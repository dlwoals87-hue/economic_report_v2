from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path, PurePath
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.providers import github_models, openai_responses, rule_based  # noqa: E402
from scripts.providers.base import (  # noqa: E402
    AnalysisProviderError,
    AnalysisProviderResult,
    zero_usage,
)


ANALYSIS_VERSION = "cpi-analysis-v1"
SCHEMA_VERSION = "1.0"
PROMPT_NAME = "cpi_analysis_v1"
SCHEMA_NAME = "cpi_analysis_v1"
SUPPORTED_PROVIDERS = ("rule_based", "github_models", "openai")
METRIC_PATHS = {
    "headline_mom": ("headline", "mom"),
    "headline_yoy": ("headline", "yoy"),
    "core_mom": ("core", "mom"),
    "core_yoy": ("core", "yoy"),
}
PERCENT_TOKEN_RE = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*%p?")
MARKET_ASSET_TERMS = (
    "S&P 500",
    "나스닥",
    "주가",
    "미국 국채",
    "국채금리",
    "달러",
    "DXY",
    "비트코인",
    "BTC",
)
MARKET_MOVE_TERMS = (
    "상승",
    "하락",
    "급등",
    "급락",
    "강세",
    "약세",
    "반등",
    "매도세",
)
CONSENSUS_CLAIM_TERMS = (
    "예상 상회",
    "예상 하회",
    "예상치 상회",
    "예상치 하회",
    "예상보다 높",
    "예상보다 낮",
    "컨센서스 상회",
    "컨센서스 하회",
    "시장 예상보다 높",
    "시장 예상보다 낮",
)


