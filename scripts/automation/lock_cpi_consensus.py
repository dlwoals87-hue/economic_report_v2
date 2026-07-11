from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")


class ConsensusLockError(Exception):
    """Raised when supplied consensus data cannot be locked safely."""


@dataclass(frozen=True)
class LockResult:
    status: str
    event_id: str
    snapshot_path: str
    snapshot_created: bool


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConsensusLockError(f"file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsensusLockError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ConsensusLockError(f"JSON root must be an object: {path}")
    return payload


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_sha256(payload: dict[str, Any]) -> str:
    normalized = copy.deepcopy(payload)
    integrity = normalized.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("sha256", None)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ConsensusLockError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsensusLockError(f"{field} is not ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ConsensusLockError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise ConsensusLockError("event_id is invalid")
    events = calendar.get("events")
    if not isinstance(events, list):
        raise ConsensusLockError("calendar events must be a list")
    matches = [event for event in events if isinstance(event, dict) and event.get("event_id") == event_id]
    if len(matches) != 1:
        raise ConsensusLockError("calendar event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise ConsensusLockError("calendar event must be US CPI")
    if not isinstance(event.get("reference_period"), str) or not event["reference_period"]:
        raise ConsensusLockError("calendar reference_period is required")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    return event


def parse_expected(value: Any, metric: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ConsensusLockError(f"expected {metric} is not Decimal")
    if isinstance(value, (int, float, Decimal)):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or "%" in value:
        raise ConsensusLockError(f"expected {metric} is not Decimal")
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ConsensusLockError(f"expected {metric} is not Decimal") from exc
    if not parsed.is_finite():
        raise ConsensusLockError(f"expected {metric} is not Decimal")
    return parsed


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def snapshot_path(root: Path, event_id: str) -> Path:
    return root / "data" / "consensus" / "cpi" / event_id / "consensus_snapshot.json"


def relative_snapshot_path(event_id: str) -> str:
    return f"data/consensus/cpi/{event_id}/consensus_snapshot.json"


def snapshot_inputs(event: dict[str, Any], now_utc: datetime) -> tuple[str, dict[str, Decimal] | None]:
    metrics = event.get("metrics")
    if not isinstance(metrics, dict) or any(metric not in metrics for metric in CPI_METRICS):
        raise ConsensusLockError("calendar CPI metrics are incomplete")
    values: dict[str, Any] = {}
    for metric in CPI_METRICS:
        entry = metrics[metric]
        if not isinstance(entry, dict):
            raise ConsensusLockError(f"calendar metric {metric} is invalid")
        values[metric] = entry.get("expected")
    if all(value is None for value in values.values()):
        return "CONSENSUS_NOT_READY", None
    if any(value is None for value in values.values()):
        return "CONSENSUS_PARTIAL", None
    release_utc = parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    if now_utc >= release_utc:
        return "CONSENSUS_LOCK_WINDOW_EXPIRED", None
    if event.get("consensus_status") != "complete":
        raise ConsensusLockError("consensus_status must be complete")
    source = event.get("consensus_source")
    if not isinstance(source, str) or not source.strip():
        raise ConsensusLockError("consensus_source is required")
    entered_at = parse_utc(event.get("entered_at_utc"), "entered_at_utc")
    if entered_at > now_utc:
        raise ConsensusLockError("entered_at_utc must not be in the future")
    if entered_at >= release_utc:
        raise ConsensusLockError("entered_at_utc must be before release_datetime_utc")
    return "READY", {metric: parse_expected(values[metric], metric) for metric in CPI_METRICS}


def build_snapshot(event: dict[str, Any], values: dict[str, Decimal], locked_at_utc: datetime) -> dict[str, Any]:
    release_utc = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    entered_at = parse_utc(event["entered_at_utc"], "entered_at_utc")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event["event_id"],
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": event["reference_period"],
        "release_datetime_utc": iso_utc(release_utc),
        "release_datetime_kst": iso_kst(release_utc),
        "consensus_source": event["consensus_source"].strip(),
        "entered_at_utc": iso_utc(entered_at),
        "locked_at_utc": iso_utc(locked_at_utc),
        "lock_status": "locked_before_release",
        "metrics": {
            metric: {
                "expected_raw": decimal_text(values[metric]),
                "expected_display": f"{values[metric].quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%",
            }
            for metric in CPI_METRICS
        },
        "integrity": {"immutable": True, "sha256": None},
    }
    payload["integrity"]["sha256"] = stable_sha256(payload)
    return payload


def validate_snapshot(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "1.0":
        raise ConsensusLockError("consensus snapshot schema_version is invalid")
    if EVENT_ID_RE.fullmatch(str(payload.get("event_id", ""))) is None:
        raise ConsensusLockError("consensus snapshot event_id is invalid")
    if payload.get("indicator_type") != "CPI" or payload.get("country") != "US":
        raise ConsensusLockError("consensus snapshot must be US CPI")
    if not isinstance(payload.get("reference_period"), str) or not payload["reference_period"]:
        raise ConsensusLockError("consensus snapshot reference_period is invalid")
    parse_utc(payload.get("release_datetime_utc"), "snapshot release_datetime_utc")
    parse_utc(payload.get("entered_at_utc"), "snapshot entered_at_utc")
    parse_utc(payload.get("locked_at_utc"), "snapshot locked_at_utc")
    if payload.get("lock_status") != "locked_before_release":
        raise ConsensusLockError("consensus snapshot lock_status is invalid")
    if not isinstance(payload.get("consensus_source"), str) or not payload["consensus_source"].strip():
        raise ConsensusLockError("consensus snapshot consensus_source is invalid")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(CPI_METRICS):
        raise ConsensusLockError("consensus snapshot metrics are invalid")
    for metric in CPI_METRICS:
        item = metrics[metric]
        if not isinstance(item, dict):
            raise ConsensusLockError(f"consensus snapshot metric {metric} is invalid")
        expected = parse_expected(item.get("expected_raw"), metric)
        if item.get("expected_display") != f"{expected.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%":
            raise ConsensusLockError(f"consensus snapshot metric {metric} display is invalid")
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("immutable") is not True:
        raise ConsensusLockError("consensus snapshot must be immutable")
    if integrity.get("sha256") != stable_sha256(payload):
        raise ConsensusLockError("consensus snapshot SHA-256 mismatch")


def snapshot_matches_event(snapshot: dict[str, Any], event: dict[str, Any], values: dict[str, Decimal]) -> bool:
    return (
        snapshot.get("event_id") == event.get("event_id")
        and snapshot.get("reference_period") == event.get("reference_period")
        and snapshot.get("release_datetime_utc") == iso_utc(parse_utc(event.get("release_datetime_utc"), "release_datetime_utc"))
        and snapshot.get("consensus_source") == event.get("consensus_source", "").strip()
        and snapshot.get("entered_at_utc") == iso_utc(parse_utc(event.get("entered_at_utc"), "entered_at_utc"))
        and all(snapshot["metrics"][metric]["expected_raw"] == decimal_text(values[metric]) for metric in CPI_METRICS)
    )


def write_snapshot_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        try:
            os.link(temp_path, path)
        except FileExistsError:
            raise
        except OSError as exc:
            raise ConsensusLockError("could not exclusively create consensus snapshot") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


def lock_consensus(root: Path, event_id: str, now_utc: datetime | None = None) -> LockResult:
    root = root.resolve()
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event = find_event(read_json(root / "data" / "calendar" / "events.json"), event_id)
    path = snapshot_path(root, event_id)
    relative_path = relative_snapshot_path(event_id)
    status, values = snapshot_inputs(event, now)
    if status != "READY":
        return LockResult(status, event_id, relative_path, False)
    assert values is not None
    if path.exists():
        existing = read_json(path)
        validate_snapshot(existing)
        status = "CONSENSUS_ALREADY_LOCKED" if snapshot_matches_event(existing, event, values) else "CONSENSUS_LOCK_CONFLICT"
        return LockResult(status, event_id, relative_path, False)
    snapshot = build_snapshot(event, values, now)
    try:
        write_snapshot_exclusive(path, snapshot)
    except FileExistsError:
        existing = read_json(path)
        validate_snapshot(existing)
        status = "CONSENSUS_ALREADY_LOCKED" if snapshot_matches_event(existing, event, values) else "CONSENSUS_LOCK_CONFLICT"
        return LockResult(status, event_id, relative_path, False)
    return LockResult("CONSENSUS_LOCKED", event_id, relative_path, True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lock CPI consensus before its release time")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--now-utc", help="timezone-aware ISO 8601 test time")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        now = parse_utc(args.now_utc, "--now-utc") if args.now_utc else None
        result = lock_consensus(project_root(), args.event_id, now)
    except ConsensusLockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"snapshot_path: {result.snapshot_path}")
    print(f"snapshot_created: {str(result.snapshot_created).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
