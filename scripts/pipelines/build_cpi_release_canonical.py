from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path, PurePath
from typing import Any
from zoneinfo import ZoneInfo


METRIC_PATHS = {
    "headline_mom": ("headline", "mom"),
    "headline_yoy": ("headline", "yoy"),
    "core_mom": ("core", "mom"),
    "core_yoy": ("core", "yoy"),
}


class ReleaseCanonicalError(Exception):
    """Raised when release canonical generation cannot continue."""


@dataclass(frozen=True)
class BuildResult:
    status: str
    event_id: str
    as_released_path: str
    output_path: str
    canonical_created: bool
    as_released_exists: bool


def import_capture_module():
    module_path = Path(__file__).with_name("capture_cpi_release.py")
    spec = importlib.util.spec_from_file_location(
        "capture_cpi_release_for_canonical",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ReleaseCanonicalError("could not load CPI release capture module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_cpi_release_for_canonical"] = module
    spec.loader.exec_module(module)
    return module


_capture_module = import_capture_module()
stable_sha256 = _capture_module.stable_sha256
CPI_METRICS = tuple(_capture_module.CPI_METRICS)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ReleaseCanonicalError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseCanonicalError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ReleaseCanonicalError(f"JSON root must be an object: {path}")
    return payload


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8")


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def parse_utc_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReleaseCanonicalError(f"{field_name}: timezone-aware ISO 8601 value required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReleaseCanonicalError(f"{field_name}: invalid timezone-aware ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise ReleaseCanonicalError(f"{field_name}: timezone offset required")
    return parsed.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def reject_parent_parts(path: PurePath, label: str) -> None:
    if any(part == ".." for part in path.parts):
        raise ReleaseCanonicalError(f"{label}: parent directory is not allowed")


def ensure_relative_source_path(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ReleaseCanonicalError(f"{field_name}: relative path string required")
    path = PurePath(value)
    if path.is_absolute():
        raise ReleaseCanonicalError(f"{field_name}: absolute path is not allowed")
    reject_parent_parts(path, field_name)
    return value.replace("\\", "/")


def resolve_output_path(root: Path, event_id: str, output: str | None) -> Path:
    if output is None:
        candidate = root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"
    else:
        requested = Path(output)
        if requested.is_absolute():
            raise ReleaseCanonicalError("--output: absolute path is not allowed")
        reject_parent_parts(requested, "--output")
        candidate = root / requested

    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseCanonicalError("--output: path must stay inside the project") from exc
    return candidate_resolved


def release_capture_path(root: Path, event_id: str) -> Path:
    return root / "data" / "releases" / "cpi" / event_id / "as_released.json"


def find_calendar_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    events = calendar.get("events")
    if not isinstance(events, list):
        raise ReleaseCanonicalError("calendar events must be a list")
    matches = [
        event
        for event in events
        if isinstance(event, dict) and event.get("event_id") == event_id
    ]
    if len(matches) != 1:
        raise ReleaseCanonicalError(f"calendar event count for {event_id} must be exactly 1")
    event = matches[0]
    if event.get("indicator_type") != "CPI":
        raise ReleaseCanonicalError("calendar event indicator_type must be CPI")
    if event.get("country") != "US":
        raise ReleaseCanonicalError("calendar event country must be US")
    if not isinstance(event.get("reference_period"), str) or not event["reference_period"]:
        raise ReleaseCanonicalError("calendar event reference_period is required")
    parse_utc_datetime(event.get("release_datetime_utc"), "release_datetime_utc")

    metrics = event.get("metrics")
    if not isinstance(metrics, dict):
        raise ReleaseCanonicalError("calendar event metrics must be an object")
    missing = [metric for metric in CPI_METRICS if metric not in metrics]
    if missing:
        raise ReleaseCanonicalError(f"calendar event missing CPI metrics: {missing}")
    for metric_key in CPI_METRICS:
        if not isinstance(metrics[metric_key], dict):
            raise ReleaseCanonicalError(f"calendar event metric {metric_key} must be an object")
    return event


def validate_release_payload(release: dict[str, Any], event: dict[str, Any]) -> None:
    if release.get("event_id") != event["event_id"]:
        raise ReleaseCanonicalError("as_released event_id does not match calendar")
    if release.get("indicator_type") != "CPI":
        raise ReleaseCanonicalError("as_released indicator_type must be CPI")
    if release.get("country") != event["country"]:
        raise ReleaseCanonicalError("as_released country does not match calendar")
    if release.get("reference_period") != event["reference_period"]:
        raise ReleaseCanonicalError("as_released reference_period does not match calendar")
    if release.get("capture_status") != "captured":
        raise ReleaseCanonicalError("as_released capture_status must be captured")
    if release.get("release_vintage") != "first_observed_after_release":
        raise ReleaseCanonicalError("as_released release_vintage must be first_observed_after_release")

    integrity = release.get("integrity")
    if not isinstance(integrity, dict):
        raise ReleaseCanonicalError("as_released integrity must be an object")
    if integrity.get("immutable") is not True:
        raise ReleaseCanonicalError("as_released integrity.immutable must be true")
    stored_sha = integrity.get("sha256")
    if not isinstance(stored_sha, str) or not stored_sha:
        raise ReleaseCanonicalError("as_released integrity.sha256 is required")
    recalculated_sha = stable_sha256(release)
    if stored_sha != recalculated_sha:
        raise ReleaseCanonicalError("as_released SHA-256 mismatch")

    metrics = release.get("metrics")
    if not isinstance(metrics, dict):
        raise ReleaseCanonicalError("as_released metrics must be an object")
    missing = [metric for metric in CPI_METRICS if metric not in metrics]
    if missing:
        raise ReleaseCanonicalError(f"as_released missing metrics: {missing}")
    for metric_key in CPI_METRICS:
        metric = metrics[metric_key]
        if not isinstance(metric, dict):
            raise ReleaseCanonicalError(f"as_released metric {metric_key} must be an object")
        for field in (
            "actual_as_released_raw",
            "actual_as_released_display",
            "previous_as_released_raw",
            "previous_as_released_display",
        ):
            if metric.get(field) in (None, ""):
                raise ReleaseCanonicalError(f"as_released metric {metric_key} missing {field}")


def parse_decimal(value: Any, metric_key: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("expected"))
    if isinstance(value, bool):
        raise ReleaseCanonicalError(f"expected value for {metric_key} must be numeric or null")
    if isinstance(value, (int, float, Decimal)):
        value = str(value)
    if not isinstance(value, str):
        raise ReleaseCanonicalError(f"expected value for {metric_key} must be numeric or null")
    text = value.strip()
    if text == "":
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ReleaseCanonicalError(f"expected value for {metric_key} is not Decimal") from exc


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_surprise_display(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%p"


def metric_expected(event: dict[str, Any], metric_key: str) -> Decimal | None:
    metrics = event.get("metrics")
    if not isinstance(metrics, dict):
        return None
    metric = metrics.get(metric_key)
    if not isinstance(metric, dict):
        return None
    return parse_decimal(metric.get("expected"), metric_key)


def build_surprise(actual_raw: Any, expected: Decimal | None) -> dict[str, str] | None:
    if expected is None:
        return None
    try:
        actual = Decimal(str(actual_raw))
    except InvalidOperation as exc:
        raise ReleaseCanonicalError(f"actual_as_released_raw is not Decimal: {actual_raw}") from exc
    with localcontext() as context:
        context.prec = 34
        surprise = actual - expected
    if surprise > 0:
        direction = "above_expected"
    elif surprise < 0:
        direction = "below_expected"
    else:
        direction = "in_line"
    return {
        "raw": decimal_to_plain(surprise),
        "display": format_surprise_display(surprise),
        "direction": direction,
    }


def build_metric(metric_key: str, release_metric: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    expected = metric_expected(event, metric_key)
    event_metric = event["metrics"].get(metric_key, {})
    unit = event_metric.get("unit") if isinstance(event_metric, dict) else None
    return {
        "actual_as_released_raw": str(release_metric["actual_as_released_raw"]),
        "actual_as_released_display": str(release_metric["actual_as_released_display"]),
        "previous_as_released_raw": str(release_metric["previous_as_released_raw"]),
        "previous_as_released_display": str(release_metric["previous_as_released_display"]),
        "expected": None if expected is None else decimal_to_plain(expected),
        "unit": str(unit or release_metric.get("unit") or "%"),
        "surprise": build_surprise(release_metric["actual_as_released_raw"], expected),
    }


def build_canonical_payload(
    event: dict[str, Any],
    release: dict[str, Any],
    profiles: dict[str, Any],
    release_path_value: str,
) -> dict[str, Any]:
    release_dt = parse_utc_datetime(event["release_datetime_utc"], "release_datetime_utc")
    profile = profiles.get("CPI", {}) if isinstance(profiles, dict) else {}
    release_source = release.get("source") if isinstance(release.get("source"), dict) else {}
    metrics = release["metrics"]

    canonical_event: dict[str, Any] = {
        "headline": {},
        "core": {},
    }
    for metric_key in CPI_METRICS:
        section, cadence = METRIC_PATHS[metric_key]
        canonical_event[section][cadence] = build_metric(metric_key, metrics[metric_key], event)

    canonical_event["consensus"] = {
        "source": event.get("consensus_source"),
        "status": event.get("consensus_status") or "not_entered",
        "entered_at_utc": event.get("entered_at_utc"),
    }

    raw_snapshot_path = ensure_relative_source_path(
        release_source.get("raw_snapshot_path"),
        "source.raw_snapshot_path",
    )
    sha256 = release["integrity"]["sha256"]
    return {
        "schema_version": "1.0",
        "meta": {
            "event_id": event["event_id"],
            "indicator_type": "CPI",
            "indicator_name": profile.get("display_name", "CPI"),
            "country": event["country"],
            "reference_period": event["reference_period"],
            "release_datetime_utc": iso_utc(release_dt),
            "release_datetime_kst": iso_kst(release_dt),
            "is_sample": False,
            "data_origin": "bls_release_capture",
            "data_status": "release_captured",
            "analysis_status": "pending",
        },
        "event": canonical_event,
        "source": {
            "provider": release_source.get("provider") or "U.S. Bureau of Labor Statistics",
            "release_capture_path": release_path_value,
            "release_capture_sha256": sha256,
            "release_vintage": release["release_vintage"],
            "captured_at_utc": release.get("captured_at_utc"),
            "raw_snapshot_path": raw_snapshot_path,
            "request_mode": release_source.get("request_mode"),
        },
        "analysis": {
            "status": "pending",
            "provider": None,
            "model": None,
            "generated_at_utc": None,
            "summary_html": None,
            "key_points": [],
        },
    }


def write_canonical(path: Path, payload: dict[str, Any]) -> str:
    if path.exists():
        existing = read_json(path)
        if existing == payload:
            return "ALREADY_UP_TO_DATE"
        raise ReleaseCanonicalError("existing canonical_release.json differs; refusing to overwrite")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_bytes(payload).decode("utf-8"))
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return "CANONICAL_CREATED"


def build_from_files(root: Path, event_id: str, output: str | None = None) -> BuildResult:
    output_path = resolve_output_path(root, event_id, output)
    calendar = read_json(root / "data" / "calendar" / "events.json")
    event = find_calendar_event(calendar, event_id)
    capture_path = release_capture_path(root, event_id)
    capture_path_value = relative_path(capture_path, root)

    if not capture_path.exists():
        return BuildResult(
            status="RELEASE_NOT_CAPTURED",
            event_id=event_id,
            as_released_path=capture_path_value,
            output_path=relative_path(output_path, root),
            canonical_created=False,
            as_released_exists=False,
        )

    release = read_json(capture_path)
    validate_release_payload(release, event)
    profiles = read_json(root / "data" / "indicator_profiles.json")
    canonical = build_canonical_payload(event, release, profiles, capture_path_value)
    status = write_canonical(output_path, canonical)
    return BuildResult(
        status=status,
        event_id=event_id,
        as_released_path=capture_path_value,
        output_path=relative_path(output_path, root),
        canonical_created=status == "CANONICAL_CREATED",
        as_released_exists=True,
    )


def print_result(result: BuildResult) -> None:
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"as_released_path: {result.as_released_path}")
    print(f"as_released_exists: {str(result.as_released_exists).lower()}")
    print(f"output: {result.output_path}")
    print(f"canonical_created: {str(result.canonical_created).lower()}")
    print("BLS API calls: 0")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        result = build_from_files(project_root(), args.event_id, output=args.output)
    except ReleaseCanonicalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