class CpiAnalysisError(Exception):
    """Raised when deterministic analysis validation cannot continue."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    event_id: str
    canonical_path: str
    output_path: str
    canonical_exists: bool
    analysis_created: bool
    api_calls: int
    api_key_checked: bool
    requested_provider: str
    provider_name: str | None
    external_api_called: bool
    fallback_used: bool
    fallback_reason: str | None


def project_root() -> Path:
    return PROJECT_ROOT


def select_provider(cli_provider: str | None = None) -> str:
    selected = cli_provider or os.environ.get("ANALYSIS_PROVIDER") or "rule_based"
    if selected not in SUPPORTED_PROVIDERS:
        raise CpiAnalysisError(
            "UNKNOWN_ANALYSIS_PROVIDER",
            f"provider must be one of: {', '.join(SUPPORTED_PROVIDERS)}",
        )
    return selected


def _reject_parent_parts(path: PurePath, label: str) -> None:
    if any(part == ".." for part in path.parts):
        raise CpiAnalysisError("INVALID_PATH", f"{label}: parent directory is not allowed")


def _resolve_project_path(root: Path, value: str | None, default: Path, label: str) -> Path:
    requested = default if value is None else Path(value)
    _reject_parent_parts(requested, label)
    candidate = requested if requested.is_absolute() else root / requested
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise CpiAnalysisError("INVALID_PATH", f"{label}: path must stay inside the project") from exc
    return candidate_resolved


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json_bytes(path: Path, data: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CpiAnalysisError("INVALID_JSON", f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CpiAnalysisError("INVALID_JSON", f"{label}: JSON root must be an object")
    return payload


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CpiAnalysisError("FILE_READ_ERROR", f"{label}: could not read file") from exc
    return _read_json_bytes(path, data, label)


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", f"{field}: non-empty string required")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", f"{field}: Decimal-compatible value required")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", f"{field}: invalid Decimal value") from exc


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _decimal_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _surprise_display(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%p"


def _metric_from_canonical(canonical: dict[str, Any], metric_key: str) -> dict[str, Any]:
    section, cadence = METRIC_PATHS[metric_key]
    event = canonical.get("event")
    if not isinstance(event, dict):
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", "event: object required")
    group = event.get(section)
    if not isinstance(group, dict):
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", f"event.{section}: object required")
    metric = group.get(cadence)
    if not isinstance(metric, dict):
        raise CpiAnalysisError(
            "INVALID_CANONICAL_RELEASE",
            f"event.{section}.{cadence}: object required",
        )
    return metric


def _validate_metric(metric_key: str, metric: dict[str, Any]) -> None:
    prefix = f"metrics.{metric_key}"
    actual_raw = _decimal(metric.get("actual_as_released_raw"), f"{prefix}.actual_as_released_raw")
    _non_empty_string(metric.get("actual_as_released_display"), f"{prefix}.actual_as_released_display")
    _decimal(metric.get("previous_as_released_raw"), f"{prefix}.previous_as_released_raw")
    _non_empty_string(metric.get("previous_as_released_display"), f"{prefix}.previous_as_released_display")

    expected = _optional_decimal(metric.get("expected"), f"{prefix}.expected")
    surprise = metric.get("surprise")
    if expected is None:
        if surprise is not None:
            raise CpiAnalysisError(
                "CANONICAL_SURPRISE_MISMATCH",
                f"{prefix}.surprise must be null when expected is null",
            )
        return

    if not isinstance(surprise, dict):
        raise CpiAnalysisError(
            "CANONICAL_SURPRISE_MISMATCH",
            f"{prefix}.surprise must be an object when expected is present",
        )
    with localcontext() as context:
        context.prec = 34
        recalculated = actual_raw - expected
    stored_raw = _decimal(surprise.get("raw"), f"{prefix}.surprise.raw")
    if stored_raw != recalculated:
        raise CpiAnalysisError(
            "CANONICAL_SURPRISE_MISMATCH",
            f"{prefix}.surprise.raw does not match actual minus expected",
        )
    expected_direction = (
        "above_expected" if recalculated > 0 else "below_expected" if recalculated < 0 else "in_line"
    )
    if surprise.get("direction") != expected_direction:
        raise CpiAnalysisError(
            "CANONICAL_SURPRISE_MISMATCH",
            f"{prefix}.surprise.direction is inconsistent",
        )
    if surprise.get("display") != _surprise_display(recalculated):
        raise CpiAnalysisError(
            "CANONICAL_SURPRISE_MISMATCH",
            f"{prefix}.surprise.display is inconsistent",
        )


def validate_canonical_release(canonical: dict[str, Any], event_id: str) -> None:
    if canonical.get("schema_version") in (None, ""):
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", "schema_version is required")

    meta = canonical.get("meta")
    if not isinstance(meta, dict):
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", "meta: object required")
    expected_meta = {
        "event_id": event_id,
        "indicator_type": "CPI",
        "country": "US",
        "is_sample": False,
        "data_origin": "bls_release_capture",
        "data_status": "release_captured",
        "analysis_status": "pending",
    }
    for key, expected in expected_meta.items():
        if meta.get(key) != expected:
            raise CpiAnalysisError(
                "INVALID_CANONICAL_RELEASE",
                f"meta.{key} must be {expected!r}",
            )
    _non_empty_string(meta.get("reference_period"), "meta.reference_period")
    release_kst = _non_empty_string(meta.get("release_datetime_kst"), "meta.release_datetime_kst")
    try:
        parsed_kst = datetime.fromisoformat(release_kst.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CpiAnalysisError(
            "INVALID_CANONICAL_RELEASE",
            "meta.release_datetime_kst must be ISO 8601",
        ) from exc
    if parsed_kst.tzinfo is None:
        raise CpiAnalysisError(
            "INVALID_CANONICAL_RELEASE",
            "meta.release_datetime_kst must include a timezone offset",
        )

    source = canonical.get("source")
    if not isinstance(source, dict):
        raise CpiAnalysisError("INVALID_CANONICAL_RELEASE", "source: object required")
    _non_empty_string(source.get("release_capture_sha256"), "source.release_capture_sha256")

    for metric_key in METRIC_PATHS:
        _validate_metric(metric_key, _metric_from_canonical(canonical, metric_key))


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.replace(" ", "")
    if normalized and normalized not in values:
        values.append(normalized)


def build_facts(canonical: dict[str, Any]) -> dict[str, Any]:
    meta = canonical["meta"]
    facts_metrics: dict[str, Any] = {}
    percentage_tokens: list[str] = []
    percentage_point_tokens: list[str] = []
    expected_states: list[bool] = []

    for metric_key in METRIC_PATHS:
        metric = _metric_from_canonical(canonical, metric_key)
        actual = _decimal(metric["actual_as_released_raw"], f"metrics.{metric_key}.actual")
        previous = _decimal(metric["previous_as_released_raw"], f"metrics.{metric_key}.previous")
        expected = _optional_decimal(metric.get("expected"), f"metrics.{metric_key}.expected")
        with localcontext() as context:
            context.prec = 34
            change = actual - previous
        momentum = "accelerating" if change > 0 else "decelerating" if change < 0 else "unchanged"

        actual_display = str(metric["actual_as_released_display"])
        previous_display = str(metric["previous_as_released_display"])
        _append_unique(percentage_tokens, actual_display)
        _append_unique(percentage_tokens, previous_display)
        if expected is not None:
            _append_unique(percentage_tokens, f"{metric['expected']}%")
            _append_unique(percentage_tokens, f"{_decimal_plain(expected)}%")
        surprise = copy.deepcopy(metric.get("surprise"))
        if isinstance(surprise, dict) and isinstance(surprise.get("display"), str):
            _append_unique(percentage_point_tokens, surprise["display"])

        facts_metrics[metric_key] = {
            "actual": str(metric["actual_as_released_raw"]),
            "actual_display": actual_display,
            "previous": str(metric["previous_as_released_raw"]),
            "previous_display": previous_display,
            "expected": None if expected is None else str(metric["expected"]),
            "surprise": surprise,
            "change_from_previous_raw": _decimal_plain(change),
            "momentum_direction": momentum,
        }
        expected_states.append(expected is not None)

    return {
        "event_id": meta["event_id"],
        "reference_period": meta["reference_period"],
        "release_datetime_kst": meta["release_datetime_kst"],
        "metrics": facts_metrics,
        "consensus_available": all(expected_states),
        "allowed_percentage_tokens": percentage_tokens,
        "allowed_percentage_point_tokens": percentage_point_tokens,
    }


def _schema_error(path: str, message: str) -> None:
    raise CpiAnalysisError("ANALYSIS_SCHEMA_INVALID", f"{path}: {message}")


def validate_json_schema_subset(value: Any, schema: dict[str, Any], path: str = "analysis") -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            _schema_error(path, "object required")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                _schema_error(path, f"missing required key {key}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                _schema_error(path, f"additional properties are not allowed: {sorted(extras)}")
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                validate_json_schema_subset(item, child_schema, f"{path}.{key}")
    elif expected_type == "array":
        if not isinstance(value, list):
            _schema_error(path, "array required")
        if len(value) < schema.get("minItems", 0):
            _schema_error(path, "array has too few items")
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            _schema_error(path, "array has too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema_subset(item, item_schema, f"{path}[{index}]")
    elif expected_type == "string":
        if not isinstance(value, str):
            _schema_error(path, "string required")
        if not value.strip():
            _schema_error(path, "empty string is not allowed")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            _schema_error(path, "string is shorter than minLength")
    elif expected_type is not None:
        _schema_error(path, f"unsupported schema type {expected_type}")

    if "enum" in schema and value not in schema["enum"]:
        _schema_error(path, f"value is not in enum {schema['enum']}")


def _path_exists(facts: dict[str, Any], evidence_path: str) -> bool:
    if not evidence_path.startswith("facts."):
        return False
    current: Any = facts
    for part in evidence_path.split(".")[1:]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def validate_evidence_paths(analysis: dict[str, Any], facts: dict[str, Any]) -> None:
    evidence_lists = [analysis["policy_implication"]["evidence_paths"]]
    evidence_lists.extend(point["evidence_paths"] for point in analysis["key_points"])
    for paths in evidence_lists:
        if len(paths) != len(set(paths)):
            raise CpiAnalysisError(
                "INVALID_EVIDENCE_PATH",
                "duplicate paths are not allowed within one evidence_paths array",
            )
        for path in paths:
            if not _path_exists(facts, path):
                raise CpiAnalysisError(
                    "INVALID_EVIDENCE_PATH",
                    f"evidence path does not exist in facts: {path}",
                )


def _validated_text_fields(analysis: dict[str, Any]) -> list[str]:
    texts = [
        analysis["executive_summary"]["one_line"],
        analysis["executive_summary"]["detail"],
        analysis["inflation_interpretation"]["headline"],
        analysis["inflation_interpretation"]["core"],
        analysis["inflation_interpretation"]["momentum"],
        analysis["policy_implication"]["explanation"],
    ]
    for point in analysis["key_points"]:
        texts.extend((point["title"], point["detail"]))
    texts.extend(analysis["risks_and_caveats"])
    return texts


def validate_numeric_claims(analysis: dict[str, Any], facts: dict[str, Any]) -> None:
    allowed = set(facts["allowed_percentage_tokens"])
    allowed.update(facts["allowed_percentage_point_tokens"])
    for text in _validated_text_fields(analysis):
        for match in PERCENT_TOKEN_RE.finditer(text):
            token = match.group(0).replace(" ", "")
            if token not in allowed:
                raise CpiAnalysisError(
                    "UNSUPPORTED_NUMERIC_CLAIM",
                    f"percentage token is not present in facts: {token}",
                )


def validate_market_claims(analysis: dict[str, Any]) -> None:
    for text in _validated_text_fields(analysis):
        if any(asset in text for asset in MARKET_ASSET_TERMS) and any(
            movement in text for movement in MARKET_MOVE_TERMS
        ):
            raise CpiAnalysisError(
                "UNSUPPORTED_MARKET_CLAIM",
                "observed market movement is not supported by facts",
            )


def validate_consensus_claims(analysis: dict[str, Any], facts: dict[str, Any]) -> None:
    if facts["consensus_available"]:
        return
    for text in _validated_text_fields(analysis):
        if any(term in text for term in CONSENSUS_CLAIM_TERMS):
            raise CpiAnalysisError(
                "UNSUPPORTED_CONSENSUS_CLAIM",
                "consensus comparison is unavailable in facts",
            )
    if analysis["confidence"] == "high":
        raise CpiAnalysisError(
            "UNSUPPORTED_CONSENSUS_CLAIM",
            "confidence cannot be high when consensus is unavailable",
        )


def validate_analysis_output(
    analysis: dict[str, Any],
    schema: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, bool]:
    validate_json_schema_subset(analysis, schema)
    validate_evidence_paths(analysis, facts)
    validate_numeric_claims(analysis, facts)
    validate_market_claims(analysis)
    validate_consensus_claims(analysis, facts)
    return {
        "schema_valid": True,
        "evidence_paths_valid": True,
        "numeric_claims_valid": True,
        "unsupported_market_claims_absent": True,
        "consensus_claims_valid": True,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise CpiAnalysisError("ALREADY_ANALYZED", "analysis output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_json_bytes(payload).decode("utf-8"))
        try:
            os.link(temp_path, path)
        except FileExistsError as exc:
            raise CpiAnalysisError("ALREADY_ANALYZED", "analysis output already exists") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _provider_callable(provider_name: str) -> Callable[..., AnalysisProviderResult]:
    return {
        "rule_based": rule_based.generate_analysis,
        "github_models": github_models.generate_analysis,
        "openai": openai_responses.generate_analysis,
    }[provider_name]


def _normalize_provider_result(value: Any, requested_provider: str) -> AnalysisProviderResult:
    if isinstance(value, AnalysisProviderResult):
        return value
    if isinstance(value, openai_responses.OpenAIResponseResult):
        return AnalysisProviderResult(
            provider_name="openai",
            model_requested=value.model_requested,
            model_returned=value.model_returned,
            response_id=value.response_id,
            analysis=value.output,
            usage=value.usage,
            external_api_called=value.api_calls > 0,
            fallback_used=False,
            fallback_reason=None,
            api_calls=value.api_calls,
        )
    raise AnalysisProviderError(
        "INVALID_PROVIDER_RESULT",
        f"{requested_provider} returned an invalid provider result",
    )


def _fallback_to_rule_based(
    *,
    facts: dict[str, Any],
    schema: dict[str, Any],
    instructions: str,
    reason: str,
    external_api_called: bool,
    api_calls: int,
    model_requested: str | None,
) -> tuple[AnalysisProviderResult, dict[str, Any], dict[str, bool]]:
    fallback = rule_based.generate_analysis(
        facts=copy.deepcopy(facts),
        instructions=instructions,
        schema=schema,
    )
    analysis = copy.deepcopy(fallback.analysis)
    validation = validate_analysis_output(analysis, schema, facts)
    result = AnalysisProviderResult(
        provider_name="rule_based",
        model_requested=model_requested,
        model_returned=None,
        response_id=None,
        analysis=analysis,
        usage=zero_usage(),
        external_api_called=external_api_called,
        fallback_used=True,
        fallback_reason=reason,
        api_calls=api_calls,
    )
    return result, analysis, validation


def _run_selected_provider(
    *,
    requested_provider: str,
    facts: dict[str, Any],
    instructions: str,
    schema: dict[str, Any],
    allow_rule_fallback: bool,
    provider_call: Callable[..., Any] | None,
) -> tuple[AnalysisProviderResult, dict[str, Any], dict[str, bool]]:
    call = provider_call or _provider_callable(requested_provider)
    provider_result: AnalysisProviderResult | None = None
    try:
        raw_result = call(
            facts=copy.deepcopy(facts),
            instructions=instructions,
            schema=schema,
        )
        provider_result = _normalize_provider_result(raw_result, requested_provider)
        analysis = copy.deepcopy(provider_result.analysis)
        validation = validate_analysis_output(analysis, schema, facts)
        return provider_result, analysis, validation
    except openai_responses.OpenAIResponsesError as exc:
        error = AnalysisProviderError(
            exc.code,
            exc.message,
            external_api_called=exc.attempts > 0,
            api_calls=exc.attempts,
            model_requested=openai_responses.configured_model(),
        )
        if requested_provider != "rule_based" and allow_rule_fallback:
            return _fallback_to_rule_based(
                facts=facts,
                schema=schema,
                instructions=instructions,
                reason=error.code,
                external_api_called=error.external_api_called,
                api_calls=error.api_calls,
                model_requested=error.model_requested,
            )
        raise error from exc
    except AnalysisProviderError as exc:
        if requested_provider != "rule_based" and allow_rule_fallback:
            return _fallback_to_rule_based(
                facts=facts,
                schema=schema,
                instructions=instructions,
                reason=exc.code,
                external_api_called=exc.external_api_called,
                api_calls=exc.api_calls,
                model_requested=exc.model_requested,
            )
        raise
    except CpiAnalysisError as exc:
        if requested_provider != "rule_based" and allow_rule_fallback and provider_result is not None:
            return _fallback_to_rule_based(
                facts=facts,
                schema=schema,
                instructions=instructions,
                reason=exc.code,
                external_api_called=provider_result.external_api_called,
                api_calls=provider_result.api_calls,
                model_requested=provider_result.model_requested,
            )
        raise


def analyze_from_files(
    root: Path,
    event_id: str,
    *,
    input_path: str | None = None,
    output_path: str | None = None,
    provider_name: str | None = None,
    allow_rule_fallback: bool = True,
    provider_call: Callable[..., Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> AnalysisResult:
    root = root.resolve()
    requested_provider = select_provider(provider_name)
    default_input = Path("data") / "generated" / "cpi" / event_id / "canonical_release.json"
    default_output = Path("data") / "analysis" / "cpi" / event_id / f"{ANALYSIS_VERSION}.json"
    canonical_path = _resolve_project_path(root, input_path, default_input, "--input")
    analysis_path = _resolve_project_path(root, output_path, default_output, "--output")
    canonical_path_value = _relative_path(canonical_path, root)
    output_path_value = _relative_path(analysis_path, root)

    if not canonical_path.exists():
        return AnalysisResult(
            status="CANONICAL_RELEASE_NOT_FOUND",
            event_id=event_id,
            canonical_path=canonical_path_value,
            output_path=output_path_value,
            canonical_exists=False,
            analysis_created=False,
            api_calls=0,
            api_key_checked=False,
            requested_provider=requested_provider,
            provider_name=None,
            external_api_called=False,
            fallback_used=False,
            fallback_reason=None,
        )
    if analysis_path.exists():
        return AnalysisResult(
            status="ALREADY_ANALYZED",
            event_id=event_id,
            canonical_path=canonical_path_value,
            output_path=output_path_value,
            canonical_exists=True,
            analysis_created=False,
            api_calls=0,
            api_key_checked=False,
            requested_provider=requested_provider,
            provider_name=None,
            external_api_called=False,
            fallback_used=False,
            fallback_reason=None,
        )

    try:
        canonical_bytes = canonical_path.read_bytes()
    except OSError as exc:
        raise CpiAnalysisError("FILE_READ_ERROR", "canonical release could not be read") from exc
    canonical = _read_json_bytes(canonical_path, canonical_bytes, "canonical_release.json")
    validate_canonical_release(canonical, event_id)
    facts = build_facts(canonical)

    prompt_path = PROJECT_ROOT / "prompts" / "cpi_analysis_v1.md"
    schema_path = PROJECT_ROOT / "schemas" / "cpi_analysis_v1.schema.json"
    try:
        prompt_bytes = prompt_path.read_bytes()
        prompt = prompt_bytes.decode("utf-8")
        schema_bytes = schema_path.read_bytes()
    except (OSError, UnicodeDecodeError) as exc:
        raise CpiAnalysisError("FILE_READ_ERROR", "prompt or schema could not be read") from exc
    schema = _read_json_bytes(schema_path, schema_bytes, "cpi_analysis_v1.schema.json")

    provider_result, analysis, validation = _run_selected_provider(
        requested_provider=requested_provider,
        facts=facts,
        instructions=prompt,
        schema=schema,
        allow_rule_fallback=allow_rule_fallback,
        provider_call=provider_call,
    )

    now = now_fn() if now_fn is not None else datetime.now(timezone.utc)
    wrapper = {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "event_id": event_id,
        "indicator_type": "CPI",
        "generated_at_utc": _iso_utc(now),
        "input": {
            "canonical_path": canonical_path_value,
            "canonical_sha256": _sha256(canonical_bytes),
            "release_capture_sha256": canonical["source"]["release_capture_sha256"],
        },
        "provider": {
            "name": provider_result.provider_name,
            "requested_provider": requested_provider,
            "model_requested": provider_result.model_requested,
            "model_returned": provider_result.model_returned,
            "response_id": provider_result.response_id,
            "external_api_called": provider_result.external_api_called,
            "fallback_used": provider_result.fallback_used,
            "fallback_reason": provider_result.fallback_reason,
        },
        "versions": {
            "prompt": PROMPT_NAME,
            "prompt_sha256": _sha256(prompt_bytes),
            "schema": SCHEMA_NAME,
            "schema_sha256": _sha256(schema_bytes),
        },
        "facts": facts,
        "analysis": analysis,
        "usage": copy.deepcopy(provider_result.usage),
        "validation": validation,
    }
    _write_new_json(analysis_path, wrapper)

    return AnalysisResult(
        status="ANALYSIS_GENERATED",
        event_id=event_id,
        canonical_path=canonical_path_value,
        output_path=output_path_value,
        canonical_exists=True,
        analysis_created=True,
        api_calls=provider_result.api_calls,
        api_key_checked=requested_provider == "openai",
        requested_provider=requested_provider,
        provider_name=provider_result.provider_name,
        external_api_called=provider_result.external_api_called,
        fallback_used=provider_result.fallback_used,
        fallback_reason=provider_result.fallback_reason,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a validated CPI analysis JSON")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS)
    fallback_group = parser.add_mutually_exclusive_group()
    fallback_group.add_argument(
        "--allow-rule-fallback",
        dest="allow_rule_fallback",
        action="store_true",
        default=True,
    )
    fallback_group.add_argument(
        "--no-rule-fallback",
        dest="allow_rule_fallback",
        action="store_false",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = analyze_from_files(
            project_root(),
            args.event_id,
            input_path=args.input,
            output_path=args.output,
            provider_name=args.provider,
            allow_rule_fallback=args.allow_rule_fallback,
        )
    except CpiAnalysisError as exc:
        print(exc.code)
        print(f"error: {exc.message}")
        print("External API calls: 0")
        return 1
    except AnalysisProviderError as exc:
        print(exc.code)
        print(f"error: {exc.message}")
        print(f"External API calls: {exc.api_calls}")
        print(f"External API called: {str(exc.external_api_called).lower()}")
        return 1

    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"canonical_path: {result.canonical_path}")
    print(f"canonical_exists: {str(result.canonical_exists).lower()}")
    print(f"output: {result.output_path}")
    print(f"analysis_created: {str(result.analysis_created).lower()}")
    print(f"requested_provider: {result.requested_provider}")
    print(f"provider_used: {result.provider_name or 'none'}")
    print(f"fallback_used: {str(result.fallback_used).lower()}")
    print(f"fallback_reason: {result.fallback_reason or 'none'}")
    print(f"External API calls: {result.api_calls}")
    print(f"External API called: {str(result.external_api_called).lower()}")
    print(f"API key checked: {str(result.api_key_checked).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
