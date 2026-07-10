from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


METRIC_KEYS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")

METRIC_PATHS = {
    "headline_mom": ("headline", "mom"),
    "headline_yoy": ("headline", "yoy"),
    "core_mom": ("core", "mom"),
    "core_yoy": ("core", "yoy"),
}


class CanonicalBuildError(Exception):
    """Raised when CPI canonical generation cannot continue."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CanonicalBuildError(f"Required input does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise CanonicalBuildError(f"Invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CanonicalBuildError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def minimal_calendar_event(reference_period: str) -> dict[str, Any]:
    return {
        "event_id": f"US_CPI_{reference_period.replace('-', '_')}",
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": "2026-06-10T12:30:00Z",
        "metrics": {
            key: {
                "expected": None,
                "unit": "%",
            }
            for key in METRIC_KEYS
        },
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def ensure_calendar_events(path: Path, reference_period: str) -> dict[str, Any]:
    if path.exists():
        calendar = read_json(path)
        events = calendar.get("events")
        if not isinstance(events, list):
            raise CanonicalBuildError("data/calendar/events.json must contain an events list.")
    else:
        calendar = {
            "version": 1,
            "description": "Manual economic calendar inputs. Expected values are not auto-generated.",
            "events": [],
        }
        events = calendar["events"]

    matches = find_calendar_events(calendar, "CPI", reference_period)
    if not matches:
        events.append(minimal_calendar_event(reference_period))
        write_json(path, calendar)
    return calendar


def validate_processed_cpi(processed: dict[str, Any]) -> None:
    if processed.get("indicator_type") != "CPI":
        raise CanonicalBuildError("Processed BLS input indicator_type must be CPI.")
    metrics = processed.get("metrics")
    if not isinstance(metrics, dict):
        raise CanonicalBuildError("Processed BLS input missing metrics object.")
    missing = [key for key in METRIC_KEYS if key not in metrics]
    if missing:
        raise CanonicalBuildError(f"Processed BLS input missing metrics: {missing}")
    for key in METRIC_KEYS:
        metric = metrics[key]
        if not isinstance(metric, dict):
            raise CanonicalBuildError(f"Metric {key} must be an object.")
        for field in (
            "actual_current_raw",
            "actual_current_display",
            "previous_current_raw",
            "previous_current_display",
        ):
            if metric.get(field) in (None, ""):
                raise CanonicalBuildError(f"Metric {key} missing {field}.")


def find_calendar_events(
    calendar: dict[str, Any],
    indicator_type: str,
    reference_period: str,
) -> list[dict[str, Any]]:
    events = calendar.get("events", [])
    if not isinstance(events, list):
        raise CanonicalBuildError("Calendar events must be a list.")
    matches = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_reference = event.get("reference_period", event.get("period"))
        if event.get("indicator_type") == indicator_type and event_reference == reference_period:
            matches.append(event)
    return matches


def select_calendar_event(
    calendar: dict[str, Any],
    indicator_type: str,
    reference_period: str,
) -> tuple[dict[str, Any] | None, str]:
    matches = find_calendar_events(calendar, indicator_type, reference_period)
    if len(matches) > 1:
        raise CanonicalBuildError(
            f"Duplicate calendar events for {indicator_type} {reference_period}."
        )
    if not matches:
        print(f"WARNING: calendar event missing for {indicator_type} {reference_period}")
        return None, "missing_event"
    event = matches[0]
    return event, str(event.get("consensus_status") or "not_entered")


def parse_utc_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CanonicalBuildError("release_datetime_utc must be a non-empty string.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CanonicalBuildError(f"Invalid release_datetime_utc: {value}") from exc
    if parsed.tzinfo is None:
        raise CanonicalBuildError("release_datetime_utc must include timezone information.")
    return parsed.astimezone(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def parse_decimal_value(value: Any, metric_key: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("expected"))
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        raise CanonicalBuildError(f"Expected value for {metric_key} must be string/number/null.")
    text = value.strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    if text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CanonicalBuildError(f"Expected value for {metric_key} is not Decimal: {value}") from exc


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_percent_display(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%"


def metric_expected(event: dict[str, Any] | None, metric_key: str) -> Decimal | None:
    if event is None:
        return None
    metrics = event.get("metrics")
    if isinstance(metrics, dict) and metric_key in metrics:
        metric = metrics[metric_key]
        if isinstance(metric, dict):
            return parse_decimal_value(metric.get("expected"), metric_key)
        return parse_decimal_value(metric, metric_key)
    expected = event.get("expected")
    if isinstance(expected, dict) and metric_key in expected:
        return parse_decimal_value(expected[metric_key], metric_key)
    return None


def build_surprise(actual_raw: str, expected: Decimal | None) -> dict[str, Any] | None:
    if expected is None:
        return None
    try:
        actual = Decimal(actual_raw)
    except InvalidOperation as exc:
        raise CanonicalBuildError(f"Actual value is not Decimal: {actual_raw}") from exc
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
        "surprise_raw": decimal_to_plain(surprise),
        "surprise_display": format_percent_display(surprise),
        "direction": direction,
        "unit": "%p",
    }


def build_metric_payload(
    metric_key: str,
    bls_metric: dict[str, Any],
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    expected = metric_expected(event, metric_key)
    expected_raw = None if expected is None else decimal_to_plain(expected)
    return {
        "actual_current_raw": str(bls_metric["actual_current_raw"]),
        "actual_current_display": str(bls_metric["actual_current_display"]),
        "actual_as_released": bls_metric.get("actual_as_released"),
        "previous_current_raw": str(bls_metric["previous_current_raw"]),
        "previous_current_display": str(bls_metric["previous_current_display"]),
        "previous_as_released": bls_metric.get("previous_as_released"),
        "expected": expected_raw,
        "unit": str(bls_metric.get("unit") or "%"),
        "surprise": build_surprise(str(bls_metric["actual_current_raw"]), expected),
    }


def build_canonical_payload(
    processed: dict[str, Any],
    calendar: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    validate_processed_cpi(processed)
    reference_period = processed.get("reference_period")
    if not isinstance(reference_period, str) or not reference_period:
        raise CanonicalBuildError("Processed BLS input missing reference_period.")

    event, consensus_status = select_calendar_event(calendar, "CPI", reference_period)
    release_datetime = parse_utc_datetime(
        event.get("release_datetime_utc") if event is not None else None
    )

    profile = profiles.get("CPI", {}) if isinstance(profiles, dict) else {}
    metrics = processed["metrics"]
    canonical_event: dict[str, Any] = {
        "headline": {},
        "core": {},
    }
    for metric_key in METRIC_KEYS:
        section, cadence = METRIC_PATHS[metric_key]
        canonical_event[section][cadence] = build_metric_payload(
            metric_key=metric_key,
            bls_metric=metrics[metric_key],
            event=event,
        )

    canonical_event["consensus"] = {
        "source": event.get("consensus_source") if event is not None else None,
        "status": consensus_status,
    }
    first_metric = metrics["headline_mom"]
    canonical_event["revision"] = {
        "actual_as_released_status": first_metric.get("as_released_status"),
        "previous_as_released_status": first_metric.get("previous_as_released_status"),
    }

    return {
        "schema_version": "1.0",
        "meta": {
            "indicator_type": "CPI",
            "indicator_name": profile.get("display_name", "CPI"),
            "country": profile.get("country", "US"),
            "reference_period": reference_period,
            "release_datetime_utc": iso_utc(release_datetime),
            "release_datetime_kst": iso_kst(release_datetime),
            "is_sample": False,
            "data_origin": "live_bls",
            "data_status": "actual_collected",
            "analysis_status": "pending",
        },
        "event": canonical_event,
        "source": {
            "provider": "U.S. Bureau of Labor Statistics",
            "processed_input_path": "data/processed/bls/cpi_latest.json",
            "raw_snapshot_path": processed.get("raw_snapshot_path"),
            "retrieved_at_utc": processed.get("retrieved_at_utc"),
            "request_mode": processed.get("request_mode"),
        },
        "analysis": {
            "status": "pending",
            "generated_by": None,
            "generated_at_utc": None,
            "summary_html": None,
            "key_points": [],
        },
    }


def build_from_files(root: Path) -> dict[str, Any]:
    processed_path = root / "data" / "processed" / "bls" / "cpi_latest.json"
    calendar_path = root / "data" / "calendar" / "events.json"
    profiles_path = root / "data" / "indicator_profiles.json"
    output_path = root / "data" / "generated" / "cpi" / "canonical_cpi_latest.json"

    processed = read_json(processed_path)
    reference_period = processed.get("reference_period")
    if not isinstance(reference_period, str) or not reference_period:
        raise CanonicalBuildError("Processed BLS input missing reference_period.")
    calendar = ensure_calendar_events(calendar_path, reference_period)
    profiles = read_json(profiles_path)
    canonical = build_canonical_payload(processed, calendar, profiles)
    write_json(output_path, canonical)
    return canonical


def main() -> int:
    try:
        canonical = build_from_files(project_root())
    except CanonicalBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    meta = canonical["meta"]
    consensus = canonical["event"]["consensus"]
    print("OK: canonical CPI JSON generated")
    print(f"indicator_type: {meta['indicator_type']}")
    print(f"reference_period: {meta['reference_period']}")
    print(f"consensus_status: {consensus['status']}")
    print("output: data/generated/cpi/canonical_cpi_latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
