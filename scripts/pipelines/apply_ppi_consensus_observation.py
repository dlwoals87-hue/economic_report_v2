"""Select the newest valid complete PPI observation and safely apply it."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collectors import ppi_consensus  # noqa: E402
from scripts.pipelines import capture_ppi_consensus_observation as capture  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402

PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
FORBIDDEN_KEYS = {"actual", "previous", "teforecast", "teforecastvalue", "raw_payload", "api_key", "secret", "token"}


class ApplyError(Exception): pass

def parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID") from exc
    if parsed.tzinfo is None: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    return parsed.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str: return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
def stable_json(value: dict[str, Any]) -> bytes: return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
def sha_payload(value: dict[str, Any]) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

def read_calendar(root: Path, path: Path) -> tuple[dict[str, Any], bytes]:
    expected = (root / "data" / "calendar" / "events.json").resolve(strict=False)
    if ".." in path.parts or path.resolve(strict=False) != expected or not path.is_file() or path.is_symlink(): raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    raw = path.read_bytes()
    try: data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID") from exc
    return data, raw

def event_for(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    match = EVENT_RE.fullmatch(event_id)
    matches = [item for item in calendar.get("events", []) if isinstance(item, dict) and item.get("event_id") == event_id]
    if not match or len(matches) != 1: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US" or event.get("reference_period") != f"{match.group(1)}-{match.group(2)}": raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    if not isinstance(event.get("metrics"), dict) or set(event["metrics"]) != set(PPI_METRICS): raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    parse_utc(event.get("release_datetime_utc")); return event

def safe_observation_root(root: Path, path: Path) -> bool:
    try: resolved = path.resolve(strict=False)
    except OSError: return False
    return ".." not in path.parts and resolved == (root / "data" / "consensus" / "ppi").resolve(strict=False) and not any(item.is_symlink() for item in (path, *path.parents) if item.exists())

def forbidden_key(value: Any) -> bool:
    if isinstance(value, dict): return any(str(key).lower() in FORBIDDEN_KEYS or forbidden_key(item) for key, item in value.items())
    if isinstance(value, list): return any(forbidden_key(item) for item in value)
    return False

def validate_observation(value: dict[str, Any], event: dict[str, Any], path: Path) -> tuple[datetime, str] | None:
    if forbidden_key(value) or value.get("event_id") != event["event_id"] or value.get("provider") != "trading_economics" or value.get("provider_data_type") != "market_consensus": return None
    provenance = value.get("provenance", {})
    if provenance != {"data_origin":"live_consensus_capture", "observation_type":"pre_release_market_consensus", "provider":"trading_economics", "observed_before_release":True, "not_actual_release_data":True}: return None
    if value.get("immutable") is not True or value.get("normalized_status") != "complete" or value.get("eligible_for_apply") is not True: return None
    if value.get("reference_period") != event["reference_period"] or value.get("release_datetime_utc") != event["release_datetime_utc"]: return None
    try: retrieved = parse_utc(value.get("retrieved_at_utc")); release = parse_utc(event["release_datetime_utc"])
    except ApplyError: return None
    if retrieved >= release or path.stem != retrieved.strftime("%Y%m%dT%H%M%SZ"): return None
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(PPI_METRICS) or value.get("missing_metrics") != []: return None
    if not all(isinstance(metrics[m], dict) and isinstance(metrics[m].get("expected"), str) for m in PPI_METRICS): return None
    if not all(isinstance(value.get(key), str) and SHA_RE.fullmatch(value[key]) for key in ("raw_payload_sha256", "normalized_sha256")): return None
    if value.get("integrity", {}).get("sha256") != capture._observation_sha(value): return None
    return retrieved, value["integrity"]["sha256"]

def select_observation(root: Path, observations_root: Path, event: dict[str, Any]) -> tuple[str, dict[str, Any] | None, Path | None, list[str]]:
    if not safe_observation_root(root, observations_root): return "PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID", None, None, ["unsafe observations root"]
    directory = observations_root / event["event_id"] / "provider_observations"
    if not directory.exists(): return "PPI_CONSENSUS_NO_ELIGIBLE_OBSERVATION", None, None, []
    if directory.is_symlink(): return "PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID", None, None, ["symlink observations directory"]
    candidates: list[tuple[datetime, str, dict[str, Any], Path]] = []; rejected: list[str] = []
    for path in directory.glob("*.json"):
        if path.is_symlink(): return "PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID", None, None, ["symlink observation"]
        try: value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError): return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR", None, None, [path.name]
        if not isinstance(value, dict): return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR", None, None, [path.name]
        checked = validate_observation(value, event, path)
        if checked is None:
            if value.get("normalized_status") in {"partial", "unavailable"}: rejected.append(path.name); continue
            return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR", None, None, [path.name]
        candidates.append((checked[0], checked[1], value, path))
    if not candidates: return "PPI_CONSENSUS_NO_ELIGIBLE_OBSERVATION", None, None, rejected
    latest = max(item[0] for item in candidates); latest_items = [item for item in candidates if item[0] == latest]
    if len({item[1] for item in latest_items}) > 1: return "PPI_CONSENSUS_OBSERVATION_SELECTION_CONFLICT", None, None, [item[3].name for item in latest_items]
    selected = latest_items[0]; return "OK", selected[2], selected[3], rejected

def base(status: str, event_id: str, *, apply: bool, event: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status":status,"event_id":event_id,"selected_observation_path":None,"selected_observation_sha256":None,"provider":"trading_economics","reference_period":event.get("reference_period") if event else None,"release_datetime_utc":event.get("release_datetime_utc") if event else None,"retrieved_at_utc":None,"expected_before":{},"expected_after":{},"changed_metrics":[],"calendar_changed":False,"apply_requested":apply,"selected_observation_count":0,"rejected_observation_count":0,"rejection_reasons":[],"external_api_called":False,"external_ai_api_called":False,"cost":"free","next_action":"CAPTURE_COMPLETE_CONSENSUS_OBSERVATION"}

def atomic_write(path: Path, content: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle: handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()

def run(event_id: str, *, root: Path = PROJECT_ROOT, events_path: Path | None = None, observations_root: Path | None = None, now_utc: datetime | None = None, apply: bool = False) -> dict[str, Any]:
    root=root.resolve(); events=events_path or root/"data"/"calendar"/"events.json"; observations=observations_root or root/"data"/"consensus"/"ppi"
    try:
        calendar, original = read_calendar(root, events); event=event_for(calendar,event_id); now=now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
        now=now.astimezone(timezone.utc); validation=validate_calendar_events.validate_events_payload(calendar,now=now)
        if not validation.valid: raise ApplyError("PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
    except ApplyError as exc: return base(str(exc),event_id,apply=apply)
    result=base("",event_id,apply=apply,event=event)
    if now >= parse_utc(event["release_datetime_utc"]): result["status"]="PPI_CONSENSUS_AUTO_APPLY_WINDOW_EXPIRED"; return result
    status, observation, path, rejected=select_observation(root,observations,event); result["rejected_observation_count"]=len(rejected); result["rejection_reasons"]=rejected
    if status != "OK": result["status"]=status; return result
    expected={m:observation["metrics"][m]["expected"] for m in PPI_METRICS}; before={m:event["metrics"][m].get("expected") for m in PPI_METRICS}
    result.update({"selected_observation_path":path.resolve().relative_to(root).as_posix(),"selected_observation_sha256":observation["integrity"]["sha256"],"retrieved_at_utc":observation["retrieved_at_utc"],"expected_before":before,"expected_after":expected,"selected_observation_count":1})
    if all(value == expected[key] for key,value in before.items()): result["status"]="PPI_CONSENSUS_EXPECTED_ALREADY_APPLIED"; result["next_action"]="5.3G-2B-2_LOCK_CONSENSUS_SNAPSHOT"; return result
    if any(value is not None for value in before.values()): result["status"]="PPI_CONSENSUS_EXPECTED_CONFLICT"; result["next_action"]="RESOLVE_EXPECTED_CONFLICT"; return result
    result["changed_metrics"]=list(PPI_METRICS)
    if not apply: result["status"]="PPI_CONSENSUS_AUTO_APPLY_PREVIEW_READY"; result["next_action"]="RUN_AUTO_APPLY"; return result
    updated=copy.deepcopy(calendar); target=event_for(updated,event_id)
    for metric in PPI_METRICS: target["metrics"][metric]["expected"]=expected[metric]
    target["consensus_status"]="complete"; target["consensus_source"]="trading_economics"; target["entered_at_utc"]=observation["retrieved_at_utc"]
    if not validate_calendar_events.validate_events_payload(updated,now=now).valid: result["status"]="PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID"; return result
    try: atomic_write(events,stable_json(updated))
    except OSError: result["status"]="PPI_CONSENSUS_AUTO_APPLY_WRITE_ERROR"; return result
    result["status"]="PPI_CONSENSUS_EXPECTED_APPLIED"; result["calendar_changed"]=True; result["next_action"]="5.3G-2B-2_LOCK_CONSENSUS_SNAPSHOT"; return result

def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Preview or apply the latest complete PPI consensus observation")
    parser.add_argument("--event-id",required=True); parser.add_argument("--events"); parser.add_argument("--observations-root",required=True); parser.add_argument("--now-utc"); parser.add_argument("--result-json"); parser.add_argument("--apply",action="store_true")
    args=parser.parse_args(argv); now=parse_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    result=run(args.event_id,events_path=Path(args.events) if args.events else None,observations_root=Path(args.observations_root),now_utc=now,apply=args.apply)
    if args.result_json: ppi_consensus.write_result(Path(args.result_json),PROJECT_ROOT,result)
    print(result["status"]); return 0 if result["status"] in {"PPI_CONSENSUS_AUTO_APPLY_PREVIEW_READY","PPI_CONSENSUS_EXPECTED_APPLIED","PPI_CONSENSUS_EXPECTED_ALREADY_APPLIED","PPI_CONSENSUS_NO_ELIGIBLE_OBSERVATION","PPI_CONSENSUS_AUTO_APPLY_WINDOW_EXPIRED"} else 1

if __name__ == "__main__": raise SystemExit(main())
