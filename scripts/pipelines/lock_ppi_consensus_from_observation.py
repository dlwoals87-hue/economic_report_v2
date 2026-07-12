"""Lock the existing PPI snapshot schema from a validated observation."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))
from scripts.automation import lock_ppi_consensus as lock  # noqa: E402
from scripts.collectors import ppi_consensus  # noqa: E402
from scripts.pipelines import apply_ppi_consensus_observation as apply  # noqa: E402

PPI_METRICS=("headline_mom","headline_yoy","core_mom","core_yoy")

def base(status:str,event_id:str,*,lock_requested:bool,event:dict[str,Any]|None=None)->dict[str,Any]:
    return {"status":status,"event_id":event_id,"provider":"trading_economics","reference_period":event.get("reference_period") if event else None,"release_datetime_utc":event.get("release_datetime_utc") if event else None,"retrieved_at_utc":None,"selected_observation_path":None,"selected_observation_sha256":None,"expected":{},"expected_matches_observation":False,"snapshot_path":None,"snapshot_created":False,"snapshot_sha256":None,"lock_requested":lock_requested,"external_api_called":False,"external_ai_api_called":False,"cost":"free","next_action":"CAPTURE_AND_APPLY_COMPLETE_CONSENSUS"}

def safe_snapshot_root(root:Path,path:Path)->bool:
    try: resolved=path.resolve(strict=False)
    except OSError: return False
    return ".." not in path.parts and resolved==(root/"data"/"consensus"/"ppi").resolve(strict=False) and not any(x.is_symlink() for x in (path,*path.parents) if x.exists())

def run(event_id:str,*,root:Path=PROJECT_ROOT,events_path:Path|None=None,observations_root:Path|None=None,snapshot_root:Path|None=None,now_utc:datetime|None=None,lock_requested:bool=False)->dict[str,Any]:
    root=root.resolve(); events=events_path or root/"data"/"calendar"/"events.json"; observations=observations_root or root/"data"/"consensus"/"ppi"; snapshots=snapshot_root or root/"data"/"consensus"/"ppi"
    try:
        calendar, original=apply.read_calendar(root,events); event=apply.event_for(calendar,event_id); now=now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None: raise apply.ApplyError("PPI_CONSENSUS_AUTO_LOCK_INPUT_INVALID")
        now=now.astimezone(timezone.utc)
    except apply.ApplyError as exc: return base(str(exc),event_id,lock_requested=lock_requested)
    result=base("",event_id,lock_requested=lock_requested,event=event)
    if now>=apply.parse_utc(event["release_datetime_utc"]): result["status"]="PPI_CONSENSUS_AUTO_LOCK_WINDOW_EXPIRED"; return result
    if not safe_snapshot_root(root,snapshots): result["status"]="PPI_CONSENSUS_AUTO_LOCK_INPUT_INVALID"; return result
    expected={m:event["metrics"][m].get("expected") for m in PPI_METRICS}
    result["expected"]=expected
    if any(value is None for value in expected.values()): result["status"]="PPI_CONSENSUS_EXPECTED_NOT_READY"; return result
    status, observation, path, _=apply.select_observation(root,observations,event)
    if status!="OK": result["status"]=status; return result
    values={m:lock.parse_expected(observation["metrics"][m]["expected"],m) for m in PPI_METRICS}
    if any(lock.parse_expected(expected[m],m)!=values[m] for m in PPI_METRICS): result["status"]="PPI_CONSENSUS_EXPECTED_OBSERVATION_MISMATCH"; return result
    relative=path.resolve().relative_to(root).as_posix(); provenance={"provider":"trading_economics","provider_data_type":"market_consensus","selected_observation_path":relative,"selected_observation_sha256":observation["integrity"]["sha256"],"raw_payload_sha256":observation["raw_payload_sha256"],"normalized_sha256":observation["normalized_sha256"],"retrieved_at_utc":observation["retrieved_at_utc"],"data_origin":"live_consensus_capture","observation_type":"pre_release_market_consensus","observed_before_release":True,"immutable":True}
    result.update({"retrieved_at_utc":observation["retrieved_at_utc"],"selected_observation_path":relative,"selected_observation_sha256":observation["integrity"]["sha256"],"expected_matches_observation":True,"snapshot_path":(snapshots/event_id/"consensus_snapshot.json").resolve().relative_to(root).as_posix()})
    if not lock_requested: result["status"]="PPI_CONSENSUS_AUTO_LOCK_PREVIEW_READY"; result["next_action"]="RUN_AUTO_LOCK"; return result
    try: locked=lock.lock_consensus(root,event_id=event_id,events_path=events,output_root=snapshots,locked_at_utc=apply.iso_utc(now),now_utc=now,observation_provenance=provenance)
    except lock.PpiConsensusLockError: result["status"]="PPI_CONSENSUS_AUTO_LOCK_INPUT_INVALID"; return result
    result.update({"snapshot_created":locked.snapshot_created,"snapshot_sha256":locked.snapshot_sha256})
    mapping={"PPI_CONSENSUS_SNAPSHOT_CREATED":"PPI_CONSENSUS_SNAPSHOT_LOCKED","PPI_CONSENSUS_SNAPSHOT_ALREADY_EXISTS":"PPI_CONSENSUS_SNAPSHOT_ALREADY_LOCKED","PPI_CONSENSUS_SNAPSHOT_CONFLICT":"PPI_CONSENSUS_SNAPSHOT_CONFLICT"}
    result["status"]=mapping.get(locked.status,locked.status); result["next_action"]="PPI_CONSENSUS_AUTOMATION_READY" if result["status"] in {"PPI_CONSENSUS_SNAPSHOT_LOCKED","PPI_CONSENSUS_SNAPSHOT_ALREADY_LOCKED"} else "CAPTURE_AND_APPLY_COMPLETE_CONSENSUS"; return result

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Preview or lock PPI consensus from a complete observation"); parser.add_argument("--event-id",required=True); parser.add_argument("--events"); parser.add_argument("--observations-root",required=True); parser.add_argument("--snapshot-root",required=True); parser.add_argument("--now-utc"); parser.add_argument("--result-json"); parser.add_argument("--lock",action="store_true"); args=parser.parse_args(argv)
    now=apply.parse_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc); result=run(args.event_id,events_path=Path(args.events) if args.events else None,observations_root=Path(args.observations_root),snapshot_root=Path(args.snapshot_root),now_utc=now,lock_requested=args.lock)
    if args.result_json: ppi_consensus.write_result(Path(args.result_json),PROJECT_ROOT,result)
    print(result["status"]); return 0 if result["status"] in {"PPI_CONSENSUS_AUTO_LOCK_PREVIEW_READY","PPI_CONSENSUS_SNAPSHOT_LOCKED","PPI_CONSENSUS_SNAPSHOT_ALREADY_LOCKED","PPI_CONSENSUS_EXPECTED_NOT_READY","PPI_CONSENSUS_NO_ELIGIBLE_OBSERVATION","PPI_CONSENSUS_AUTO_LOCK_WINDOW_EXPIRED"} else 1
if __name__=="__main__": raise SystemExit(main())
