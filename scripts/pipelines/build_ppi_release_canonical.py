from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.common import preview
from scripts.pipelines import capture_ppi_release as capture


class PpiLiveCanonicalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code; super().__init__(message)


def validate_release(payload: dict[str, Any], event_id: str) -> None:
    if payload.get("integrity", {}).get("sha256") != preview.stable_json_sha256(payload): raise PpiLiveCanonicalError("PPI_RELEASE_INTEGRITY_ERROR","release SHA invalid")
    if payload.get("event_id") != event_id or payload.get("indicator_type") != "PPI" or payload.get("country") != "US": raise PpiLiveCanonicalError("PPI_RELEASE_EVENT_MISMATCH","release identity invalid")
    if event_id != f"US_PPI_{str(payload.get('reference_period')).replace('-', '_')}": raise PpiLiveCanonicalError("PPI_RELEASE_REFERENCE_PERIOD_MISMATCH","reference mismatch")
    release=capture.parse_utc(payload.get("release_datetime_utc"),"release_datetime_utc"); captured=capture.parse_utc(payload.get("captured_at_utc"),"captured_at_utc")
    if not release <= captured <= release + capture.timedelta(hours=24): raise PpiLiveCanonicalError("PPI_RELEASE_PROVENANCE_INVALID","capture window invalid")
    provenance=payload.get("provenance",{})
    if provenance.get("data_origin")!="live_release_capture" or provenance.get("vintage_status")!="as_released_capture" or provenance.get("not_as_released") is not False or provenance.get("immutable") is not True: raise PpiLiveCanonicalError("PPI_RELEASE_PROVENANCE_INVALID","provenance invalid")
    metrics=payload.get("metrics")
    if not isinstance(metrics,dict) or set(metrics)!=set(capture.METRICS): raise PpiLiveCanonicalError("PPI_RELEASE_PARTIAL_METRICS","four metrics required")
    for name in capture.METRICS:
        if metrics[name].get("series_id") != capture.bls_ppi.SOURCE_SERIES[name]: raise PpiLiveCanonicalError("PPI_RELEASE_PARTIAL_METRICS","series invalid")


def build_canonical(release: dict[str, Any], event_id: str) -> dict[str, Any]:
    validate_release(release,event_id); metrics={}
    for name,value in release["metrics"].items(): metrics[name]={"actual_raw":value["actual_raw"],"actual_display":value["actual_display"],"expected_raw":None,"expected_display":None,"previous_raw":None,"previous_display":None,"surprise_raw":None,"surprise_display":None,"source_series_id":value["series_id"],"seasonal_adjustment":value["seasonal_adjustment"],"calculation":value["calculation"]}
    result={"schema_version":"1.0","event":{"event_id":event_id,"reference_period":release["reference_period"]},"indicator":{"type":"PPI","country":"US"},"release":{"release_datetime_utc":release["release_datetime_utc"],"captured_at_utc":release["captured_at_utc"]},"meta":{"event_id":event_id,"indicator_type":"PPI","indicator_name":"US Producer Price Index","country":"US","reference_period":release["reference_period"],"release_datetime_utc":release["release_datetime_utc"],"release_datetime_kst":release["release_datetime_utc"],"retrieved_at_utc":release["captured_at_utc"],"data_origin":"live_release_capture","vintage_status":"as_released_capture","not_as_released":False,"is_sample":False},"source":{"provider":"BLS","release_sha256":release["integrity"]["sha256"]},"metrics":metrics,"consensus":{"status":"not_locked"},"provenance":release["provenance"],"integrity":{"sha256":None}}
    result["integrity"]["sha256"]=preview.stable_json_sha256(result); return result


def build_file(release_path: Path, output_path: Path, event_id: str) -> str:
    if not release_path.is_file(): raise PpiLiveCanonicalError("PPI_RELEASE_NOT_FOUND","release not found")
    try: release=json.loads(release_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise PpiLiveCanonicalError("PPI_RELEASE_INTEGRITY_ERROR","release unreadable") from exc
    result=build_canonical(release,event_id); data=preview.json_bytes(result)
    if output_path.exists():
        if output_path.read_bytes()==data:return "PPI_CANONICAL_ALREADY_EXISTS"
        raise PpiLiveCanonicalError("PPI_CANONICAL_CONFLICT","canonical differs")
    preview.write_immutable_bytes(output_path,data); return "PPI_CANONICAL_CREATED"
