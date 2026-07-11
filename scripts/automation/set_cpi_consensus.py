from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validators import validate_calendar_events  # noqa: E402


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
MOM_METRICS = {"headline_mom", "core_mom"}
SOURCE_SECRET_RE = re.compile(r"api[ _-]?key|token|password|secret", re.IGNORECASE)


class ConsensusEntryError(Exception):
    """Raised when consensus input cannot be safely previewed or applied."""


@dataclass(frozen=True)
class EntryResult:
    status: str
    event_id: str
    reference_period: str
    release_datetime_kst: str
    file_modified: bool
    consensus_status: str
    source: str
    entered_at_utc: str
    metrics: dict[str, dict[str, str]]
    warnings: tuple[str, ...]
    before_sha256: str | None
    after_sha256: str | None
    next_action: str

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = "1.0"
        data["warnings"] = list(self.warnings)
        return data


def project_root() -> Path:
    return PROJECT_ROOT


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConsensusEntryError(f"file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsensusEntryError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ConsensusEntryError("calendar JSON root must be an object")
    return payload


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ConsensusEntryError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsensusEntryError(f"{field} must be timezone-aware ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ConsensusEntryError(f"{field} must be timezone-aware ISO 8601")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_metric(value: Any, metric: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConsensusEntryError(f"{metric}: non-empty Decimal value is required")
    text = value.strip()
    if any(token in text for token in ("%", ",")):
        raise ConsensusEntryError(f"{metric}: percent and comma characters are not allowed")
    if text.lower() in {"nan", "+nan", "-nan", "infinity", "+infinity", "-infinity", "inf", "+inf", "-inf"}:
        raise ConsensusEntryError(f"{metric}: finite Decimal value is required")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ConsensusEntryError(f"{metric}: Decimal value is required") from exc
    if not parsed.is_finite():
        raise ConsensusEntryError(f"{metric}: finite Decimal value is required")
    lower, upper = (Decimal("-10"), Decimal("10")) if metric in MOM_METRICS else (Decimal("-20"), Decimal("30"))
    if parsed < lower or parsed > upper:
        raise ConsensusEntryError(f"{metric}: value is outside the input safety range")
    return decimal_text(parsed)


def normalize_source(value: Any) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value.strip():
        raise ConsensusEntryError("source is required")
    source = value.strip()
    if "://" in source or SOURCE_SECRET_RE.search(source):
        raise ConsensusEntryError("source must be a source name without URL or credentials")
    mixed = any(marker in source.lower() for marker in (";", " and ", " + ", "multiple source", "multiple sources"))
    warnings = ("Confirm all four values come from one source at the same time.",) if mixed else ()
    return source, warnings


def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise ConsensusEntryError("event_id is invalid")
    events = calendar.get("events")
    if not isinstance(events, list):
        raise ConsensusEntryError("calendar events must be a list")
    matches = [event for event in events if isinstance(event, dict) and event.get("event_id") == event_id]
    if len(matches) != 1:
        raise ConsensusEntryError("event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise ConsensusEntryError("target event must be US CPI")
    if not isinstance(event.get("reference_period"), str) or not event["reference_period"]:
        raise ConsensusEntryError("reference_period is required")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    metrics = event.get("metrics")
    if not isinstance(metrics, dict) or any(not isinstance(metrics.get(metric), dict) for metric in CPI_METRICS):
        raise ConsensusEntryError("target event CPI metrics are invalid")
    return event


def validate_calendar(payload: dict[str, Any], now_utc: datetime) -> None:
    result = validate_calendar_events.validate_events_payload(payload, now=now_utc)
    if not result.valid:
        raise ConsensusEntryError(f"calendar validation failed: {result.errors[0]}")


def path_is_safe(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    resolved_temp = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent.exists()):
        return False
    return any(resolved.is_relative_to(base) for base in (resolved_root, resolved_temp))


def resolve_user_path(root: Path, value: str | None, default: Path, field: str) -> Path:
    if value is None:
        return default
    candidate = Path(value)
    if ".." in candidate.parts:
        raise ConsensusEntryError(f"{field}: parent directory is not allowed")
    if not candidate.is_absolute():
        candidate = root / candidate
    if not path_is_safe(candidate, root):
        raise ConsensusEntryError(f"{field}: path must stay inside the project or tempfile and cannot use symlinks")
    return candidate


def snapshot_exists(root: Path, event_id: str) -> bool:
    return (root / "data" / "consensus" / "cpi" / event_id / "consensus_snapshot.json").exists()


def existing_input_matches(event: dict[str, Any], values: dict[str, str], source: str, entered_at_utc: str) -> bool:
    metrics = event.get("metrics", {})
    return (
        event.get("consensus_status") == "complete"
        and event.get("consensus_source") == source
        and event.get("entered_at_utc") == entered_at_utc
        and all(metrics.get(metric, {}).get("expected") == values[metric] for metric in CPI_METRICS)
    )


def all_expected_null(event: dict[str, Any]) -> bool:
    metrics = event.get("metrics", {})
    return all(metrics.get(metric, {}).get("expected") is None for metric in CPI_METRICS)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_result(path: Path, result: EntryResult) -> None:
    if path.exists() and path.is_symlink():
        raise ConsensusEntryError("result-json: symlinks are not allowed")
    atomic_write(path, canonical_json(result.payload()).encode("utf-8"))


def set_consensus(
    root: Path,
    *,
    event_id: str,
    metric_values: dict[str, Any],
    source: Any,
    mode: str,
    entered_at_utc: str | None = None,
    now_utc: datetime | None = None,
    events_path: Path | None = None,
    validate_func: Callable[[dict[str, Any], datetime], None] = validate_calendar,
) -> EntryResult:
    if mode not in {"preview", "apply"}:
        raise ConsensusEntryError("exactly one of preview or apply is required")
    root = root.resolve()
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events_file = events_path or root / "data" / "calendar" / "events.json"
    if not path_is_safe(events_file, root):
        raise ConsensusEntryError("events: path is unsafe")
    original_bytes = events_file.read_bytes()
    calendar = read_json(events_file)
    validate_func(calendar, now)
    event = find_event(calendar, event_id)
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    if now >= release:
        return EntryResult("CONSENSUS_ENTRY_WINDOW_EXPIRED", event_id, event["reference_period"], iso_kst(release), False, str(event.get("consensus_status")), "", "", {}, (), None, None, "none")
    values = {metric: parse_metric(metric_values.get(metric), metric) for metric in CPI_METRICS}
    normalized_source, source_warnings = normalize_source(source)
    entered = parse_utc(entered_at_utc, "entered_at_utc") if entered_at_utc else now
    if entered > now:
        raise ConsensusEntryError("entered_at_utc must not be in the future")
    if entered >= release:
        raise ConsensusEntryError("entered_at_utc must be before release_datetime_utc")
    entered_text = iso_utc(entered)
    metrics_result = {metric: {"expected": values[metric]} for metric in CPI_METRICS}
    warnings = source_warnings + (
        "Apply and lock must both finish before release.",
        "Run validate_calendar_events.py after apply.",
        "Run lock_cpi_consensus.py separately after apply.",
        "Do not change values after the immutable snapshot is locked.",
    )
    if snapshot_exists(root, event_id):
        return EntryResult("CONSENSUS_ALREADY_LOCKED", event_id, event["reference_period"], iso_kst(release), False, str(event.get("consensus_status")), normalized_source, entered_text, metrics_result, warnings, None, None, "none")
    if not all_expected_null(event):
        status = "CONSENSUS_ALREADY_APPLIED" if existing_input_matches(event, values, normalized_source, entered_text) else "CONSENSUS_INPUT_CONFLICT"
        return EntryResult(status, event_id, event["reference_period"], iso_kst(release), False, str(event.get("consensus_status")), normalized_source, entered_text, metrics_result, warnings, None, None, "none")
    if mode == "preview":
        return EntryResult("CONSENSUS_PREVIEW", event_id, event["reference_period"], iso_kst(release), False, "complete", normalized_source, entered_text, metrics_result, warnings, None, None, "review_then_apply")
    updated = json.loads(json.dumps(calendar))
    target = find_event(updated, event_id)
    for metric in CPI_METRICS:
        target["metrics"][metric]["expected"] = values[metric]
    target["consensus_source"] = normalized_source
    target["consensus_status"] = "complete"
    target["entered_at_utc"] = entered_text
    validate_func(updated, now)
    atomic_write(events_file, canonical_json(updated).encode("utf-8"))
    return EntryResult("CONSENSUS_APPLIED", event_id, event["reference_period"], iso_kst(release), True, "complete", normalized_source, entered_text, metrics_result, warnings, sha256_bytes(original_bytes), sha256_bytes(events_file.read_bytes()), "lock_cpi_consensus.py")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely enter CPI consensus before release")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--headline-mom", required=True)
    parser.add_argument("--headline-yoy", required=True)
    parser.add_argument("--core-mom", required=True)
    parser.add_argument("--core-yoy", required=True)
    parser.add_argument("--source", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--entered-at-utc")
    parser.add_argument("--events")
    parser.add_argument("--result-json")
    parser.add_argument("--now-utc")
    return parser.parse_args(argv)


def print_result(result: EntryResult) -> None:
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"reference_period: {result.reference_period}")
    print(f"release_datetime_kst: {result.release_datetime_kst}")
    print(f"source: {result.source}")
    for metric in CPI_METRICS:
        if metric in result.metrics:
            print(f"{metric}: {result.metrics[metric]['expected']}")
    print(f"entered_at_utc: {result.entered_at_utc}")
    print(f"consensus_status: {result.consensus_status}")
    print(f"file_modified: {str(result.file_modified).lower()}")
    if result.before_sha256:
        print(f"before_sha256: {result.before_sha256}")
        print(f"after_sha256: {result.after_sha256}")
    print(f"next_action: {result.next_action}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        now = parse_utc(args.now_utc, "--now-utc") if args.now_utc else None
        root = project_root()
        events_file = resolve_user_path(root, args.events, root / "data" / "calendar" / "events.json", "events")
        result = set_consensus(
            root,
            event_id=args.event_id,
            metric_values={
                "headline_mom": args.headline_mom,
                "headline_yoy": args.headline_yoy,
                "core_mom": args.core_mom,
                "core_yoy": args.core_yoy,
            },
            source=args.source,
            mode="apply" if args.apply else "preview",
            entered_at_utc=args.entered_at_utc,
            now_utc=now,
            events_path=events_file,
        )
        result_path = resolve_user_path(root, args.result_json, root / "result.json", "result-json") if args.result_json else None
        if result_path:
            write_result(result_path, result)
    except ConsensusEntryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
