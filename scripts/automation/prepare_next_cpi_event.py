from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.validators import validate_calendar_events  # noqa: E402


EVENT_RE = re.compile(r"US_CPI_(\d{4})_(0[1-9]|1[0-2])\Z")
METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")


class CandidateError(Exception):
    def __init__(self, code: str, message: str): self.code, self.message = code, message; super().__init__(message)


@dataclass(frozen=True)
class CandidateResult:
    status: str; event_id: str; reference_period: str; release_datetime_kst: str; candidate_created: bool; sha256: str | None
    def payload(self):
        value = asdict(self); value["schema_version"] = "1.0"; return value


def stable_sha256(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload); value.get("integrity", {}).pop("sha256", None)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value: raise CandidateError("CPI_EVENT_INVALID", f"{field} is required")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise CandidateError("CPI_EVENT_INVALID", f"{field} is invalid") from exc
    if parsed.tzinfo is None: raise CandidateError("CPI_EVENT_INVALID", f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str: return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
def iso_kst(value: datetime) -> str: return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise CandidateError("CPI_EVENT_INVALID", "calendar is invalid") from exc
    if not isinstance(value, dict): raise CandidateError("CPI_EVENT_INVALID", "calendar must be an object")
    return value


def next_month(period: str) -> str:
    year, month = map(int, period.split("-")); return f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"


def source_name(value: str) -> str:
    if not value or not value.strip() or "://" in value or re.search(r"token|key|password|secret", value, re.I): raise CandidateError("CPI_EVENT_INVALID", "schedule source is invalid")
    return value.strip()


def candidate_payload(event_id: str, period: str, release: datetime, source: str, checked: datetime) -> dict[str, Any]:
    value: dict[str, Any] = {"schema_version": "1.0", "candidate_status": "pending_human_approval", "event": {"event_id": event_id, "indicator_type": "CPI", "country": "US", "reference_period": period, "release_datetime_utc": iso_utc(release), "release_datetime_kst": iso_kst(release), "consensus_status": "not_entered", "consensus_source": None, "entered_at_utc": None, "metrics": {key: {"expected": None, "unit": "%"} for key in METRICS}}, "schedule_source": {"name": source, "checked_at_utc": iso_utc(checked)}, "integrity": {"immutable_candidate": True, "sha256": None}}
    value["integrity"]["sha256"] = stable_sha256(value); return value


def prepare(root: Path, *, event_id: str, reference_period: str, release_datetime_utc: str, source: str, source_checked_at_utc: str, output: Path, now: datetime | None = None) -> CandidateResult:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc); root = root.resolve()
    match = EVENT_RE.fullmatch(event_id)
    if not match or reference_period != f"{match.group(1)}-{match.group(2)}": raise CandidateError("CPI_EVENT_INVALID", "event_id and reference_period must match")
    release, checked = parse_utc(release_datetime_utc, "release_datetime_utc"), parse_utc(source_checked_at_utc, "source_checked_at_utc")
    if release <= now or checked > now or checked >= release: raise CandidateError("CPI_EVENT_INVALID", "schedule times are invalid")
    calendar = read_json(root / "data/calendar/events.json")
    if not validate_calendar_events.validate_events_payload(calendar, now=now).valid: raise CandidateError("CPI_EVENT_INVALID", "calendar validation failed")
    events = [e for e in calendar.get("events", []) if isinstance(e, dict) and e.get("indicator_type") == "CPI" and e.get("country") == "US"]
    if any(e.get("event_id") == event_id for e in events): raise CandidateError("CPI_EVENT_DUPLICATE", "event_id already exists")
    if any(e.get("reference_period") == reference_period for e in events): raise CandidateError("CPI_EVENT_DUPLICATE", "reference_period already exists")
    latest = max(str(e.get("reference_period")) for e in events)
    expected = next_month(latest)
    if reference_period != expected: raise CandidateError("CPI_EVENT_SEQUENCE_GAP" if reference_period > expected else "CPI_EVENT_SEQUENCE_INVALID", "candidate must be the next CPI reference period")
    payload = candidate_payload(event_id, reference_period, release, source_name(source), checked)
    if output.exists():
        if output.is_symlink(): raise CandidateError("CPI_EVENT_INVALID", "candidate output symlink is forbidden")
        existing = read_json(output)
        if existing == payload: return CandidateResult("CPI_EVENT_CANDIDATE_ALREADY_EXISTS", event_id, reference_period, iso_kst(release), False, payload["integrity"]["sha256"])
        raise CandidateError("CPI_EVENT_CANDIDATE_CONFLICT", "candidate output differs")
    output.parent.mkdir(parents=True, exist_ok=True); temp = output.parent / f".{output.name}.{uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.link(temp, output)
    finally:
        if temp.exists(): temp.unlink()
    return CandidateResult("CPI_EVENT_CANDIDATE_CREATED", event_id, reference_period, iso_kst(release), True, payload["integrity"]["sha256"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--event-id", required=True); parser.add_argument("--reference-period", required=True); parser.add_argument("--release-datetime-utc", required=True); parser.add_argument("--source", required=True); parser.add_argument("--source-checked-at-utc", required=True); parser.add_argument("--output", required=True); args = parser.parse_args(argv)
    try: result = prepare(PROJECT_ROOT, event_id=args.event_id, reference_period=args.reference_period, release_datetime_utc=args.release_datetime_utc, source=args.source, source_checked_at_utc=args.source_checked_at_utc, output=Path(args.output))
    except CandidateError as exc: print(exc.code); return 1
    print(result.status); return 0


if __name__ == "__main__": raise SystemExit(main())
