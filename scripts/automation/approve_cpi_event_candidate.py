from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.automation import prepare_next_cpi_event as prepare
from scripts.validators import validate_calendar_events


@dataclass(frozen=True)
class ApprovalResult:
    status: str; event_id: str | None; file_modified: bool; before_sha256: str | None; after_sha256: str | None


def sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def read_candidate(path: Path) -> dict[str, Any]:
    if path.is_symlink() or ".." in path.parts: raise prepare.CandidateError("CPI_EVENT_CANDIDATE_INTEGRITY_ERROR", "candidate path is unsafe")
    value = prepare.read_json(path)
    if value.get("candidate_status") != "pending_human_approval" or value.get("integrity", {}).get("immutable_candidate") is not True or value.get("integrity", {}).get("sha256") != prepare.stable_sha256(value): raise prepare.CandidateError("CPI_EVENT_CANDIDATE_INTEGRITY_ERROR", "candidate integrity is invalid")
    event = value.get("event")
    if not isinstance(event, dict): raise prepare.CandidateError("CPI_EVENT_CANDIDATE_INTEGRITY_ERROR", "candidate event is invalid")
    return value


def approve(root: Path, candidate_path: Path, *, mode: str, now: datetime | None = None) -> ApprovalResult:
    if mode not in {"preview", "apply"}: raise prepare.CandidateError("CPI_EVENT_INVALID", "mode is required")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc); candidate = read_candidate(candidate_path); event = candidate["event"]
    calendar_path = root / "data/calendar/events.json"; before = calendar_path.read_bytes(); calendar = json.loads(before.decode("utf-8")); events = calendar.get("events", [])
    same_id = [item for item in events if isinstance(item, dict) and item.get("event_id") == event.get("event_id")]
    if same_id:
        if same_id[0] == event: return ApprovalResult("CPI_EVENT_ALREADY_REGISTERED", event.get("event_id"), False, sha(before), sha(before))
        raise prepare.CandidateError("CPI_EVENT_REGISTRATION_CONFLICT", "event_id conflicts")
    if any(isinstance(item, dict) and item.get("reference_period") == event.get("reference_period") for item in events): raise prepare.CandidateError("CPI_REFERENCE_PERIOD_CONFLICT", "reference period conflicts")
    merged = dict(calendar); merged["events"] = [*events, event]
    if not validate_calendar_events.validate_events_payload(merged, now=now).valid: raise prepare.CandidateError("CPI_EVENT_CALENDAR_VALIDATION_FAILED", "merged calendar is invalid")
    if mode == "preview": return ApprovalResult("CPI_EVENT_APPROVAL_PREVIEW", event.get("event_id"), False, sha(before), sha(before))
    temporary = calendar_path.with_name(f".{calendar_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(temporary, calendar_path)
    finally:
        if temporary.exists(): temporary.unlink()
    return ApprovalResult("CPI_EVENT_APPROVED", event.get("event_id"), True, sha(before), sha(calendar_path.read_bytes()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--candidate", required=True); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--preview", action="store_true"); mode.add_argument("--apply", action="store_true"); args = parser.parse_args(argv)
    try: result = approve(Path.cwd(), Path(args.candidate), mode="apply" if args.apply else "preview")
    except prepare.CandidateError as exc: print(exc.code); return 1
    print(result.status); return 0


if __name__ == "__main__": raise SystemExit(main())
