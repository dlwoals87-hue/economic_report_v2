from __future__ import annotations

import argparse
import copy
import errno
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
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from scripts.validators import validate_calendar_events  # noqa: E402

PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
UNSUPPORTED_ERRNOS = {errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP}
UNSUPPORTED_WINERRORS = {1, 50}

class PpiConsensusLockError(Exception): pass

@dataclass(frozen=True)
class LockResult:
    status: str; event_id: str | None; reference_period: str | None; release_datetime_utc: str | None; release_datetime_kst: str | None; snapshot_path: str | None; snapshot_created: bool; snapshot_sha256: str | None; source_calendar_sha256: str | None; consensus_source: str | None; entered_at_utc: str | None; metrics: dict[str, dict[str, str]]; created_paths: tuple[str, ...]; external_api_called: bool = False; external_ai_api_called: bool = False; cost: str = "free"; next_action: str = "5.3F-2B"
    def payload(self):
        value = asdict(self); value["created_paths"] = list(self.created_paths); value["schema_version"] = "1.0"; return value

def sha256_bytes(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def stable_sha256(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload); value.get("integrity", {}).pop("sha256", None); return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
def parse_utc(value: Any, field: str) -> datetime:
    try: parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc: raise PpiConsensusLockError(f"{field} is invalid") from exc
    if parsed.tzinfo is None: raise PpiConsensusLockError(f"{field} requires timezone")
    return parsed.astimezone(timezone.utc)
def iso_utc(value: datetime) -> str: return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
def iso_kst(value: datetime) -> str: return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()
def decimal_text(value: Decimal) -> str:
    text = format(value, "f"); return text.rstrip("0").rstrip(".") if "." in text else text
def parse_expected(value: Any, metric: str) -> str:
    if not isinstance(value, str) or not value or "%" in value: raise PpiConsensusLockError(f"expected {metric} is invalid")
    try: parsed = Decimal(value)
    except InvalidOperation as exc: raise PpiConsensusLockError(f"expected {metric} is invalid") from exc
    if not parsed.is_finite(): raise PpiConsensusLockError(f"expected {metric} is invalid")
    return decimal_text(parsed)
def unsupported(error: OSError) -> bool: return error.errno in UNSUPPORTED_ERRNOS or getattr(error, "winerror", None) in UNSUPPORTED_WINERRORS
def relative(root: Path, path: Path) -> str: return path.relative_to(root).as_posix()
def safe_path(path: Path, root: Path, *, allow_temp: bool = False) -> bool:
    if ".." in path.parts: return False
    try: resolved = path.resolve(strict=False)
    except OSError: return False
    bases = (root.resolve(), Path(tempfile.gettempdir()).resolve()) if allow_temp else (root.resolve(),)
    return any(resolved.is_relative_to(base) for base in bases) and not any(item.is_symlink() for item in (path, *path.parents) if item.exists())

def read_calendar(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise PpiConsensusLockError("calendar JSON is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("events"), list): raise PpiConsensusLockError("calendar events are invalid")
    return value
def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    match = EVENT_RE.fullmatch(event_id)
    if not match: raise PpiConsensusLockError("event_id is invalid")
    matches = [e for e in calendar["events"] if isinstance(e, dict) and e.get("event_id") == event_id]
    if len(matches) != 1: raise PpiConsensusLockError("event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US" or event.get("reference_period") != f"{match.group(1)}-{match.group(2)}": raise PpiConsensusLockError("target event must be US PPI")
    return event
def output_path(root: Path, output_root: Path, event_id: str) -> Path:
    if not safe_path(output_root, root): raise PpiConsensusLockError("output root is unsafe")
    return output_root / event_id / "consensus_snapshot.json"
def validate_event(calendar: dict[str, Any], event_id: str, now: datetime) -> tuple[dict[str, Any], datetime, dict[str, str]]:
    if not validate_calendar_events.validate_events_payload(calendar, now=now).valid: raise PpiConsensusLockError("calendar validation failed")
    event = find_event(calendar, event_id); release = parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    if now >= release: raise PpiConsensusLockError("window expired")
    if event.get("consensus_status") != "complete" or not isinstance(event.get("consensus_source"), str) or not event["consensus_source"].strip() or not event.get("entered_at_utc"): raise PpiConsensusLockError("not ready")
    entered = parse_utc(event["entered_at_utc"], "entered_at_utc")
    if entered >= release: raise PpiConsensusLockError("not ready")
    metrics = event.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(PPI_METRICS): raise PpiConsensusLockError("not ready")
    return event, release, {name: parse_expected(metrics[name].get("expected") if isinstance(metrics[name], dict) else None, name) for name in PPI_METRICS}
def build_snapshot(event: dict[str, Any], release: datetime, values: dict[str, str], calendar_sha: str, locked_at: datetime) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version":"1.0","event_id":event["event_id"],"indicator_type":"PPI","country":"US","reference_period":event["reference_period"],"release_datetime_utc":iso_utc(release),"release_datetime_kst":iso_kst(release),"consensus_status":"complete","consensus_source":event["consensus_source"].strip(),"entered_at_utc":event["entered_at_utc"],"source_observed_at_utc":event.get("source_observed_at_utc"),"snapshot_created_at_utc":iso_utc(locked_at),"source_calendar_sha256":calendar_sha,"metrics":{name:{"expected_raw":values[name]} for name in PPI_METRICS},"integrity":{"immutable":True,"sha256":None}}
    payload["integrity"]["sha256"] = stable_sha256(payload); return payload
def valid_snapshot(value: dict[str, Any]) -> bool:
    return isinstance(value, dict) and value.get("integrity", {}).get("immutable") is True and value.get("integrity", {}).get("sha256") == stable_sha256(value)
def result(status: str, event: dict[str, Any] | None = None, release: datetime | None = None, *, path: Path | None = None, created: bool = False, snapshot: dict[str, Any] | None = None, calendar_sha: str | None = None) -> LockResult:
    return LockResult(status, event.get("event_id") if event else None, event.get("reference_period") if event else None, iso_utc(release) if release else None, iso_kst(release) if release else None, path.as_posix() if path else None, created, snapshot.get("integrity", {}).get("sha256") if snapshot else None, calendar_sha, event.get("consensus_source") if event else None, event.get("entered_at_utc") if event else None, snapshot.get("metrics", {}) if snapshot else {}, (path.as_posix(),) if created and path else ())
def lock_consensus(root: Path, *, event_id: str, events_path: Path, output_root: Path, locked_at_utc: str, now_utc: datetime | None = None) -> LockResult:
    root = root.resolve(); now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc); locked_at = parse_utc(locked_at_utc, "locked_at_utc")
    if locked_at > now: raise PpiConsensusLockError("locked_at_utc must not be future")
    original = events_path.read_bytes(); calendar = read_calendar(events_path)
    try: event, release, values = validate_event(calendar, event_id, now)
    except PpiConsensusLockError as exc:
        if str(exc) == "not ready": return result("PPI_CONSENSUS_NOT_READY_TO_LOCK")
        if str(exc) == "window expired": return result("PPI_CONSENSUS_LOCK_WINDOW_EXPIRED")
        raise
    if locked_at >= release: raise PpiConsensusLockError("locked_at_utc must be before release")
    path = output_path(root, output_root, event_id); snapshot = build_snapshot(event, release, values, sha256_bytes(original), locked_at)
    if path.exists():
        try: existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return result("PPI_CONSENSUS_SNAPSHOT_INTEGRITY_ERROR", event, release, path=path)
        if not valid_snapshot(existing): return result("PPI_CONSENSUS_SNAPSHOT_INTEGRITY_ERROR", event, release, path=path)
        return result("PPI_CONSENSUS_SNAPSHOT_ALREADY_EXISTS" if existing == snapshot else "PPI_CONSENSUS_SNAPSHOT_CONFLICT", event, release, path=path, snapshot=existing, calendar_sha=sha256_bytes(original))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink(): raise PpiConsensusLockError("output root is unsafe")
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        try: os.link(temp, path)
        except FileExistsError: return lock_consensus(root, event_id=event_id, events_path=events_path, output_root=output_root, locked_at_utc=locked_at_utc, now_utc=now)
        except OSError as exc:
            if not unsupported(exc): raise
            with path.open("xb") as handle: handle.write(temp.read_bytes())
    finally:
        if temp.exists(): temp.unlink()
    return result("PPI_CONSENSUS_SNAPSHOT_CREATED", event, release, path=path, created=True, snapshot=snapshot, calendar_sha=sha256_bytes(original))
def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--event-id"); parser.add_argument("--events"); parser.add_argument("--output-root"); parser.add_argument("--locked-at-utc"); parser.add_argument("--result-json"); args=parser.parse_args(argv)
    if not any((args.event_id,args.events,args.output_root,args.locked_at_utc)): print("PPI_CONSENSUS_LOCK_INPUT_REQUIRED"); return 0
    if not all((args.event_id,args.events,args.output_root,args.locked_at_utc)): print("PPI_CONSENSUS_LOCK_INPUT_REQUIRED"); return 1
    try: value=lock_consensus(PROJECT_ROOT,event_id=args.event_id,events_path=Path(args.events),output_root=Path(args.output_root),locked_at_utc=args.locked_at_utc)
    except PpiConsensusLockError as exc: print(f"ERROR: {exc}",file=sys.stderr); return 1
    if args.result_json:
        result_path = Path(args.result_json)
        if not safe_path(result_path, PROJECT_ROOT, allow_temp=True): print("ERROR: result-json path is unsafe", file=sys.stderr); return 1
        result_path.write_text(json.dumps(value.payload(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(value.status); return 0
if __name__ == "__main__": raise SystemExit(main())
