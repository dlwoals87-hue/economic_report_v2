from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.automation import prepare_next_ppi_event as prepare
from scripts.validators import validate_calendar_events


EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")


class PpiApprovalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ApprovalResult:
    status: str
    event_id: str | None
    reference_period: str | None
    release_datetime_utc: str | None
    approved_by: str | None
    approved_at_utc: str | None
    candidate_sha256: str | None
    calendar_modified: bool
    created_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    external_api_called: bool
    external_ai_api_called: bool
    cost: str

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_paths"] = list(self.created_paths)
        value["modified_paths"] = list(self.modified_paths)
        return value


def parse_utc(value: Any, field: str) -> datetime:
    try:
        return prepare.parse_utc(value, field)
    except prepare.PpiEventCandidateError as exc:
        raise PpiApprovalError("PPI_EVENT_APPROVAL_FIELDS_INVALID", str(exc)) from exc


def read_candidate(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_NOT_FOUND", "candidate file is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate JSON is invalid") from exc
    if not isinstance(value, dict):
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate must be an object")
    integrity = value.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("sha256") != prepare.stable_sha256(value):
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INTEGRITY_ERROR", "candidate SHA-256 is invalid")
    return value


def validate_candidate(candidate: dict[str, Any]) -> tuple[dict[str, Any], datetime, datetime, str]:
    if candidate.get("schema_version") != "1.0":
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate schema is invalid")
    if candidate.get("indicator_type") != "PPI" or candidate.get("country") != "US":
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate identity is invalid")
    event_id = candidate.get("event_id")
    reference_period = candidate.get("reference_period")
    match = EVENT_RE.fullmatch(str(event_id))
    if match is None or reference_period != f"{match.group(1)}-{match.group(2)}":
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "event_id and reference_period must match")

    try:
        release = prepare.parse_utc(candidate.get("release_datetime_utc"), "release_datetime_utc")
        checked_at = prepare.parse_utc(candidate.get("schedule_source", {}).get("checked_at_utc"), "source_checked_at_utc")
        source_url = prepare.validated_source_url(candidate.get("schedule_source", {}).get("url"))
    except (prepare.PpiEventCandidateError, AttributeError) as exc:
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate schedule is invalid") from exc
    if candidate.get("release_datetime_kst") != prepare.iso_kst(release) or checked_at >= release:
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate schedule times are invalid")

    approval = candidate.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "candidate" or approval.get("approved_by") is not None or approval.get("approved_at_utc") is not None:
        raise PpiApprovalError("PPI_EVENT_APPROVAL_FIELDS_INVALID", "candidate is not pending approval")
    if candidate.get("consensus_status") != "not_entered" or candidate.get("consensus_source") is not None or candidate.get("entered_at_utc") is not None:
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate consensus is invalid")

    metrics = candidate.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(prepare.PPI_METRICS):
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate PPI metrics are invalid")
    for metric in metrics.values():
        if not isinstance(metric, dict) or metric.get("expected") is not None or any(key in metric for key in ("actual", "previous", "surprise")):
            raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate metrics must contain null expected values only")

    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("data_origin") != "manual_official_schedule_entry" or provenance.get("official_schedule_verified") is not True:
        raise PpiApprovalError("PPI_EVENT_CANDIDATE_INVALID", "candidate provenance is invalid")
    return candidate, release, checked_at, source_url


