from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
REFERENCE_PERIOD_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
HARD_LINK_UNSUPPORTED_ERRNOS = {errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP}
HARD_LINK_UNSUPPORTED_WINERRORS = {1, 50}


class PpiEventCandidateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CandidateResult:
    status: str
    event_id: str | None
    reference_period: str | None
    release_datetime_utc: str | None
    release_datetime_kst: str | None
    source_url: str | None
    created_paths: tuple[str, ...]
    approval_status: str | None
    calendar_modified: bool
    external_api_called: bool
    external_ai_api_called: bool
    cost: str
    sha256: str | None

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_paths"] = list(self.created_paths)
        return value


def stable_sha256(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload)
    value.get("integrity", {}).pop("sha256", None)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def read_calendar(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "calendar is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "calendar events are invalid")
    return value


def validated_source_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "source_url is required")
    source_url = value.strip()
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "source_url must be http or https")
    return source_url


def candidate_payload(
    event_id: str,
    reference_period: str,
    release: datetime,
    source_url: str,
    checked_at: datetime,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event_id,
        "indicator_type": "PPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": iso_utc(release),
        "release_datetime_kst": iso_kst(release),
        "schedule_source": {
            "url": source_url,
            "checked_at_utc": iso_utc(checked_at),
        },
        "approval": {
            "status": "candidate",
            "approved_by": None,
            "approved_at_utc": None,
        },
        "consensus_status": "not_entered",
        "consensus_source": None,
        "entered_at_utc": None,
        "metrics": {name: {"expected": None} for name in PPI_METRICS},
        "provenance": {
            "data_origin": "manual_official_schedule_entry",
            "official_schedule_verified": True,
        },
        "integrity": {"sha256": None},
    }
    payload["integrity"]["sha256"] = stable_sha256(payload)
    return payload


def result(
    status: str,
    *,
    event_id: str | None = None,
    reference_period: str | None = None,
    release: datetime | None = None,
    source_url: str | None = None,
    created_paths: tuple[str, ...] = (),
    sha256: str | None = None,
) -> CandidateResult:
    return CandidateResult(
        status=status,
        event_id=event_id,
        reference_period=reference_period,
        release_datetime_utc=iso_utc(release) if release else None,
        release_datetime_kst=iso_kst(release) if release else None,
        source_url=source_url,
        created_paths=created_paths,
        approval_status="candidate" if event_id else None,
        calendar_modified=False,
        external_api_called=False,
        external_ai_api_called=False,
        cost="free",
        sha256=sha256,
    )


def output_path(output_root: Path, event_id: str) -> Path:
    if output_root.exists() and output_root.is_symlink():
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "candidate output root symlink is forbidden")
    return output_root / f"{event_id}.json"


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def hard_link_unsupported(error: OSError) -> bool:
    return error.errno in HARD_LINK_UNSUPPORTED_ERRNOS or getattr(error, "winerror", None) in HARD_LINK_UNSUPPORTED_WINERRORS


