"""Offline-only BLS CPI component parser using the approved series registry."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from scripts.collectors import bls_cpi


class ComponentError(ValueError):
    def __init__(self, code: str, message: str): self.code, self.message = code, message; super().__init__(message)


def _plain(value: Decimal) -> str:
    text = format(value, "f"); return text.rstrip("0").rstrip(".") if "." in text else text
def _display(value: Decimal) -> str: return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%"
def _sha(payload: dict[str, Any]) -> str:
    value=copy.deepcopy(payload); value.get("integrity",{}).pop("sha256",None); return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def _fixture_id(value: str) -> None:
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.-]+",value) or ".." in value or "\\" in value: raise ComponentError("INVALID_INPUT","fixture id is unsafe")
def parse_component_fixture_bytes(raw: bytes, registry: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    try: payload=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ComponentError("INVALID_INPUT","fixture JSON is invalid") from exc
    if not isinstance(payload,dict) or any("key" in str(key).lower() or "secret" in str(key).lower() or "token" in str(key).lower() for key in payload): raise ComponentError("INVALID_INPUT","fixture credentials are forbidden")
    return parse_component_response(payload,registry)


def requested_series(registry: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({component[field] for component in registry["components"] if component["mapping_status"] == "APPROVED" for field in ("mom_series_id", "yoy_series_id")}))


def validate_component_hierarchy(registry: dict[str, Any]) -> None:
    components=registry.get("components")
    if not isinstance(components,list) or not components: raise ComponentError("COMPONENT_MAPPING_INVALID","components required")
    ids=set(); series=set()
    for component in components:
        required={"component_id","display_name_ko","display_name_en","parent_component","child_components","mutually_exclusive","aggregation_allowed","display_group","double_count_risk","mom_series_id","yoy_series_id","mom_seasonal_adjustment","yoy_seasonal_adjustment","calculation_formula","source_version","mapping_version","mapping_status","official_reference"}
        if not isinstance(component,dict) or set(component)!=required: raise ComponentError("COMPONENT_MAPPING_INVALID","component fields invalid")
        if component["component_id"] in ids: raise ComponentError("COMPONENT_MAPPING_INVALID","duplicate component")
        ids.add(component["component_id"])
        if component["mapping_status"] == "APPROVED":
            if component["mom_seasonal_adjustment"] != "seasonally_adjusted" or component["yoy_seasonal_adjustment"] != "not_seasonally_adjusted": raise ComponentError("COMPONENT_MAPPING_INVALID","SA/NSA contract invalid")
            for key in ("mom_series_id","yoy_series_id"):
                if component[key] in series: raise ComponentError("COMPONENT_MAPPING_INVALID","duplicate approved series mapping")
                series.add(component[key])
        if component["parent_component"] and component["aggregation_allowed"]: raise ComponentError("COMPONENT_MAPPING_INVALID","parent/child aggregation forbidden")
    for component in components:
        if component["parent_component"] and component["parent_component"] not in ids: raise ComponentError("COMPONENT_MAPPING_INVALID","unknown parent")
        if any(child not in ids for child in component["child_components"]): raise ComponentError("COMPONENT_MAPPING_INVALID","unknown child")


def _records(series: dict[str, Any]) -> dict[str, Decimal]:
    data=series.get("data")
    if not isinstance(data,list): raise ComponentError("INVALID_INPUT","series data required")
    result={}
    for row in data:
        if not isinstance(row,dict): raise ComponentError("INVALID_INPUT","row invalid")
        parsed=bls_cpi.parse_period(str(row.get("year","")),str(row.get("period","")))
        if parsed is None:
            if str(row.get("period","")) == "M13": continue
            continue
        period=bls_cpi.period_key(*parsed)
        if period in result: raise ComponentError("COMPONENT_SERIES_DUPLICATE","duplicate period")
        try: value=Decimal(str(row.get("value")))
        except InvalidOperation as exc: raise ComponentError("COMPONENT_INVALID_VALUE","non-numeric index") from exc
        if not value.is_finite(): raise ComponentError("COMPONENT_INVALID_VALUE","non-finite index")
        result[period]=value
    return result


def parse_component_response(raw_payload: dict[str, Any], registry: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    validate_component_hierarchy(registry)
    if not isinstance(raw_payload,dict) or raw_payload.get("status") != "REQUEST_SUCCEEDED": raise ComponentError("INVALID_INPUT","BLS response status invalid")
    results=raw_payload.get("Results"); rows=results.get("series") if isinstance(results,dict) else None
    if not isinstance(rows,list): raise ComponentError("INVALID_INPUT","BLS series required")
    expected=set(requested_series(registry)); parsed={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("seriesID"),str): raise ComponentError("INVALID_INPUT","series id invalid")
        sid=row["seriesID"]
        if sid in parsed: raise ComponentError("COMPONENT_SERIES_DUPLICATE","duplicate series")
        if sid not in expected: raise ComponentError("COMPONENT_SERIES_UNEXPECTED","unexpected series")
        parsed[sid]=_records(row)
    missing=expected-set(parsed)
    if missing: raise ComponentError("COMPONENT_SERIES_MISSING","missing series")
    return parsed


def find_common_component_period(series: dict[str, dict[str, Decimal]], registry: dict[str, Any]) -> str:
    candidates=None
    for component in registry["components"]:
        if component["mapping_status"] != "APPROVED": continue
        mom=set(series[component["mom_series_id"]]); yoy=set(series[component["yoy_series_id"]])
        usable={period for period in mom & yoy if bls_cpi.shift_month(period,1) in mom and bls_cpi.shift_month(period,12) in yoy}
        candidates=usable if candidates is None else candidates & usable
    if not candidates: raise ComponentError("COMPONENT_PERIOD_MISMATCH","no common component period")
    return max(candidates)


def build_component_metrics(series: dict[str, dict[str, Decimal]], registry: dict[str, Any], reference_period: str | None = None) -> dict[str, Any]:
    period=reference_period or find_common_component_period(series,registry)
    output=[]
    for component in registry["components"]:
        if component["mapping_status"] != "APPROVED": continue
        mom_current=series[component["mom_series_id"]].get(period); mom_previous=series[component["mom_series_id"]].get(bls_cpi.shift_month(period,1))
        yoy_current=series[component["yoy_series_id"]].get(period); yoy_previous=series[component["yoy_series_id"]].get(bls_cpi.shift_month(period,12))
        if None in (mom_current,mom_previous,yoy_current,yoy_previous): raise ComponentError("COMPONENT_PERIOD_MISMATCH","component period missing")
        def metric(kind,current,comparison,comparison_period,sid,sa):
            with localcontext() as context: context.prec=34; change=(current/comparison-Decimal(1))*100
            return {"component_id":component["component_id"],"metric_type":kind,"series_id":sid,"current_index":_plain(current),"comparison_index":_plain(comparison),"comparison_period":comparison_period,"raw":_plain(change),"display":_display(change),"unit":"%","seasonal_adjustment":sa,"calculation_formula":component["calculation_formula"]}
        output.append({"component_id":component["component_id"],"mom":metric("mom",mom_current,mom_previous,bls_cpi.shift_month(period,1),component["mom_series_id"],component["mom_seasonal_adjustment"]),"yoy":metric("yoy",yoy_current,yoy_previous,bls_cpi.shift_month(period,12),component["yoy_series_id"],component["yoy_seasonal_adjustment"]),"contribution":{"contribution_raw":None,"contribution_display":"산출 불가","contribution_status":"UNAVAILABLE_WEIGHT_OR_FORMULA"}})
    return {"reference_period":period,"components":output,"contribution_status":"CONTRIBUTION_UNAVAILABLE"}


def build_component_observation(series: dict[str, dict[str, Decimal]], metrics: dict[str, Any], registry: dict[str, Any], retrieved_at_utc: str, fixture_id: str) -> dict[str, Any]:
    _fixture_id(fixture_id)
    return {"schema_version":"cpi-component-observation-v1","provider":"BLS","retrieved_at_utc":retrieved_at_utc,"reference_period":metrics["reference_period"],"source_response_fixture_id":fixture_id,"requested_series":list(requested_series(registry)),"returned_series":sorted(series),"components":metrics["components"],"validation":{"status":"COMPONENT_PARSE_READY","test_fixture":True,"not_real_market_data":True},"provenance":{"source":"fixture_only","live_api_called":False}}


def build_component_snapshot(metrics: dict[str, Any], registry: dict[str, Any], retrieved_at_utc: str, fixture_id: str) -> dict[str, Any]:
    _fixture_id(fixture_id)
    payload={"schema_version":"cpi-component-snapshot-v1","indicator_type":"CPI","reference_period":metrics["reference_period"],"retrieved_at_utc":retrieved_at_utc,"component_mapping_version":registry["registry_version"],"components":metrics["components"],"completeness":"COMPLETE","validation":{"status":"COMPONENT_SNAPSHOT_READY","test_fixture":True,"not_real_market_data":True},"source":{"provider":"BLS","fixture_id":fixture_id},"integrity":{"immutable":True,"sha256":None}}
    payload["integrity"]["sha256"]=_sha(payload); return payload
