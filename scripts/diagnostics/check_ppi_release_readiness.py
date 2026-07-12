from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from scripts.automation import lock_ppi_consensus as lock  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402

PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")

@dataclass(frozen=True)
class ReadinessResult:
    status: str; event_id: str; reference_period: str | None; release_datetime_utc: str | None; release_datetime_kst: str | None; time_state: str | None; capture_readiness: str; consensus_readiness: str; processing_readiness: str; notification_readiness: str; blocking_errors: tuple[str, ...]; warnings: tuple[str, ...]; checks: dict[str, bool]; expected_values_entered: bool; consensus_snapshot_exists: bool; consensus_snapshot_integrity: str; external_api_called: bool = False; external_ai_api_called: bool = False; cost: str = "free"; next_actions: tuple[str, ...] = ()
    def payload(self):
        value=asdict(self); value["blocking_errors"]=list(self.blocking_errors); value["warnings"]=list(self.warnings); value["next_actions"]=list(self.next_actions); return value

def parse_utc(value: Any) -> datetime: return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def snapshot_for_test(event: dict[str, Any]) -> dict[str, Any]:
    release=parse_utc(event["release_datetime_utc"]); values={k:str(event["metrics"][k]["expected"]) for k in PPI_METRICS}; return lock.build_snapshot(event,release,values,"0"*64,parse_utc(event["entered_at_utc"]))
def static_contract(root: Path, _: dict[str, Any]) -> list[str]:
    errors=[]
    for path in ("scripts/collectors/bls_ppi.py","scripts/pipelines/capture_ppi_release.py","scripts/automation/run_due_ppi_capture.py","scripts/automation/run_pending_ppi_processing.py","scripts/automation/build_ppi_notification.py"):
        if not (root/path).is_file(): errors.append(f"missing {path}")
    checks={".github/workflows/capture-ppi-release.yml":("workflow_dispatch","schedule:","run_due_ppi_capture.py"),".github/workflows/process-ppi-release.yml":("workflow_run:","Capture PPI Release","run_pending_ppi_processing.py"),".github/workflows/notify-ppi-processing.yml":("workflow_run:","Process PPI Release","issues: write")}
    for name,needed in checks.items():
        path=root/name
        if not path.is_file() or any(token not in path.read_text(encoding="utf-8") for token in needed): errors.append(f"workflow contract {name}")
    notify=root/".github/workflows/notify-ppi-processing.yml"
    if notify.is_file() and "contents: write" in notify.read_text(encoding="utf-8"): errors.append("notification contents write")
    return errors
def event_contract(root: Path,event_id: str) -> tuple[dict[str,Any],datetime,list[str]]:
    payload=json.loads((root/"data/calendar/events.json").read_text(encoding="utf-8")); validation=validate_calendar_events.validate_events_payload(payload)
    errors=[] if validation.valid else ["calendar invalid"]
    matches=[e for e in payload.get("events",[]) if isinstance(e,dict) and e.get("event_id")==event_id]
    if len(matches)!=1: return {},datetime.now(timezone.utc),errors+["event missing or duplicate"]
    event=matches[0]; match=EVENT_RE.fullmatch(event_id)
    if not match or event.get("indicator_type")!="PPI" or event.get("country")!="US" or event.get("reference_period")!=f"{match.group(1)}-{match.group(2)}": errors.append("PPI event identity invalid")
    try: release=parse_utc(event.get("release_datetime_utc"))
    except Exception: release=datetime.now(timezone.utc); errors.append("release time invalid")
    if not isinstance(event.get("schedule_source"),dict) or not event["schedule_source"].get("url") or not isinstance(event.get("approval"),dict) or event["approval"].get("status")!="approved": errors.append("schedule or approval metadata invalid")
    if not isinstance(event.get("metrics"),dict) or set(event["metrics"])!=set(PPI_METRICS): errors.append("PPI metrics invalid")
    return event,release,errors
def check_readiness(root: Path,event_id: str,*,now_utc: datetime|None=None,static_checks: Callable[[Path,dict[str,Any]],list[str]]=static_contract)->ReadinessResult:
    now=(now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc); event,release,errors=event_contract(root,event_id); errors+=static_checks(root,event) if event else []
    time_state="BEFORE_RELEASE" if now<release else "CAPTURE_WINDOW_OPEN" if now<=release+timedelta(hours=24) else "CAPTURE_WINDOW_EXPIRED"
    warnings=[]; snapshot=root/"data/consensus/ppi"/event_id/"consensus_snapshot.json"; exists=snapshot.is_file(); integrity="missing"; expected=False; consensus="CONSENSUS_INVALID"
    if event:
        metrics=event.get("metrics",{}); expected=all(isinstance(metrics.get(k),dict) and metrics[k].get("expected") is not None for k in PPI_METRICS)
        status=event.get("consensus_status")
        if status=="not_entered" and not expected and not exists: consensus="CONSENSUS_NOT_READY"; warnings.append("Market expected values are not entered; surprise calculation is unavailable.")
        elif status=="complete" and expected and not exists: consensus="CONSENSUS_COMPLETE_UNLOCKED"; warnings.append("Immutable PPI consensus lock is still required before release.")
        elif exists:
            try:
                data=json.loads(snapshot.read_text(encoding="utf-8")); integrity="valid" if lock.valid_snapshot(data) else "invalid"
                if integrity=="valid" and data.get("event_id")==event_id and data.get("reference_period")==event.get("reference_period"): consensus="CONSENSUS_LOCKED"
                else: errors.append("consensus snapshot integrity or calendar mismatch")
            except Exception: integrity="invalid"; errors.append("consensus snapshot integrity or calendar mismatch")
        else: errors.append("consensus state invalid")
    if time_state=="CAPTURE_WINDOW_EXPIRED" and not (root/"data/releases/ppi"/event_id/"as_released.json").exists(): errors.append("capture window expired without as_released data")
    status="READINESS_FAIL" if errors else "READINESS_PASS"; checks={"capture":not any("capture" in e or "collector" in e or "workflow contract .github/workflows/capture" in e for e in errors),"processing":not any("process" in e for e in errors),"notification":not any("notification" in e for e in errors)}
    next_actions=("Verify the consensus provider API configuration.","Run the automated PPI consensus collector.","Normalize all expected values from one provider response.","Validate complete consensus, create the immutable snapshot, then rerun readiness.") if consensus=="CONSENSUS_NOT_READY" else ()
    return ReadinessResult(status,event_id,event.get("reference_period") if event else None,release.isoformat().replace("+00:00","Z") if event else None,release.astimezone(ZoneInfo("Asia/Seoul")).isoformat() if event else None,time_state,"READY" if checks["capture"] else "NOT_READY",consensus,"READY" if checks["processing"] else "NOT_READY","READY" if checks["notification"] else "NOT_READY",tuple(errors),tuple(warnings),checks,expected,exists,integrity,next_actions=next_actions)
def main(argv=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--event-id"); parser.add_argument("--project-root"); parser.add_argument("--result-json"); args=parser.parse_args(argv)
    if not args.event_id: print("PPI_READINESS_INPUT_REQUIRED"); return 0
    root=Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT; result=check_readiness(root,args.event_id)
    if args.result_json: Path(args.result_json).write_text(json.dumps(result.payload(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(result.status); return 0 if result.status=="READINESS_PASS" else 1
if __name__=="__main__": raise SystemExit(main())
