from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis import generate_cpi_analysis  # noqa: E402


TEMPLATE_PATH = PROJECT_ROOT / "templates" / "report.html"
DESIGN_SOURCE_PATH = PROJECT_ROOT / "templates" / "sample_report_v11.html"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "cpi_analysis_v1.schema.json"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "cpi_analysis_v1.md"

METRIC_ORDER = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
METRIC_LOCATIONS = {
    "headline_mom": ("headline", "mom"),
    "headline_yoy": ("headline", "yoy"),
    "core_mom": ("core", "mom"),
    "core_yoy": ("core", "yoy"),
}
METRIC_LABELS = {
    "headline_mom": "헤드라인 CPI 전월비",
    "headline_yoy": "헤드라인 CPI 전년비",
    "core_mom": "근원 CPI 전월비",
    "core_yoy": "근원 CPI 전년비",
}
UNSUPPORTED_LABELS = {
    "market_reaction": "시장 반응",
    "asset_prices": "자산 가격",
    "yield_curve": "수익률 곡선",
    "positioning": "포지셔닝",
    "liquidity": "유동성",
    "component_breakdown": "세부 품목",
    "historical_analogs": "과거 유사 사례",
    "forecast_probabilities": "전망 확률",
}
UNAVAILABLE = "해당 데이터는 이번 리포트 입력에 포함되지 않았습니다."
ZERO_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
UNRESOLVED_PATTERNS = (
    re.compile(r"\{\{[A-Z0-9_]+\}\}"),
    re.compile(r"\$\{[^}]+\}"),
    re.compile(r"__PLACEHOLDER__"),
    re.compile(r"PLACEHOLDER_"),
)
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
ACTIVE_TAG_RE = re.compile(r"<\s*(script|iframe|object|embed)\b", re.IGNORECASE)
EVENT_HANDLER_RE = re.compile(r"<[^>]+\s+on[a-z0-9_-]+\s*=", re.IGNORECASE)
JAVASCRIPT_URL_RE = re.compile(r"(?:href|src)\s*=\s*['\"]\s*javascript:", re.IGNORECASE)
SAMPLE_LEAK_MARKERS = (
    "sample",
    "샘플",
    "S&P500–2년물 상관",
    "$6.27T",
    "나스닥 +1.1%",
    "기본 — 완만한 리스크온",
    "Bullish 68",
)


class CpiReportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReportResult:
    status: str
    event_id: str
    output_path: str
    html_created: bool
    canonical_sha256: str | None
    analysis_sha256: str | None
    template_sha256: str | None
    design_source_sha256: str | None
    report_sha256: str | None
    generated_at_utc: str | None
    physical_lines: int
    missing_payload_keys: tuple[str, ...]
    unused_payload_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_payload_keys"] = list(self.missing_payload_keys)
        payload["unused_payload_keys"] = list(self.unused_payload_keys)
        return payload


def project_root() -> Path:
    return PROJECT_ROOT


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _reject_parent_parts(path: PurePath, label: str) -> None:
    if ".." in path.parts:
        raise CpiReportError("INVALID_PATH", f"{label} must not contain parent traversal")


