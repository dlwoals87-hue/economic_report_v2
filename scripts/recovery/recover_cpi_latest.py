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
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collectors import bls_cpi  # noqa: E402


EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
RAW_PATH_RE = re.compile(r"data/raw/bls/cpi/(\d{4}-(?:0[1-9]|1[0-2]))/retrieved_[A-Za-z0-9TZ_.-]+\.json\Z")
EXPECTED_OUTPUT = "data/processed/bls/cpi_latest.json"
REQUEST_MODES = {"registered", "unregistered", "unregistered_fallback"}
SECRET_RE = re.compile(rb"(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
METRICS = tuple(bls_cpi.SOURCE_SERIES)


class RecoveryError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class RecoveryResult:
    schema_version: str
    status: str
    event_id: str | None
    reference_period: str | None
    raw_snapshot_path: str | None
    immutable_release_path: str | None
    output_path: str
    applied: bool
    network_called: bool
    external_api_called: bool
    external_ai_api_called: bool
    provider: str
    validation: dict[str, Any]
    output_sha256: str | None
    commit_paths: list[str]
    message: str

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def project_root() -> Path:
    return PROJECT_ROOT


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_relative(value: str, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RecoveryError("INVALID_INPUT", f"{label} must be a non-empty POSIX relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise RecoveryError("INVALID_INPUT", f"{label} must stay inside the project")
    return pure


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RecoveryError("INVALID_INPUT", "path escapes project root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _project_file(root: Path, value: str, label: str, *, must_exist: bool = True) -> Path:
    pure = _safe_relative(value, label)
    path = root.joinpath(*pure.parts)
    if _has_symlink_component(root, path):
        raise RecoveryError("INVALID_INPUT", f"{label} may not use a symlink")
    if must_exist and not path.is_file():
        raise RecoveryError("INVALID_INPUT", f"{label} must be a regular file")
    return path


def _read_json(path: Path, label: str, *, inspect_secrets: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RecoveryError("INVALID_INPUT", f"{label} could not be read") from exc
    if inspect_secrets and SECRET_RE.search(data):
        raise RecoveryError("INVALID_INPUT", f"{label} contains a credential-like value")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("INVALID_INPUT", f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("INVALID_INPUT", f"{label} must contain an object")
    return payload, data


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RecoveryError("INVALID_INPUT", "raw retrieved_at_utc is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryError("INVALID_INPUT", "raw retrieved_at_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RecoveryError("INVALID_INPUT", "raw retrieved_at_utc must be UTC-aware")
    return parsed.astimezone(timezone.utc)


def _calendar_event(root: Path, event_id: str) -> dict[str, Any]:
    calendar, _ = _read_json(root / "data/calendar/events.json", "calendar")
    events = calendar.get("events")
    if not isinstance(events, list):
        raise RecoveryError("INVALID_INPUT", "calendar events must be a list")
    matches = [item for item in events if isinstance(item, dict) and item.get("event_id") == event_id]
    if len(matches) != 1:
        raise RecoveryError("INVALID_INPUT", "calendar event must exist exactly once")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise RecoveryError("INVALID_INPUT", "calendar event must be US CPI")
    if not isinstance(event.get("reference_period"), str):
        raise RecoveryError("INVALID_INPUT", "calendar reference_period is invalid")
    return event


def _immutable_release(root: Path, event_id: str) -> tuple[Path, dict[str, Any]]:
    relative = f"data/releases/cpi/{event_id}/as_released.json"
    path = _project_file(root, relative, "immutable release")
    payload, _ = _read_json(path, "immutable release")
    return path, payload


def _validate_raw_metadata(raw: dict[str, Any]) -> tuple[datetime, dict[str, Any], str, bool]:
    retrieved_at = _parse_utc(raw.get("retrieved_at_utc"))
    if raw.get("provider") != "U.S. Bureau of Labor Statistics":
        raise RecoveryError("INVALID_INPUT", "raw provider is invalid")
    if raw.get("api_version") != "v2":
        raise RecoveryError("INVALID_INPUT", "raw api_version is invalid")
    request_mode = raw.get("request_mode")
    if request_mode not in REQUEST_MODES:
        raise RecoveryError("INVALID_INPUT", "raw request_mode is invalid")
    key_used = raw.get("registration_key_used")
    if not isinstance(key_used, bool):
        raise RecoveryError("INVALID_INPUT", "raw registration_key_used is invalid")
    response = raw.get("response")
    if not isinstance(response, dict):
        raise RecoveryError("INVALID_INPUT", "raw response must be an object")
    return retrieved_at, response, request_mode, key_used


def _validate_release(
    release: dict[str, Any],
    *,
    event_id: str,
    reference_period: str,
    raw_relative: str,
    retrieved_at: datetime,
    request_mode: str,
    processed: dict[str, Any],
) -> None:
    if release.get("event_id") != event_id or release.get("reference_period") != reference_period:
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable release event metadata differs")
    if release.get("capture_status") != "captured":
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable release is not captured")
    integrity = release.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("immutable") is not True:
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable release flag is invalid")
    source = release.get("source")
    if not isinstance(source, dict):
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable release source is invalid")
    if source.get("raw_snapshot_path") != raw_relative:
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable raw snapshot path differs")
    if source.get("retrieved_at_utc") != bls_cpi.iso_utc(retrieved_at):
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable retrieval time differs")
    if source.get("request_mode") != request_mode:
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "immutable request mode differs")
    release_metrics = release.get("metrics")
    processed_metrics = processed.get("metrics")
    if not isinstance(release_metrics, dict) or not isinstance(processed_metrics, dict):
        raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "release metrics are invalid")
    pairs = (
        ("actual_current_raw", "actual_as_released_raw"),
        ("actual_current_display", "actual_as_released_display"),
        ("previous_current_raw", "previous_as_released_raw"),
        ("previous_current_display", "previous_as_released_display"),
    )
    for metric in METRICS:
        current = processed_metrics.get(metric)
        captured = release_metrics.get(metric)
        if not isinstance(current, dict) or not isinstance(captured, dict):
            raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", f"metric missing: {metric}")
        for current_key, captured_key in pairs:
            if current.get(current_key) != captured.get(captured_key):
                raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", f"metric differs: {metric}.{current_key}")


def _candidate_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _exclusive_write(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = path.parents[3]
    if _has_symlink_component(root, path.parent):
        raise RecoveryError("INVALID_INPUT", "output parent may not use a symlink")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            try:
                with path.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                return True
            except FileExistsError:
                return False
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _result(
    status: str,
    *,
    event_id: str | None,
    reference_period: str | None,
    raw_snapshot_path: str | None,
    output_path: str,
    applied: bool,
    validation: dict[str, Any],
    output_sha256: str | None,
    commit_paths: list[str],
    message: str,
) -> RecoveryResult:
    immutable = f"data/releases/cpi/{event_id}/as_released.json" if event_id else None
    return RecoveryResult(
        "1.0", status, event_id, reference_period, raw_snapshot_path, immutable, output_path,
        applied, False, False, False, "BLS", validation, output_sha256, commit_paths, message,
    )


def recover(root: Path, *, event_id: str, raw_snapshot: str, output: str = EXPECTED_OUTPUT, apply: bool = False) -> RecoveryResult:
    root = root.resolve()
    raw_relative: str | None = None
    reference_period: str | None = None
    try:
        if EVENT_ID_RE.fullmatch(event_id) is None:
            raise RecoveryError("INVALID_INPUT", "event_id is invalid")
        if output != EXPECTED_OUTPUT:
            raise RecoveryError("INVALID_INPUT", "output path must be data/processed/bls/cpi_latest.json")
        raw_pure = _safe_relative(raw_snapshot, "raw snapshot")
        raw_relative = raw_pure.as_posix()
        match = RAW_PATH_RE.fullmatch(raw_relative)
        if match is None:
            raise RecoveryError("INVALID_INPUT", "raw snapshot path is invalid")
        reference_period = match.group(1)
        raw_path = _project_file(root, raw_relative, "raw snapshot")
        raw, _ = _read_json(raw_path, "raw snapshot", inspect_secrets=True)
        retrieved_at, response, request_mode, key_used = _validate_raw_metadata(raw)
        series_data, collector_validation = bls_cpi.parse_bls_response(response)
        common_period = bls_cpi.find_common_latest_period(series_data)
        if common_period != reference_period:
            raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "raw path and common reference period differ")
        event = _calendar_event(root, event_id)
        if event["reference_period"] != reference_period:
            raise RecoveryError("RECOVERY_INTEGRITY_MISMATCH", "calendar and raw reference periods differ")
        metrics = bls_cpi.build_metrics(series_data, reference_period)
        processed = bls_cpi.build_processed_payload(
            reference_period, retrieved_at, metrics, collector_validation, raw_path, root, request_mode, key_used,
        )
        release_path, release = _immutable_release(root, event_id)
        _validate_release(
            release, event_id=event_id, reference_period=reference_period, raw_relative=raw_relative,
            retrieved_at=retrieved_at, request_mode=request_mode, processed=processed,
        )
        candidate = _candidate_bytes(processed)
        digest = _sha256(candidate)
        validation = {
            "raw_metadata_valid": True,
            "calendar_reference_period": event["reference_period"],
            "common_reference_period": common_period,
            "immutable_metrics_match": True,
            "collector": collector_validation,
        }
        output_path = root / EXPECTED_OUTPUT
        if output_path.exists():
            if output_path.is_symlink() or _has_symlink_component(root, output_path):
                raise RecoveryError("INVALID_INPUT", "output path may not use a symlink")
            existing = output_path.read_bytes()
            if existing == candidate:
                return _result("ALREADY_UP_TO_DATE", event_id=event_id, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation=validation, output_sha256=digest, commit_paths=[], message="Existing output already matches the validated recovery payload.")
            return _result("RECOVERY_CONFLICT", event_id=event_id, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation=validation, output_sha256=digest, commit_paths=[], message="Existing output differs; overwrite is forbidden.")
        if not apply:
            return _result("RECOVERY_READY", event_id=event_id, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation=validation, output_sha256=digest, commit_paths=[], message="Validated offline recovery is ready; rerun with --apply to create the missing output.")
        if not _exclusive_write(output_path, candidate):
            existing = output_path.read_bytes() if output_path.is_file() and not output_path.is_symlink() else b""
            status = "ALREADY_UP_TO_DATE" if existing == candidate else "RECOVERY_CONFLICT"
            return _result(status, event_id=event_id, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation=validation, output_sha256=digest, commit_paths=[], message="Output appeared during recovery; it was not overwritten.")
        return _result("RECOVERED", event_id=event_id, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=True, validation=validation, output_sha256=digest, commit_paths=[EXPECTED_OUTPUT], message="Validated recovery output was created without a network request.")
    except RecoveryError as exc:
        return _result(exc.status, event_id=event_id if EVENT_ID_RE.fullmatch(event_id or "") else None, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation={}, output_sha256=None, commit_paths=[], message=exc.message)
    except (bls_cpi.DataValidationError, ValueError, OSError) as exc:
        return _result("INVALID_INPUT", event_id=event_id if EVENT_ID_RE.fullmatch(event_id or "") else None, reference_period=reference_period, raw_snapshot_path=raw_relative, output_path=EXPECTED_OUTPUT, applied=False, validation={}, output_sha256=None, commit_paths=[], message=str(exc))


def _result_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        try:
            resolved.relative_to(temporary_root)
        except ValueError as exc:
            raise RecoveryError("INVALID_INPUT", "result JSON must be project-relative or inside the system temp directory") from exc
        if resolved.is_symlink():
            raise RecoveryError("INVALID_INPUT", "result JSON may not be a symlink")
        return resolved
    return _project_file(root, value, "result JSON", must_exist=False)


def write_result_json(path: Path, result: RecoveryResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RecoveryError("INVALID_INPUT", "result JSON may not be a symlink")
    path.write_bytes(_candidate_bytes(result.payload()))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover missing CPI latest data from a stored BLS raw snapshot")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--raw-snapshot", required=True)
    parser.add_argument("--output", default=EXPECTED_OUTPUT)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = project_root()
    result = recover(root, event_id=args.event_id, raw_snapshot=args.raw_snapshot, output=args.output, apply=args.apply)
    try:
        write_result_json(_result_path(root, args.result_json), result)
    except RecoveryError as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        return 1
    print(result.status)
    print(f"event_id: {result.event_id or ''}")
    print(f"network_called: {str(result.network_called).lower()}")
    print(f"commit_paths: {len(result.commit_paths)}")
    return 0 if result.status in {"RECOVERY_READY", "RECOVERED", "ALREADY_UP_TO_DATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