def validate_approval_fields(
    approved_by: Any,
    approved_at_utc: Any,
    confirm_event_id: Any,
    event_id: str,
    checked_at: datetime,
    now: datetime,
) -> datetime:
    if confirm_event_id != event_id:
        raise PpiApprovalError("PPI_EVENT_CONFIRMATION_MISMATCH", "confirm_event_id must exactly match the candidate")
    if not isinstance(approved_by, str) or not approved_by or len(approved_by) > 120:
        raise PpiApprovalError("PPI_EVENT_APPROVAL_FIELDS_INVALID", "approved_by is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in approved_by) or any(char in approved_by for char in "<>&;|`$\\"):
        raise PpiApprovalError("PPI_EVENT_APPROVAL_FIELDS_INVALID", "approved_by contains unsafe characters")
    approved_at = parse_utc(approved_at_utc, "approved_at_utc")
    if approved_at < checked_at or approved_at > now:
        raise PpiApprovalError("PPI_EVENT_APPROVAL_FIELDS_INVALID", "approved_at_utc is outside the approval window")
    return approved_at


def event_from_candidate(candidate: dict[str, Any], approved_by: str, approved_at: datetime) -> dict[str, Any]:
    return {
        "event_id": candidate["event_id"],
        "indicator_type": "PPI",
        "country": "US",
        "reference_period": candidate["reference_period"],
        "release_datetime_utc": candidate["release_datetime_utc"],
        "metrics": {name: {"expected": None, "unit": "%"} for name in prepare.PPI_METRICS},
        "consensus_status": "not_entered",
        "consensus_source": None,
        "entered_at_utc": None,
        "schedule_source": candidate["schedule_source"],
        "approval": {
            "status": "approved",
            "approved_by": approved_by,
            "approved_at_utc": prepare.iso_utc(approved_at),
        },
        "source_candidate_sha256": candidate["integrity"]["sha256"],
    }


def read_calendar(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiApprovalError("PPI_EVENT_CALENDAR_INVALID", "calendar JSON is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise PpiApprovalError("PPI_EVENT_CALENDAR_INVALID", "calendar events are invalid")
    return value


def display_path(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 3 and parts[-3:] == ("data", "calendar", "events.json"):
        return "data/calendar/events.json"
    return str(path)


def result(
    status: str,
    candidate: dict[str, Any] | None = None,
    *,
    approved_by: str | None = None,
    approved_at: datetime | None = None,
    calendar_modified: bool = False,
    modified_paths: tuple[str, ...] = (),
) -> ApprovalResult:
    return ApprovalResult(
        status=status,
        event_id=candidate.get("event_id") if candidate else None,
        reference_period=candidate.get("reference_period") if candidate else None,
        release_datetime_utc=candidate.get("release_datetime_utc") if candidate else None,
        approved_by=approved_by,
        approved_at_utc=prepare.iso_utc(approved_at) if approved_at else None,
        candidate_sha256=candidate.get("integrity", {}).get("sha256") if candidate else None,
        calendar_modified=calendar_modified,
        created_paths=(),
        modified_paths=modified_paths,
        external_api_called=False,
        external_ai_api_called=False,
        cost="free",
    )


def approve(
    candidate_path: Path,
    events_path: Path,
    *,
    approved_by: str,
    approved_at_utc: str,
    confirm_event_id: str | None,
    now: datetime | None = None,
) -> ApprovalResult:
    candidate, release, checked_at, _ = validate_candidate(read_candidate(candidate_path))
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approved_at = validate_approval_fields(approved_by, approved_at_utc, confirm_event_id, candidate["event_id"], checked_at, now_utc)
    calendar = read_calendar(events_path)
    events = calendar["events"]
    candidate_sha = candidate["integrity"]["sha256"]

    for existing in events:
        if not isinstance(existing, dict):
            continue
        if existing.get("event_id") == candidate["event_id"]:
            if existing.get("indicator_type") == "PPI" and existing.get("source_candidate_sha256") == candidate_sha:
                return result("PPI_EVENT_ALREADY_APPROVED", candidate, approved_by=approved_by, approved_at=approved_at)
            return result("PPI_EVENT_APPROVAL_CONFLICT", candidate, approved_by=approved_by, approved_at=approved_at)
        if existing.get("indicator_type") != "PPI":
            continue
        if existing.get("reference_period") == candidate["reference_period"]:
            return result("PPI_EVENT_ALREADY_REGISTERED", candidate, approved_by=approved_by, approved_at=approved_at)
        try:
            if prepare.iso_utc(prepare.parse_utc(existing.get("release_datetime_utc"), "release_datetime_utc")) == prepare.iso_utc(release):
                return result("PPI_EVENT_ALREADY_REGISTERED", candidate, approved_by=approved_by, approved_at=approved_at)
        except prepare.PpiEventCandidateError:
            continue

    merged = dict(calendar)
    merged["events"] = [*events, event_from_candidate(candidate, approved_by, approved_at)]
    if not validate_calendar_events.validate_events_payload(merged, now=now_utc).valid:
        raise PpiApprovalError("PPI_EVENT_CALENDAR_INVALID", "merged calendar fails validation")

    temporary = events_path.with_name(f".{events_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verified = read_calendar(temporary)
        if not validate_calendar_events.validate_events_payload(verified, now=now_utc).valid:
            raise PpiApprovalError("PPI_EVENT_CALENDAR_INVALID", "temporary calendar fails validation")
        os.replace(temporary, events_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return result(
        "PPI_EVENT_APPROVED",
        candidate,
        approved_by=approved_by,
        approved_at=approved_at,
        calendar_modified=True,
        modified_paths=(display_path(events_path),),
    )


def input_required_result() -> ApprovalResult:
    return result("PPI_EVENT_APPROVAL_INPUT_REQUIRED")


def write_result(path: Path, value: ApprovalResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value.payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Approve a manually verified PPI event candidate.")
    parser.add_argument("--candidate")
    parser.add_argument("--events")
    parser.add_argument("--approved-by")
    parser.add_argument("--approved-at-utc")
    parser.add_argument("--confirm-event-id")
    parser.add_argument("--result-json")
    args = parser.parse_args(argv)

    required = (args.candidate, args.events, args.approved_by, args.approved_at_utc, args.confirm_event_id)
    try:
        value = input_required_result() if not all(required) else approve(
            Path(args.candidate),
            Path(args.events),
            approved_by=args.approved_by,
            approved_at_utc=args.approved_at_utc,
            confirm_event_id=args.confirm_event_id,
        )
    except PpiApprovalError as exc:
        print(exc.code)
        return 1

    if args.result_json:
        write_result(Path(args.result_json), value)
    print(value.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
