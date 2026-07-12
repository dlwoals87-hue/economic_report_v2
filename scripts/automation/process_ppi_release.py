from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.common import preview
from scripts.pipelines import build_ppi_release_canonical as canonical
from scripts.automation import update_report_index


def _index(root: Path, event_id: str, canonical_payload: dict[str, Any], report_path: Path) -> str:
    index_path = root / "docs/index.html"
    source = index_path.read_text(encoding="utf-8")
    prefix, managed, suffix = update_report_index._marker_bounds(source)
    entries = update_report_index._parse_entries(managed)
    report_sha = preview.file_sha256(report_path)
    release = canonical_payload["release"]["release_datetime_utc"]
    entry = update_report_index.ReportEntry(event_id, "US Producer Price Index", canonical_payload["event"]["reference_period"], release, f"reports/ppi/{event_id}.html", report_sha)
    same = [item for item in entries if item.event_id == event_id]
    if same:
        if len(same) == 1 and same[0] == entry: return "PPI_INDEX_ALREADY_UP_TO_DATE"
        raise canonical.PpiLiveCanonicalError("PPI_INDEX_CONFLICT", "PPI index entry conflicts")
    if any(item.report_href == entry.report_href for item in entries): raise canonical.PpiLiveCanonicalError("PPI_INDEX_CONFLICT", "PPI report href conflicts")
    region = update_report_index._render_managed_region(entries + [entry])
    candidate = prefix + region + suffix
    update_report_index._validate_final_index(source, candidate, region)
    preview.write_immutable_bytes(index_path.with_name(".ppi-index-new.html"), candidate.encode("utf-8"))
    index_path.write_bytes((index_path.with_name(".ppi-index-new.html")).read_bytes())
    index_path.with_name(".ppi-index-new.html").unlink()
    return "PPI_INDEX_UPDATED"


def process(root: Path,event_id: str) -> dict[str,Any]:
    release=root/"data/releases/ppi"/event_id/"as_released.json"; base=root/"data/generated/ppi"/event_id; analysis_path=root/"data/analysis/ppi"/event_id/"analysis.json"; report=root/"docs/reports/ppi"/(event_id+".html")
    created=[]
    try: status=canonical.build_file(release,base/"canonical.json",event_id)
    except canonical.PpiLiveCanonicalError as exc:return {"status":exc.code,"commit_paths":[]}
    if status == "PPI_CANONICAL_CREATED": created.append("data/generated/ppi/%s/canonical.json"%event_id)
    c=json.loads((base/"canonical.json").read_text(encoding="utf-8")); analysis={"schema_version":"1.0","event_id":event_id,"provider":{"name":"rule_based","external_ai_api_called":False},"usage":{"cost":"free"},"analysis":{"summary":"Live PPI capture","headline":"", "core":"", "pressure":""}}
    if not analysis_path.exists(): preview.write_immutable_bytes(analysis_path,preview.json_bytes(analysis)); created.append("data/analysis/ppi/%s/analysis.json"%event_id)
    if not report.exists():
        rows="".join(f"<li>{name}: {value['actual_display']}</li>" for name,value in c['metrics'].items()); html=f"<html><body><h1>PPI 실제 발표 포착</h1><ul>{rows}</ul><p>규칙 기반 해석 · 외부 AI 미사용 · 비용 무료 · 투자 조언이 아닙니다.</p></body></html>"; preview.write_immutable_bytes(report,html.encode())
        created.append("docs/reports/ppi/%s.html"%event_id)
    try: index_status=_index(root,event_id,c,report)
    except canonical.PpiLiveCanonicalError as exc:return {"status":exc.code,"commit_paths":[]}
    if index_status == "PPI_INDEX_UPDATED": created.append("docs/index.html")
    paths=["data/generated/ppi/%s/canonical.json"%event_id,"data/analysis/ppi/%s/analysis.json"%event_id,"docs/reports/ppi/%s.html"%event_id,"docs/index.html"]
    if not created: status="ALREADY_PROCESSED"
    elif created == ["docs/index.html"]: status="INDEX_ONLY_RESUMED"
    else: status="PROCESSED_AND_INDEXED"
    return {"status":status,"event_id":event_id,"provider":"rule_based","external_api_called":False,"external_ai_api_called":False,"cost_mode":"free","created_paths":created,"commit_paths":created}