def _resolve_project_path(
    root: Path,
    value: str | None,
    default: Path,
    label: str,
) -> Path:
    root = root.resolve()
    candidate = default if value is None else Path(value)
    _reject_parent_parts(candidate, label)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CpiReportError("INVALID_PATH", f"{label} must stay inside the project root") from exc
    return resolved


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CpiReportError("INVALID_INPUT", f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CpiReportError("INVALID_INPUT", f"{label} must contain a JSON object")
    return payload, data


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CpiReportError("INVALID_INPUT", f"{field} must be a non-empty string")
    return value


def _extract_styles(source: str) -> tuple[str, ...]:
    return tuple(STYLE_RE.findall(source))


def _validate_design_sources(template: str, design_source: str) -> None:
    template_styles = _extract_styles(template)
    source_styles = _extract_styles(design_source)
    if not source_styles or template_styles != source_styles:
        raise CpiReportError(
            "TEMPLATE_STYLE_MISMATCH",
            "report.html style blocks must exactly match sample_report_v11.html",
        )
    if re.search(r"<script\b", template, re.IGNORECASE):
        raise CpiReportError("TEMPLATE_SCRIPT_FOUND", "report.html must not contain script tags")


def _build_actual_template(template: str) -> str:
    section_marker = "<!-- 01 -->"
    if section_marker not in template:
        raise CpiReportError("INVALID_TEMPLATE", "report section marker is missing")
    prefix = template.split(section_marker, 1)[0]
    prefix, tab_count = re.subn(
        r"\s*<span class=\"evt-tab\">.*?</span>",
        "",
        prefix,
        count=1,
        flags=re.DOTALL,
    )
    prefix, drift_count = re.subn(
        r"\s*<div class=\"drift\">.*?</div>",
        "",
        prefix,
        count=1,
        flags=re.DOTALL,
    )
    prefix, secondary_count = re.subn(
        r"\s*<div class=\"sub-evt\">.*?</div>",
        "",
        prefix,
        count=1,
        flags=re.DOTALL,
    )
    if (tab_count, drift_count, secondary_count) != (1, 1, 1):
        raise CpiReportError("INVALID_TEMPLATE", "unsupported hero blocks could not be isolated")
    return prefix.rstrip() + "\n\n"


def _expected_display(metric: dict[str, Any]) -> str:
    expected = metric.get("expected")
    return "미입력" if expected is None else f"{expected}%"


def _surprise_display(metric: dict[str, Any]) -> str:
    surprise = metric.get("surprise")
    if surprise is None:
        return "산출 불가"
    if not isinstance(surprise, dict):
        raise CpiReportError("INVALID_INPUT", "metric surprise must be an object or null")
    return _non_empty_string(surprise.get("display"), "metric.surprise.display")


def _metric_payload(canonical: dict[str, Any], metric_key: str) -> dict[str, str]:
    group_key, period_key = METRIC_LOCATIONS[metric_key]
    event = canonical.get("event")
    group = event.get(group_key) if isinstance(event, dict) else None
    metric = group.get(period_key) if isinstance(group, dict) else None
    if not isinstance(metric, dict):
        raise CpiReportError("INVALID_INPUT", f"event.metrics.{metric_key} is required")
    historical = isinstance(canonical.get("meta"), dict) and canonical["meta"].get("data_origin") == "historical_backfill"
    actual_display_key = "actual_display" if historical else "actual_as_released_display"
    previous_display_key = "previous_display" if historical else "previous_as_released_display"
    return {
        "actual": _non_empty_string(
            metric.get(actual_display_key),
            f"event.metrics.{metric_key}.{actual_display_key}",
        ),
        "expected": _expected_display(metric),
        "previous": _non_empty_string(
            metric.get(previous_display_key),
            f"event.metrics.{metric_key}.{previous_display_key}",
        ),
        "surprise": _surprise_display(metric),
    }


def _safe_text(value: Any) -> str:
    escaped = html.escape(str(value), quote=True)
    return re.sub(r"javascript:", "javascript&#58;", escaped, flags=re.IGNORECASE)


def _build_flat_payload(
    template: str,
    canonical: dict[str, Any],
    analysis_wrapper: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, str]:
    keys = set(PLACEHOLDER_RE.findall(template))
    payload = {key: UNAVAILABLE for key in keys}
    meta = canonical["meta"]
    source = canonical["source"]
    analysis = analysis_wrapper["analysis"]
    headline_yoy = _metric_payload(canonical, "headline_yoy")
    core_yoy = _metric_payload(canonical, "core_yoy")
    display_name = _non_empty_string(profile.get("display_name"), "profile.CPI.display_name")
    reference_period = _non_empty_string(meta.get("reference_period"), "meta.reference_period")
    release_kst = _non_empty_string(meta.get("release_datetime_kst"), "meta.release_datetime_kst")
    provider = _non_empty_string(source.get("provider"), "source.provider")

    payload.update(
        {
            "REPORT_TITLE": f"{reference_period} 미국 CPI 발표 리포트",
            "BRAND_NAME": "ECONOMIC REPORT",
            "SAMPLE_BADGE": "ACTUAL RELEASE",
            "REPORT_DATETIME": f"{release_kst} · {provider} 최초 발표값",
            "MULTI_EVENT_NOTE": "분석 방식: 규칙 기반 자동 해석 · 외부 AI API: 사용하지 않음",
            "INDICATOR_NAME": display_name,
            "LEAD_EVENT_LABEL": "최초 발표값",
            "HEADLINE_PREFIX": f"{reference_period} 미국 CPI",
            "CPI_ACTUAL": headline_yoy["actual"],
            "HEADLINE_SURPRISE": (
                "예상치 미입력"
                if headline_yoy["expected"] == "미입력"
                else f"예상치 {headline_yoy['expected']} · 차이 {headline_yoy['surprise']}"
            ),
            "HEADLINE_MESSAGE": analysis["executive_summary"]["one_line"],
            "IMPORTANCE_LABEL": "미국 CPI 최초 발표값",
            "SURPRISE_LABEL": f"예상 대비 차이: {headline_yoy['surprise']}",
            "DETAIL_CONFIRM_LABEL": "규칙 기반 자동 해석",
            "NARRATIVE_FIT_LABEL": "외부 AI API 미사용",
            "TABLE_ACTUAL_LABEL": "실제",
            "TABLE_EXPECTED_LABEL": "예상",
            "TABLE_PREVIOUS_LABEL": "이전",
            "CPI_SUBLABEL": "헤드라인 · 전년비",
            "CPI_SURPRISE_DELTA": headline_yoy["surprise"],
            "CPI_EXPECTED": headline_yoy["expected"],
            "CPI_PREVIOUS": headline_yoy["previous"],
            "CORE_INDICATOR_NAME": "근원 CPI",
            "CORE_CPI_SUBLABEL": "근원 · 전년비",
            "CORE_CPI_ACTUAL": core_yoy["actual"],
            "CORE_CPI_SURPRISE_DELTA": core_yoy["surprise"],
            "CORE_CPI_EXPECTED": core_yoy["expected"],
            "CORE_CPI_PREVIOUS": core_yoy["previous"],
            "STRIP_NOTE_PREFIX": analysis["inflation_interpretation"]["momentum"],
            "STRIP_NOTE_BOLD": "actual_as_released 기준",
            "STRIP_NOTE_SUFFIX": "정보 제공용이며 투자 조언이 아닙니다.",
        }
    )
    return payload


def render_flat_template(template: str, payload: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    template_keys = set(PLACEHOLDER_RE.findall(template))
    payload_keys = set(payload)
    missing = tuple(sorted(template_keys - payload_keys))
    unused = tuple(sorted(payload_keys - template_keys))
    if missing or unused:
        raise CpiReportError(
            "PAYLOAD_KEY_MISMATCH",
            f"missing={list(missing)}, unused={list(unused)}",
        )
    rendered = template
    for key in sorted(template_keys):
        rendered = rendered.replace("{{" + key + "}}", _safe_text(payload[key]))
    if any(pattern.search(rendered) for pattern in UNRESOLVED_PATTERNS):
        raise CpiReportError("UNRESOLVED_PLACEHOLDER", "rendered HTML contains a placeholder")
    return rendered, missing, unused


def _build_metric_section(metric_values: dict[str, dict[str, str]]) -> str:
    rows = []
    for metric_key in METRIC_ORDER:
        values = metric_values[metric_key]
        cells = "".join(
            f'<td data-field="{field}">{_safe_text(values[field])}</td>'
            for field in ("actual", "expected", "previous", "surprise")
        )
        rows.append(
            f'<tr data-metric="{metric_key}"><td>{_safe_text(METRIC_LABELS[metric_key])}</td>{cells}</tr>'
        )
    return """<!-- ACTUAL CPI METRICS -->
<section>
  <div class="shead"><span class="snum">01</span><h2>최초 발표 CPI 지표</h2></div>
  <div class="card">
    <table class="rt">
      <thead><tr><th>지표</th><th>실제</th><th>예상</th><th>이전</th><th>예상 대비 차이</th></tr></thead>
      <tbody>
        %s
      </tbody>
    </table>
  </div>
</section>
""" % "\n        ".join(rows)


def _analysis_paragraph(label: str, value: str) -> str:
    return f"<p><b>{_safe_text(label)}</b> {_safe_text(value)}</p>"


def _build_analysis_section(analysis: dict[str, Any]) -> str:
    executive = analysis["executive_summary"]
    inflation = analysis["inflation_interpretation"]
    policy = analysis["policy_implication"]
    paragraphs = "\n      ".join(
        (
            _analysis_paragraph("상세 요약", executive["detail"]),
            _analysis_paragraph("헤드라인 물가", inflation["headline"]),
            _analysis_paragraph("근원 물가", inflation["core"]),
            _analysis_paragraph("물가 모멘텀", inflation["momentum"]),
            _analysis_paragraph("정책 신호", policy["signal"]),
            _analysis_paragraph("정책 해석", policy["explanation"]),
        )
    )
    points = "\n        ".join(
        f'<li><span><b>{_safe_text(point["title"])}</b> {_safe_text(point["detail"])}</span></li>'
        for point in analysis["key_points"]
    )
    return f"""<!-- RULE BASED ANALYSIS -->
<section>
  <div class="shead"><span class="snum">02</span><h2>규칙 기반 CPI 해석</h2></div>
  <div class="keyline">{_safe_text(executive["one_line"])}</div>
  <div class="card">
      {paragraphs}
      <ul class="reasons">
        {points}
      </ul>
      <p><b>분석 신뢰도</b> {_safe_text(analysis["confidence"])}</p>
      <p><b>분석 방식</b> 규칙 기반 자동 해석 · 외부 AI API 사용하지 않음</p>
  </div>
</section>
"""


def _build_limitations_section(analysis: dict[str, Any]) -> str:
    risks = "\n        ".join(
        f"<li>{_safe_text(item)}</li>" for item in analysis["risks_and_caveats"]
    )
    unsupported = "\n        ".join(
        (
            '<li><b>%s</b> %s %s</li>'
            % (
                _safe_text(UNSUPPORTED_LABELS[item["section"]]),
                _safe_text(UNAVAILABLE),
                _safe_text(item["reason"]),
            )
        )
        for item in analysis["unsupported_sections"]
    )
    return f"""<!-- INPUT COVERAGE -->
<section>
  <div class="shead"><span class="snum">03</span><h2>입력 범위와 유의사항</h2></div>
  <div class="keyline">{_safe_text(UNAVAILABLE)}</div>
  <div class="card">
    <p><b>해석상 유의사항</b></p>
    <ul class="risk">
        {risks}
    </ul>
    <p><b>미지원 영역</b></p>
    <ul class="risk">
        {unsupported}
    </ul>
  </div>
</section>
"""


def _metadata_comment(
    *,
    event_id: str,
    generated_at_utc: str,
    canonical_sha256: str,
    analysis_sha256: str,
    template_sha256: str,
    design_source_sha256: str,
) -> str:
    metadata = {
        "event_id": event_id,
        "generated_at_utc": generated_at_utc,
        "canonical_sha256": canonical_sha256,
        "analysis_sha256": analysis_sha256,
        "template_sha256": template_sha256,
        "design_source_sha256": design_source_sha256,
        "rendering_version": "cpi-release-report-v1",
    }
    return "<!-- cpi-report-metadata " + json.dumps(metadata, ensure_ascii=False, sort_keys=True) + " -->"


def _build_document(
    rendered_prefix: str,
    metric_values: dict[str, dict[str, str]],
    analysis: dict[str, Any],
    metadata_comment: str,
) -> str:
    return (
        rendered_prefix
        + _build_metric_section(metric_values)
        + "\n"
        + _build_analysis_section(analysis)
        + "\n"
        + _build_limitations_section(analysis)
        + "\n"
        + '<div class="disclaimer">정보 제공용이며 투자 조언이 아닙니다. '
        + "최종 판단과 책임은 이용자에게 있습니다.</div>\n"
        + metadata_comment
        + "\n</div>\n</body>\n</html>\n"
    )


def _validate_rendered_metrics(document: str, expected: dict[str, dict[str, str]]) -> None:
    for metric_key, fields in expected.items():
        row_match = re.search(
            rf'<tr data-metric="{re.escape(metric_key)}">(.*?)</tr>',
            document,
            re.DOTALL,
        )
        if row_match is None:
            raise CpiReportError("METRIC_RENDER_MISMATCH", f"rendered row missing: {metric_key}")
        row = row_match.group(1)
        for field, expected_value in fields.items():
            cell_match = re.search(
                rf'<td data-field="{re.escape(field)}">(.*?)</td>',
                row,
                re.DOTALL,
            )
            if cell_match is None:
                raise CpiReportError(
                    "METRIC_RENDER_MISMATCH",
                    f"rendered field missing: {metric_key}.{field}",
                )
            actual_value = html.unescape(re.sub(r"<[^>]*>", "", cell_match.group(1)))
            if actual_value != expected_value:
                raise CpiReportError(
                    "METRIC_RENDER_MISMATCH",
                    f"rendered field differs: {metric_key}.{field}",
                )


def _validate_final_html(document: str, design_source: str) -> None:
    if any(pattern.search(document) for pattern in UNRESOLVED_PATTERNS):
        raise CpiReportError("UNRESOLVED_PLACEHOLDER", "final HTML contains a placeholder")
    lower_document = document.casefold()
    for marker in SAMPLE_LEAK_MARKERS:
        if marker.casefold() in lower_document:
            raise CpiReportError("SAMPLE_DATA_LEAK", f"sample marker found: {marker}")
    if ACTIVE_TAG_RE.search(document):
        raise CpiReportError("UNSAFE_HTML", "active embedded content is not allowed")
    if EVENT_HANDLER_RE.search(document):
        raise CpiReportError("UNSAFE_HTML", "event handler attributes are not allowed")
    if JAVASCRIPT_URL_RE.search(document):
        raise CpiReportError("UNSAFE_HTML", "javascript URLs are not allowed")
    if _extract_styles(document) != _extract_styles(design_source):
        raise CpiReportError("TEMPLATE_STYLE_MISMATCH", "rendered style blocks changed")


def _load_and_validate_inputs(
    *,
    root: Path,
    event_id: str,
    canonical_path: Path,
    analysis_path: Path,
) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes, dict[str, Any]]:
    canonical, canonical_bytes = _read_json(canonical_path, "canonical release")
    analysis_wrapper, analysis_bytes = _read_json(analysis_path, "analysis")
    canonical_sha = _sha256(canonical_bytes)
    analysis_sha = _sha256(analysis_bytes)

    try:
        generate_cpi_analysis.validate_canonical_release(canonical, event_id)
    except generate_cpi_analysis.CpiAnalysisError as exc:
        raise CpiReportError("INVALID_CANONICAL_RELEASE", str(exc)) from exc
    if analysis_wrapper.get("schema_version") != "1.0":
        raise CpiReportError("INVALID_ANALYSIS", "analysis schema_version must be 1.0")
    if analysis_wrapper.get("analysis_version") != "cpi-analysis-v1":
        raise CpiReportError("INVALID_ANALYSIS", "analysis_version must be cpi-analysis-v1")
    if analysis_wrapper.get("event_id") != event_id or analysis_wrapper.get("indicator_type") != "CPI":
        raise CpiReportError("INPUT_INTEGRITY_MISMATCH", "analysis identity does not match")

    input_meta = analysis_wrapper.get("input")
    source = canonical.get("source")
    if not isinstance(input_meta, dict) or not isinstance(source, dict):
        raise CpiReportError("INPUT_INTEGRITY_MISMATCH", "input hash metadata is missing")
    historical = isinstance(canonical.get("meta"), dict) and canonical["meta"].get("data_origin") == "historical_backfill"
    source_hash_field = "historical_observation_sha256" if historical else "release_capture_sha256"
    release_sha = source.get(source_hash_field)
    expected_canonical_path = _relative_path(canonical_path, root)
    if (
        input_meta.get("canonical_path") != expected_canonical_path
        or input_meta.get("canonical_sha256") != canonical_sha
        or input_meta.get(source_hash_field) != release_sha
    ):
        raise CpiReportError("INPUT_INTEGRITY_MISMATCH", "canonical and analysis hashes do not match")

    provider = analysis_wrapper.get("provider")
    if not isinstance(provider, dict):
        raise CpiReportError("INVALID_ANALYSIS", "provider metadata is missing")
    if (
        provider.get("name") != "rule_based"
        or provider.get("requested_provider") != "rule_based"
        or provider.get("external_api_called") is not False
        or provider.get("fallback_used") is not False
        or any(
            provider.get(key) is not None
            for key in ("model_requested", "model_returned", "response_id", "fallback_reason")
        )
    ):
        raise CpiReportError("INVALID_ANALYSIS", "only the free rule_based analysis is allowed")
    if analysis_wrapper.get("usage") != ZERO_USAGE:
        raise CpiReportError("INVALID_ANALYSIS", "analysis usage must be zero")

    facts = generate_cpi_analysis.build_facts(canonical)
    if analysis_wrapper.get("facts") != facts:
        raise CpiReportError("INPUT_INTEGRITY_MISMATCH", "analysis facts do not match canonical")
    schema, schema_bytes = _read_json(SCHEMA_PATH, "analysis schema")
    versions = analysis_wrapper.get("versions")
    if not isinstance(versions, dict) or (
        versions.get("schema_sha256") != _sha256(schema_bytes)
        or versions.get("prompt_sha256") != _sha256_file(PROMPT_PATH)
    ):
        raise CpiReportError("INVALID_ANALYSIS", "analysis schema or prompt hash is stale")
    analysis = analysis_wrapper.get("analysis")
    if not isinstance(analysis, dict):
        raise CpiReportError("INVALID_ANALYSIS", "analysis payload is missing")
    try:
        validation = generate_cpi_analysis.validate_analysis_output(analysis, schema, facts)
    except generate_cpi_analysis.CpiAnalysisError as exc:
        raise CpiReportError("INVALID_ANALYSIS", str(exc)) from exc
    if analysis_wrapper.get("validation") != validation:
        raise CpiReportError("INVALID_ANALYSIS", "analysis validation metadata is inconsistent")

    profile_path = root / "data" / "indicator_profiles.json"
    if not profile_path.exists():
        raise CpiReportError("INPUT_PROFILE_NOT_FOUND", "data/indicator_profiles.json is required")
    profiles, _ = _read_json(profile_path, "indicator profiles")
    profile = profiles.get("CPI")
    if not isinstance(profile, dict) or profile.get("country") != "US":
        raise CpiReportError("INVALID_INPUT_PROFILE", "the US CPI profile is required")
    return canonical, canonical_bytes, analysis_wrapper, analysis_bytes, profile


def _write_new_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        try:
            os.link(temp_path, path)
        except OSError as exc:
            if path.exists():
                raise CpiReportError("OUTPUT_CONFLICT", "report output already exists") from exc
            os.replace(temp_path, path)
    except FileExistsError as exc:
        raise CpiReportError("OUTPUT_CONFLICT", "report output already exists") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def build_report(
    root: Path,
    event_id: str,
    *,
    canonical: str | None = None,
    analysis: str | None = None,
    output: str | None = None,
) -> ReportResult:
    root = root.resolve()
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise CpiReportError("INVALID_EVENT_ID", "event_id must use uppercase letters, digits, and underscores")
    canonical_path = _resolve_project_path(
        root,
        canonical,
        root / "data" / "generated" / "cpi" / event_id / "canonical_release.json",
        "canonical path",
    )
    analysis_path = _resolve_project_path(
        root,
        analysis,
        root / "data" / "analysis" / "cpi" / event_id / "cpi-analysis-v1.json",
        "analysis path",
    )
    output_path = _resolve_project_path(
        root,
        output,
        root / "docs" / "reports" / f"{event_id}.html",
        "output path",
    )
    if output_path.suffix.lower() != ".html":
        raise CpiReportError("INVALID_PATH", "output path must end with .html")
    output_relative = _relative_path(output_path, root)
    if not canonical_path.exists():
        return ReportResult(
            "CANONICAL_RELEASE_NOT_FOUND",
            event_id,
            output_relative,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            (),
            (),
        )
    if not analysis_path.exists():
        return ReportResult(
            "ANALYSIS_NOT_FOUND",
            event_id,
            output_relative,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            (),
            (),
        )

    design_sha_before = _sha256_file(DESIGN_SOURCE_PATH)
    template_bytes = TEMPLATE_PATH.read_bytes()
    design_bytes = DESIGN_SOURCE_PATH.read_bytes()
    try:
        template = template_bytes.decode("utf-8")
        design_source = design_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CpiReportError("INVALID_TEMPLATE", "templates must be UTF-8") from exc
    _validate_design_sources(template, design_source)

    canonical_payload, canonical_bytes, analysis_wrapper, analysis_bytes, profile = (
        _load_and_validate_inputs(
            root=root,
            event_id=event_id,
            canonical_path=canonical_path,
            analysis_path=analysis_path,
        )
    )
    generated_at_utc = _non_empty_string(
        analysis_wrapper.get("generated_at_utc"),
        "analysis.generated_at_utc",
    )
    actual_template = _build_actual_template(template)
    flat_payload = _build_flat_payload(actual_template, canonical_payload, analysis_wrapper, profile)
    rendered_prefix, missing, unused = render_flat_template(actual_template, flat_payload)
    metric_values = {
        metric_key: _metric_payload(canonical_payload, metric_key) for metric_key in METRIC_ORDER
    }
    canonical_sha = _sha256(canonical_bytes)
    analysis_sha = _sha256(analysis_bytes)
    template_sha = _sha256(template_bytes)
    design_sha = _sha256(design_bytes)
    document = _build_document(
        rendered_prefix,
        metric_values,
        analysis_wrapper["analysis"],
        _metadata_comment(
            event_id=event_id,
            generated_at_utc=generated_at_utc,
            canonical_sha256=canonical_sha,
            analysis_sha256=analysis_sha,
            template_sha256=template_sha,
            design_source_sha256=design_sha,
        ),
    )
    _validate_rendered_metrics(document, metric_values)
    _validate_final_html(document, design_source)
    if _sha256_file(DESIGN_SOURCE_PATH) != design_sha_before:
        raise CpiReportError("DESIGN_SOURCE_CHANGED", "sample_report_v11.html changed during rendering")

    document_bytes = document.encode("utf-8")
    report_sha = _sha256(document_bytes)
    physical_lines = len(document.splitlines())
    if output_path.exists():
        existing_bytes = output_path.read_bytes()
        if existing_bytes == document_bytes:
            return ReportResult(
                "ALREADY_UP_TO_DATE",
                event_id,
                output_relative,
                False,
                canonical_sha,
                analysis_sha,
                template_sha,
                design_sha,
                report_sha,
                generated_at_utc,
                physical_lines,
                missing,
                unused,
            )
        raise CpiReportError("OUTPUT_CONFLICT", "existing report differs; overwrite is forbidden")
    _write_new_file(output_path, document_bytes)
    return ReportResult(
        "REPORT_CREATED",
        event_id,
        output_relative,
        True,
        canonical_sha,
        analysis_sha,
        template_sha,
        design_sha,
        report_sha,
        generated_at_utc,
        physical_lines,
        missing,
        unused,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an immutable CPI release HTML report")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--canonical")
    parser.add_argument("--analysis")
    parser.add_argument("--output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_report(
            project_root(),
            args.event_id,
            canonical=args.canonical,
            analysis=args.analysis,
            output=args.output,
        )
    except CpiReportError as exc:
        print(exc.code)
        print(f"error: {exc}")
        return 1
    print(result.status)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
