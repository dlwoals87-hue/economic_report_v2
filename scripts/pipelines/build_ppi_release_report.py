from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.pipelines import build_ppi_historical_canonical as canonical_module


STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)


class PpiReportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _blocks(pattern: re.Pattern[str], value: str) -> tuple[str, ...]:
    return tuple(pattern.findall(value))


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _metric_rows(metrics: dict[str, Any]) -> str:
    labels = {"headline_mom": "헤드라인 PPI 전월비", "headline_yoy": "헤드라인 PPI 전년비", "core_mom": "근원 PPI 전월비", "core_yoy": "근원 PPI 전년비"}
    return "".join(
        "<tr><td>%s</td><td>%s</td><td>미입력</td><td>산출하지 않음</td></tr>" % (
            labels[name], _escape(metrics[name]["actual_display"])
        ) for name in canonical_module.METRICS
    )


OPTIONAL_GROUPS = {
    "market_reaction": "시장 즉시 반응", "asset_prices": "자산 가격",
    "yield_curve": "수익률곡선", "positioning": "기관 포지셔닝과 유동성",
    "historical_analogs": "과거 유사 사례", "outlook": "전망과 시나리오",
    "track_record": "성적표", "checkpoints": "데이터 기반 체크포인트",
}
MISSING_VALUES = {None, "", "unavailable", "unsupported", "missing"}


def _meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in MISSING_VALUES
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_meaningful(item) for item in value)
    return value is not None


def _optional_sections(canonical: dict[str, Any], start_number: int) -> tuple[str, tuple[str, ...]]:
    optional = canonical.get("optional_data")
    if not isinstance(optional, dict):
        return "", ()
    sections: list[str] = []
    included: list[str] = []
    number = start_number
    for key, title in OPTIONAL_GROUPS.items():
        value = optional.get(key)
        if not _meaningful(value):
            continue
        if isinstance(value, dict):
            rows = "".join(
                "<tr><td>%s</td><td>%s</td></tr>" % (_escape(name), _escape(_optional_text(item)))
                for name, item in value.items() if _meaningful(item)
            )
            content = "<table class=\"rt\"><tbody>%s</tbody></table>" % rows
        else:
            content = "<p>%s</p>" % _escape(_optional_text(value))
        sections.append("<section data-optional-section=\"%s\"><div class=\"shead\"><span class=\"snum\">%02d</span><h2>%s</h2></div><div class=\"card\">%s</div></section>" % (key, number, _escape(title), content))
        included.append(title)
        number += 1
    return "\n".join(sections), tuple(included)


