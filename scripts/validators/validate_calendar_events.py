from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
VALID_CONSENSUS_STATUSES = {"not_entered", "partial", "complete"}
REFERENCE_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    events: int
    complete: int
    partial: int
    not_entered: int

    @property
    def valid(self) -> bool:
        return not self.errors


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def parse_datetime(value: Any, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: required timezone-aware ISO 8601 datetime")
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"{path}: invalid timezone-aware ISO 8601 datetime")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{path}: timezone offset required")
        return None
    return parsed.astimezone(timezone.utc)


def expected_state(value: Any, path: str, errors: list[str]) -> str:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        errors.append(f"{path}: invalid numeric value")
        return "invalid"
    if isinstance(value, (int, float, Decimal)):
        try:
            Decimal(str(value))
        except InvalidOperation:
            errors.append(f"{path}: invalid numeric value")
            return "invalid"
        return "entered"
    if isinstance(value, str):
        if value == "":
            errors.append(f"{path}: invalid numeric value")
            return "invalid"
        if "%" in value:
            errors.append(f"{path}: percent sign is not allowed")
            return "invalid"
        try:
            Decimal(value)
        except InvalidOperation:
            errors.append(f"{path}: invalid numeric value")
            return "invalid"
        return "entered"
    errors.append(f"{path}: invalid numeric value")
    return "invalid"


def expected_status(states: list[str]) -> str:
    entered = sum(1 for state in states if state == "entered")
    if entered == 0:
        return "not_entered"
    if entered == len(states):
        return "complete"
    return "partial"


def validate_cpi_metrics(event: dict[str, Any], event_path: str, errors: list[str]) -> list[str]:
    metrics = event.get("metrics")
    if not isinstance(metrics, dict):
        errors.append(f"{event_path}.metrics: required object")
        return ["invalid"] * len(CPI_METRICS)

    states: list[str] = []
    for metric_key in CPI_METRICS:
        metric_path = f"{event_path}.metrics.{metric_key}"
        metric = metrics.get(metric_key)
        if not isinstance(metric, dict):
            errors.append(f"{metric_path}: required object")
            states.append("invalid")
            continue
        if metric.get("unit") != "%":
            errors.append(f"{metric_path}.unit: must be %")
        if "surprise" in metric and metric.get("expected") is None and metric.get("surprise") is not None:
            errors.append(f"{metric_path}.surprise: must be null when expected is null")
        states.append(expected_state(metric.get("expected"), f"{metric_path}.expected", errors))
    return states


def validate_events_payload(payload: dict[str, Any], now: datetime | None = None) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    counts = {"complete": 0, "partial": 0, "not_entered": 0}
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    events = payload.get("events")
    if not isinstance(events, list):
        return ValidationResult(
            errors=["events: required array"],
            warnings=[],
            events=0,
            complete=0,
            partial=0,
            not_entered=0,
        )

    event_ids: set[str] = set()
    for index, event in enumerate(events):
        event_path = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{event_path}: required object")
            continue

        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            errors.append(f"{event_path}.event_id: required string")
        elif event_id in event_ids:
            errors.append(f"{event_path}.event_id: duplicate event_id")
        else:
            event_ids.add(event_id)

        if not event.get("indicator_type"):
            errors.append(f"{event_path}.indicator_type: required")
        if not event.get("country"):
            errors.append(f"{event_path}.country: required")

        reference_period = event.get("reference_period")
        if not isinstance(reference_period, str) or not REFERENCE_PERIOD_RE.match(reference_period):
            errors.append(f"{event_path}.reference_period: must be YYYY-MM")

        release_dt = parse_datetime(
            event.get("release_datetime_utc"),
            f"{event_path}.release_datetime_utc",
            errors,
        )

        metric_states: list[str] = []
        if event.get("indicator_type") == "CPI":
            metric_states = validate_cpi_metrics(event, event_path, errors)
        actual_status = expected_status(metric_states) if metric_states else "not_entered"
        if actual_status in counts:
            counts[actual_status] += 1

        consensus_status = event.get("consensus_status")
        if consensus_status not in VALID_CONSENSUS_STATUSES:
            errors.append(f"{event_path}.consensus_status: invalid status")
        elif consensus_status != actual_status:
            errors.append(
                f"{event_path}.consensus_status: expected {actual_status} from metric inputs"
            )

        has_expected = actual_status in {"partial", "complete"}
        if has_expected:
            source = event.get("consensus_source")
            if not isinstance(source, str) or not source.strip():
                errors.append(f"{event_path}.consensus_source: required when expected is entered")

            entered_dt = parse_datetime(
                event.get("entered_at_utc"),
                f"{event_path}.entered_at_utc",
                errors,
            )
            if entered_dt is not None:
                if entered_dt > now_utc:
                    errors.append(f"{event_path}.entered_at_utc: must not be in the future")
                if release_dt is not None and entered_dt >= release_dt:
                    errors.append(
                        f"{event_path}.entered_at_utc: must be before release_datetime_utc"
                    )

    return ValidationResult(
        errors=errors,
        warnings=warnings,
        events=len(events),
        complete=counts["complete"],
        partial=counts["partial"],
        not_entered=counts["not_entered"],
    )


def print_result(path: Path, result: ValidationResult) -> None:
    if result.valid:
        print(f"VALID: {path.as_posix()}")
        print(f"events: {result.events}")
        print(f"complete: {result.complete}")
        print(f"partial: {result.partial}")
        print(f"not_entered: {result.not_entered}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")
    else:
        print(f"INVALID: {path.as_posix()}")
        for error in result.errors:
            print(error)


def main() -> int:
    root = project_root()
    path = root / "data" / "calendar" / "events.json"
    display_path = Path("data/calendar/events.json")
    try:
        payload = read_json(path)
    except ValueError as exc:
        print(f"INVALID: {display_path.as_posix()}")
        print(str(exc))
        return 1
    result = validate_events_payload(payload)
    print_result(display_path, result)
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