def registered_ppi_conflict(calendar: dict[str, Any], event_id: str, reference_period: str, release: datetime) -> bool:
    release_utc = iso_utc(release)
    for event in calendar["events"]:
        if not isinstance(event, dict) or event.get("indicator_type") != "PPI":
            continue
        if event.get("event_id") == event_id or event.get("reference_period") == reference_period:
            return True
        try:
            if iso_utc(parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")) == release_utc:
                return True
        except PpiEventCandidateError:
            continue
    return False


def prepare(
    root: Path,
    *,
    event_id: str | None,
    reference_period: str,
    release_datetime_utc: str,
    source_url: str,
    source_checked_at_utc: str,
    output_root: Path,
    now: datetime | None = None,
) -> CandidateResult:
    root = root.resolve()
    if not isinstance(reference_period, str) or not REFERENCE_PERIOD_RE.fullmatch(reference_period):
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "reference_period must be YYYY-MM")
    expected_event_id = f"US_PPI_{reference_period.replace('-', '_')}"
    event_id = event_id or expected_event_id
    match = EVENT_RE.fullmatch(event_id)
    if match is None or event_id != expected_event_id:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "event_id and reference_period must match")

    release = parse_utc(release_datetime_utc, "release_datetime_utc")
    checked_at = parse_utc(source_checked_at_utc, "source_checked_at_utc")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if release <= now_utc or checked_at > now_utc or checked_at >= release:
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "schedule times are invalid")
    source_url = validated_source_url(source_url)

    calendar = read_calendar(root / "data" / "calendar" / "events.json")
    if registered_ppi_conflict(calendar, event_id, reference_period, release):
        return result(
            "PPI_EVENT_ALREADY_REGISTERED",
            event_id=event_id,
            reference_period=reference_period,
            release=release,
            source_url=source_url,
        )

    payload = candidate_payload(event_id, reference_period, release, source_url, checked_at)
    candidate_path = output_path(output_root, event_id)
    if candidate_path.exists():
        if candidate_path.is_symlink():
            raise PpiEventCandidateError("PPI_EVENT_INVALID", "candidate output symlink is forbidden")
        try:
            existing = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            existing = None
        status = "PPI_EVENT_CANDIDATE_ALREADY_EXISTS" if existing == payload else "PPI_EVENT_CANDIDATE_CONFLICT"
        return result(status, event_id=event_id, reference_period=reference_period, release=release, source_url=source_url, sha256=payload["integrity"]["sha256"])

    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    if candidate_path.parent.is_symlink():
        raise PpiEventCandidateError("PPI_EVENT_INVALID", "candidate output root symlink is forbidden")
    temporary = candidate_path.parent / f".{candidate_path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.link(temporary, candidate_path)
        except FileExistsError:
            existing = json.loads(candidate_path.read_text(encoding="utf-8"))
            status = "PPI_EVENT_CANDIDATE_ALREADY_EXISTS" if existing == payload else "PPI_EVENT_CANDIDATE_CONFLICT"
            return result(status, event_id=event_id, reference_period=reference_period, release=release, source_url=source_url, sha256=payload["integrity"]["sha256"])
        except OSError as exc:
            if not hard_link_unsupported(exc):
                raise
            try:
                with candidate_path.open("xb") as handle:
                    handle.write(temporary.read_bytes())
            except FileExistsError:
                existing = json.loads(candidate_path.read_text(encoding="utf-8"))
                status = "PPI_EVENT_CANDIDATE_ALREADY_EXISTS" if existing == payload else "PPI_EVENT_CANDIDATE_CONFLICT"
                return result(status, event_id=event_id, reference_period=reference_period, release=release, source_url=source_url, sha256=payload["integrity"]["sha256"])
    finally:
        if temporary.exists():
            temporary.unlink()

    return result(
        "PPI_EVENT_CANDIDATE_CREATED",
        event_id=event_id,
        reference_period=reference_period,
        release=release,
        source_url=source_url,
        created_paths=(relative_path(root, candidate_path),),
        sha256=payload["integrity"]["sha256"],
    )


def input_required_result() -> CandidateResult:
    return result("PPI_EVENT_INPUT_REQUIRED")


def write_result(path: Path, value: CandidateResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value.payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a PPI event candidate from manually verified official schedule inputs.")
    parser.add_argument("--event-id")
    parser.add_argument("--reference-period")
    parser.add_argument("--release-datetime-utc")
    parser.add_argument("--source-url")
    parser.add_argument("--source-checked-at-utc")
    parser.add_argument("--output-root")
    parser.add_argument("--result-json")
    parser.add_argument("--now-utc")
    args = parser.parse_args(argv)

    required = (
        args.reference_period,
        args.release_datetime_utc,
        args.source_url,
        args.source_checked_at_utc,
        args.output_root,
    )
    try:
        value = input_required_result() if not all(required) else prepare(
            PROJECT_ROOT,
            event_id=args.event_id,
            reference_period=args.reference_period,
            release_datetime_utc=args.release_datetime_utc,
            source_url=args.source_url,
            source_checked_at_utc=args.source_checked_at_utc,
            output_root=Path(args.output_root),
            now=parse_utc(args.now_utc, "now_utc") if args.now_utc else None,
        )
    except PpiEventCandidateError as exc:
        print(exc.code)
        return 1

    if args.result_json:
        write_result(Path(args.result_json), value)
    print(value.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