def _optional_text(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_optional_text(item)}" for key, item in value.items() if _meaningful(item))
    if isinstance(value, (list, tuple)):
        return ", ".join(_optional_text(item) for item in value if _meaningful(item))
    return str(value)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PpiReportError("PPI_RENDER_FAILED", "timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise PpiReportError("PPI_RENDER_FAILED", "timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _format_period(value: str) -> str:
    try:
        year, month = (int(item) for item in value.split("-", 1))
    except (AttributeError, ValueError) as exc:
        raise PpiReportError("PPI_RENDER_FAILED", "reference period is invalid") from exc
    return f"{year}년 {month}월"


def _format_utc(value: str) -> str:
    parsed = _parse_timestamp(value)
    return f"{parsed.year}년 {parsed.month}월 {parsed.day}일 {parsed.hour:02d}:{parsed.minute:02d} UTC"


def _format_kst(value: str) -> str:
    parsed = _parse_timestamp(value).astimezone(ZoneInfo("Asia/Seoul"))
    meridiem = "오전" if parsed.hour < 12 else "오후"
    hour = parsed.hour % 12 or 12
    return f"{parsed.year}년 {parsed.month}월 {parsed.day}일 {meridiem} {hour}시 {parsed.minute:02d}분 KST"


def _is_up(value: str) -> bool:
    return Decimal(value) > 0


def build_report(canonical: dict[str, Any], analysis: dict[str, Any], template_path: Path) -> str:
    event_id = canonical.get("meta", {}).get("event_id")
    canonical_module.validate_canonical(canonical, event_id)
    if analysis.get("event_id") != event_id or analysis.get("provider", {}).get("name") != "rule_based":
        raise PpiReportError("PPI_ANALYSIS_INVALID", "PPI analysis is invalid")
    if analysis.get("provider", {}).get("external_ai_api_called") is not False or analysis.get("usage", {}).get("cost") != "free":
        raise PpiReportError("PPI_ANALYSIS_INVALID", "PPI analysis must be free and offline")
    template = template_path.read_text(encoding="utf-8")
    meta = canonical["meta"]
    if "</head>" not in template or "</body>" not in template:
        raise PpiReportError("PPI_RENDER_FAILED", "template has no body close")
    head, original_body = template.split("</head>", 1)
    head = head.replace("{{REPORT_TITLE}}", _escape(f"{_format_period(meta['reference_period'])} 미국 생산자물가지수(PPI) 과거 백필"))
    body_scripts = "\n".join(_blocks(SCRIPT_RE, original_body))
    optional_sections, included = _optional_sections(canonical, 4)
    excluded = tuple(title for title in OPTIONAL_GROUPS.values() if title not in included)
    availability = "<section id=\"data-availability-summary\"><div class=\"shead\"><span class=\"snum\">03</span><h2>데이터 가용성</h2></div><div class=\"card\"><p><b>이번 리포트 포함:</b> 헤드라인·근원 PPI 전월비와 전년비, 발표 및 조회 메타데이터, 규칙 기반 PPI 해석%s.</p><p><b>이번 리포트 미포함:</b> %s.</p><p>해당 데이터 소스가 이번 과거 백필 입력에 연결되지 않았습니다. 외부 데이터 없이 이를 추정하지 않았습니다.</p></div></section>" % ((", " + ", ".join(included)) if included else "", _escape(", ".join(excluded)))
    metrics = canonical["metrics"]
    headline_mom = metrics["headline_mom"]
    headline_yoy = metrics["headline_yoy"]
    core_mom = metrics["core_mom"]
    core_yoy = metrics["core_yoy"]
    headline_direction = "상승" if _is_up(headline_mom["actual_raw"]) and _is_up(headline_yoy["actual_raw"]) else "변동"
    core_direction = "상승" if _is_up(core_mom["actual_raw"]) and _is_up(core_yoy["actual_raw"]) else "변동"
    document = """%s</head>
<body>
<div class="topbar"><div class="topbar-in"><div class="brand">경제 지표 리포트</div><div class="badge">과거 PPI 백필</div></div></div>
<div class="wrap"><div class="hero"><div class="date">공식 발표 %s</div><div class="multi-note">현재 BLS API에서 조회한 과거 데이터이며, 발표 당시 실시간으로 포착한 값이 아닙니다.</div><div class="evt-tabs"><span class="evt-tab lead">미국 PPI <small>%s</small></span></div><h1>%s 미국 생산자물가지수(PPI)<br><span class="down">전월비 %s · 전년비 %s</span></h1><p>근원 PPI는 전월비 %s, 전년비 %s를 기록했습니다.</p><div class="chips"><span class="chip gold">과거 데이터 백필</span><span class="chip blue">시장 예상치 미입력</span><span class="chip green">규칙 기반 해석</span><span class="chip green">외부 AI 미사용</span></div></div>
<section id="ppi-metrics"><div class="shead"><span class="snum">01</span><h2>PPI 핵심 지표</h2></div><div class="card"><p><b>기준월:</b> %s<br><b>공식 발표 UTC:</b> %s<br><b>공식 발표:</b> %s<br><b>데이터 조회 UTC:</b> %s<br><b>데이터 조회:</b> %s</p><table class="rt"><thead><tr><th>지표</th><th>실제</th><th>예상</th><th>이전</th></tr></thead><tbody>%s</tbody></table></div></section>
<section id="ppi-analysis"><div class="shead"><span class="snum">02</span><h2>규칙 기반 PPI 해석</h2></div><div class="card"><p>헤드라인 PPI는 전월비와 전년비 모두 %s했습니다. 근원 PPI도 전월비와 전년비 모두 %s했습니다.</p><p>근원 PPI는 식품·에너지·무역서비스를 제외한 최종수요를 뜻하며, 헤드라인 PPI와 별도로 해석해야 합니다.</p><p>PPI는 생산자 가격압력을 설명하지만 소비자물가로의 전이를 완전히 보여주는 지표는 아닙니다. 이번 결과만으로 CPI나 연준의 정책 결정을 확정적으로 예측할 수 없습니다.</p><p>시장 반응과 자산 가격 데이터는 이번 입력에 포함되지 않았습니다.</p><p>규칙 기반 해석을 사용했으며 외부 AI API를 사용하지 않았습니다. 비용은 무료입니다.</p><p>이 리포트는 현재 연결된 PPI 백필 데이터만 사용했으며 투자 조언이 아닙니다.</p></div></section>
%s
%s
<div class="disclaimer">이 리포트는 현재 연결된 PPI 백필 데이터만 사용했습니다. 투자 조언이 아닙니다.</div></div>
%s
</body>
</html>
""" % (head, _escape(_format_utc(meta["original_release_datetime_utc"])), _escape(_format_period(meta["reference_period"])), _escape(_format_period(meta["reference_period"])), _escape(headline_mom["actual_display"]), _escape(headline_yoy["actual_display"]), _escape(core_mom["actual_display"]), _escape(core_yoy["actual_display"]), _escape(_format_period(meta["reference_period"])), _escape(_format_utc(meta["original_release_datetime_utc"])), _escape(_format_kst(meta["original_release_datetime_utc"])), _escape(_format_utc(meta["retrieved_at_utc"])), _escape(_format_kst(meta["retrieved_at_utc"])), _metric_rows(metrics), _escape(headline_direction), _escape(core_direction), optional_sections, availability, body_scripts)
    if _blocks(STYLE_RE, document) != _blocks(STYLE_RE, template) or _blocks(SCRIPT_RE, document) != _blocks(SCRIPT_RE, template):
        raise PpiReportError("PPI_DESIGN_CHANGED", "v11 style or script changed")
    if "{{" in document:
        raise PpiReportError("PPI_RENDER_FAILED", "unresolved template placeholder")
    return document


def build_report_file(canonical_path: Path, analysis_path: Path, output_path: Path, event_id: str, template_path: Path) -> str:
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PpiReportError("PPI_REPORT_INPUT_INVALID", "PPI report input is unreadable") from exc
    document = build_report(canonical, analysis, template_path)
    data = document.encode("utf-8")
    if output_path.exists():
        if output_path.read_bytes() == data:
            return hashlib.sha256(data).hexdigest()
        raise PpiReportError("PPI_REPORT_CONFLICT", "report output differs")
    output_path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()
