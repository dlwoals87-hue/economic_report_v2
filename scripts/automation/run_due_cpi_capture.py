from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


CAPTURE_WINDOW_HOURS = 24
RESULT_SCHEMA_VERSION = "1.0"
MAX_COMMIT_FILES = 3
ALLOWED_COMMIT_PATTERNS = (
    "data/releases/cpi/*/as_released.json",
    "data/raw/bls/cpi/*/retrieved_*.json",
    "data/processed/bls/cpi_latest.json",
)


class AutomationError(Exception):
    """Raised for invalid automated capture conditions."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_utc_datetime(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AutomationError(f"{field_name}: timezone-aware ISO 8601 value required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AutomationError(f"{field_name}: invalid timezone-aware ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise AutomationError(f"{field_name}: timezone offset required")
    return parsed.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise AutomationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AutomationError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AutomationError(f"JSON root must be an object: {path}")
    return payload


def write_result_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sanitize_secret_text(text: str, secret: str | None = None) -> str:
    secret_value = secret if secret is not None else os.environ.get("BLS_API_KEY")
    if secret_value:
        return text.replace(secret_value, "[REDACTED]")
    return text


def import_capture_module(root: Path):
    module_path = root / "scripts" / "pipelines" / "capture_cpi_release.py"
    spec = importlib.util.spec_from_file_location("capture_cpi_release_for_due", module_path)
    if spec is None or spec.loader is None:
        raise AutomationError("could not load capture_cpi_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_cpi_release_for_due"] = module
    spec.loader.exec_module(module)
    return module


def release_path(root: Path, event_id: str) -> Path:
    return root / "data" / "releases" / "cpi" / event_id / "as_released.json"


def capture_window_end(release_dt: datetime) -> datetime:
    return release_dt + timedelta(hours=CAPTURE_WINDOW_HOURS)


def find_due_events(root: Path, calendar: dict[str, Any], now_utc: datetime) -> list[dict[str, Any]]:
    events = calendar.get("events")
    if not isinstance(events, list):
        raise AutomationError("calendar events must be a list")
    event_ids: set[str] = set()
    duplicates: set[str] = set()
    due: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            if event_id in event_ids:
                duplicates.add(event_id)
            event_ids.add(event_id)
        if event.get("indicator_type") != "CPI":
            continue
        if not isinstance(event_id, str) or not event_id:
            continue
        if release_path(root, event_id).exists():
            continue
        release_dt = parse_utc_datetime(event.get("release_datetime_utc"), f"{event_id}.release_datetime_utc")
        if release_dt <= now_utc <= capture_window_end(release_dt):
            due.append(event)
    due_ids = {event.get("event_id") for event in due}
    duplicate_due = sorted(item for item in duplicates if item in due_ids)
    if duplicate_due:
        raise AutomationError(f"duplicate due event_id: {', '.join(duplicate_due)}")
    return due


def empty_result(status: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "event_id": None,
        "reference_period": None,
        "captured": False,
        "as_released_path": None,
        "raw_snapshot_path": None,
        "processed_path": None,
        "commit_paths": [],
        "api_called": False,
        "request_mode": None,
        "message": message,
    }


def result_from_capture(capture_result: Any) -> dict[str, Any]:
    status = capture_result.status
    captured = status == "CAPTURED"
    as_released_path = capture_result.as_released_path if captured else None
    raw_snapshot_path = capture_result.raw_snapshot_path if captured else None
    processed_path = capture_result.processed_path if captured else None
    commit_paths = []
    if captured:
        commit_paths = [as_released_path, raw_snapshot_path, processed_path]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "event_id": capture_result.event_id,
        "reference_period": capture_result.reference_period,
        "captured": captured,
        "as_released_path": as_released_path,
        "raw_snapshot_path": raw_snapshot_path,
        "processed_path": processed_path,
        "commit_paths": [path for path in commit_paths if path],
        "api_called": int(capture_result.api_call_count or 0) > 0,
        "request_mode": capture_result.request_mode,
        "message": status,
    }


def is_safe_relative_path(path: str) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if "\\" in path:
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return False
    return ".." not in pure.parts


def is_allowed_commit_path(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in ALLOWED_COMMIT_PATTERNS)


def validate_commit_paths(root: Path, commit_paths: list[str]) -> None:
    if len(commit_paths) > MAX_COMMIT_FILES:
        raise AutomationError("too many commit paths")
    secret = os.environ.get("BLS_API_KEY")
    for path in commit_paths:
        if not is_safe_relative_path(path):
            raise AutomationError(f"unsafe commit path: {path}")
        if not is_allowed_commit_path(path):
            raise AutomationError(f"commit path not allowed: {path}")
        full_path = (root / path).resolve()
        try:
            full_path.relative_to(root.resolve())
        except ValueError as exc:
            raise AutomationError(f"commit path outside project: {path}") from exc
        if not full_path.exists():
            raise AutomationError(f"commit path missing: {path}")
        if full_path.is_symlink():
            raise AutomationError(f"commit path is symlink: {path}")
        if secret and secret in full_path.read_text(encoding="utf-8", errors="ignore"):
            raise AutomationError(f"secret value found in commit path: {path}")


def run_due_capture(
    root: Path,
    now_utc: datetime | None = None,
    event_id: str | None = None,
    capture_func: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], int]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    calendar = read_json(root / "data" / "calendar" / "events.json")
    capture_module = None
    capture = capture_func
    if capture is None:
        capture_module = import_capture_module(root)
        capture = capture_module.capture_release

    if event_id:
        capture_result = capture(root, event_id, now_utc=now)
        result = result_from_capture(capture_result)
        if result["captured"]:
            validate_commit_paths(root, result["commit_paths"])
        return result, 0

    due_events = find_due_events(root, calendar, now)
    if not due_events:
        return empty_result("NO_DUE_EVENT", "No CPI event is due for capture."), 0
    if len(due_events) > 1:
        result = empty_result("MULTIPLE_DUE_EVENTS", "Multiple CPI events are due; refusing to choose.")
        result["due_event_ids"] = [event["event_id"] for event in due_events]
        return result, 1

    selected_event_id = due_events[0]["event_id"]
    capture_result = capture(root, selected_event_id, now_utc=now)
    result = result_from_capture(capture_result)
    if result["captured"]:
        validate_commit_paths(root, result["commit_paths"])
    return result, 0


def print_summary(result: dict[str, Any]) -> None:
    print(result["status"])
    print(f"event_id: {result.get('event_id')}")
    print(f"reference_period: {result.get('reference_period')}")
    print(f"captured: {str(result.get('captured')).lower()}")
    print(f"api_called: {str(result.get('api_called')).lower()}")
    print(f"commit_paths: {len(result.get('commit_paths') or [])}")
    if result.get("request_mode"):
        print(f"request_mode: {result['request_mode']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id")
    parser.add_argument("--now-utc")
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()

    root = project_root()
    try:
        now = parse_utc_datetime(args.now_utc, "--now-utc") if args.now_utc else None
        result, exit_code = run_due_capture(root, now_utc=now, event_id=args.event_id or None)
    except Exception as exc:
        result = empty_result("ERROR", sanitize_secret_text(str(exc)))
        exit_code = 1

    result_path = Path(args.result_json)
    write_result_json(result_path, result)
    print_summary(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
