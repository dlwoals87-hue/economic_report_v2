"""Read-only diagnostic wrapper for the PPI consensus collector."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.collectors import ppi_consensus  # noqa: E402

METRICS=("headline_mom","headline_yoy","core_mom","core_yoy")
def stable_sha(value:dict[str,Any])->str: return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def parse_now(value:str|None)->datetime:
 if not value:return datetime.now(timezone.utc)
 parsed=datetime.fromisoformat(value.replace("Z","+00"));
 if parsed.tzinfo is None: raise ValueError("now_utc timezone required")
 return parsed.astimezone(timezone.utc)
def probe(event_id:str,*,events_path:Path|None=None,now_utc:datetime|None=None,collector:Callable[...,dict[str,Any]]=ppi_consensus.collect)->dict[str,Any]:
 result=collector(event_id,root=ROOT,events_path=events_path or ROOT/"data/calendar/events.json",now_utc=now_utc or datetime.now(timezone.utc))
 status=result.get("status"); normalized=result.get("normalized") or {}; metrics=normalized.get("metrics",result.get("metrics",{})) if isinstance(normalized,dict) else {}
 available=[m for m in METRICS if m in metrics]; missing=[m for m in METRICS if m not in metrics]
 mapping={"PPI_CONSENSUS_COLLECTED":"PPI_CONSENSUS_PROVIDER_PROBE_COMPLETE","PPI_CONSENSUS_PARTIAL":"PPI_CONSENSUS_PROVIDER_PROBE_PARTIAL","PPI_CONSENSUS_UNAVAILABLE":"PPI_CONSENSUS_PROVIDER_PROBE_UNAVAILABLE"}; output_status=mapping.get(status,status)
 safe=output_status=="PPI_CONSENSUS_PROVIDER_PROBE_COMPLETE"
 action="ENABLE_PPI_CONSENSUS_AUTOMATION" if safe else "REVIEW_PROVIDER_METRIC_COVERAGE" if output_status.endswith("PARTIAL") else "REVIEW_PROVIDER_MAPPING_OR_PLAN" if output_status.endswith("UNAVAILABLE") else "CONFIGURE_TRADING_ECONOMICS_API_KEY" if status=="CONSENSUS_PROVIDER_KEY_MISSING" else "REVIEW_PROVIDER_ERROR"
 output={"schema_version":"1.0","status":output_status,"event_id":event_id,"provider":"trading_economics","provider_data_type":"market_consensus","reference_period":result.get("reference_period"),"release_datetime_utc":result.get("release_datetime_utc"),"retrieved_at_utc":normalized.get("retrieved_at_utc") if isinstance(normalized,dict) else result.get("retrieved_at_utc"),"normalized_status":result.get("normalized_status"),"metrics_available":available,"missing_metrics":missing,"provider_event_ids":result.get("provider_event_ids",{}),"provider_tickers":result.get("provider_tickers",{}),"source_fields":result.get("source_fields",{}),"raw_payload_sha256":result.get("raw_payload_sha256"),"external_api_called":bool(result.get("external_api_called",False)),"external_ai_api_called":False,"cost":"free","safe_to_enable_automation":safe,"next_action":action,"integrity":{"sha256":None}}
 output["integrity"]["sha256"]=stable_sha({**output,"integrity":{}}); return output
def main(argv=None)->int:
 p=argparse.ArgumentParser(description="Probe PPI provider capability without applying data"); p.add_argument("--event-id",required=True); p.add_argument("--events"); p.add_argument("--now-utc"); p.add_argument("--result-json",required=True); a=p.parse_args(argv)
 try:r=probe(a.event_id,events_path=Path(a.events) if a.events else None,now_utc=parse_now(a.now_utc))
 except ValueError: return 2
 ppi_consensus.write_result(Path(a.result_json),ROOT,r); print(r["status"]); return 0
if __name__=="__main__":raise SystemExit(main())
