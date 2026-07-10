from __future__ import annotations

from typing import Any

from scripts.providers.base import AnalysisProviderResult, zero_usage


METRIC_LABELS = {
    "headline_mom": "헤드라인 전월비",
    "headline_yoy": "헤드라인 전년비",
    "core_mom": "근원 전월비",
    "core_yoy": "근원 전년비",
}
METRIC_ORDER = tuple(METRIC_LABELS)
UNSUPPORTED_REASONS = {
    "market_reaction": "시장 가격 데이터가 입력에 없어 실제 반응을 판단할 수 없다.",
    "asset_prices": "자산 가격 데이터가 입력에 없어 가격 흐름을 판단할 수 없다.",
    "yield_curve": "수익률곡선 데이터가 입력에 없어 곡선 변화를 판단할 수 없다.",
    "positioning": "투자자 포지셔닝 데이터가 입력에 없어 수급 상태를 판단할 수 없다.",
    "liquidity": "유동성 데이터가 입력에 없어 금융 여건을 판단할 수 없다.",
    "component_breakdown": "CPI 세부 구성 항목이 입력에 없어 구성별 기여를 판단할 수 없다.",
    "historical_analogs": "역사적 비교 데이터가 입력에 없어 유사 사례를 제시할 수 없다.",
    "forecast_probabilities": "전망 확률 데이터가 입력에 없어 확률을 제시할 수 없다.",
}


def _direction_phrase(direction: str) -> str:
    return {
        "accelerating": "물가 상승 모멘텀이 강화됐다",
        "decelerating": "물가 상승 모멘텀이 둔화됐다",
        "unchanged": "직전 발표와 동일한 흐름을 보였다",
    }.get(direction, "방향을 판정할 수 없다")


def _comparison_phrase(metric: dict[str, Any]) -> str:
    direction = metric["momentum_direction"]
    if direction == "accelerating":
        return "보다 높아 물가 상승 모멘텀이 강화됐다"
    if direction == "decelerating":
        return "보다 낮아 물가 상승 모멘텀이 둔화됐다"
    return "와 같아 직전 발표와 동일한 흐름을 보였다"


def _surprise_phrase(metric: dict[str, Any], consensus_available: bool) -> str:
    if not consensus_available:
        return ""
    surprise = metric.get("surprise")
    if not isinstance(surprise, dict):
        return ""
    display = surprise.get("display")
    direction = surprise.get("direction")
    if not isinstance(display, str):
        return ""
    translated = {
        "above_expected": "상회 방향",
        "below_expected": "하회 방향",
        "in_line": "부합 방향",
    }.get(direction, "판정 불가")
    return f" 예상치 대비 차이는 {display}로 {translated}이다."


def _key_point(metric_key: str, facts: dict[str, Any]) -> dict[str, Any]:
    metric = facts["metrics"][metric_key]
    label = METRIC_LABELS[metric_key]
    detail = (
        f"{label} 실제 상승률은 {metric['actual_display']}로 직전 발표 "
        f"{metric['previous_display']}{_comparison_phrase(metric)}."
        f"{_surprise_phrase(metric, facts['consensus_available'])}"
    )
    evidence_paths = [
        f"facts.metrics.{metric_key}.actual_display",
        f"facts.metrics.{metric_key}.previous_display",
        f"facts.metrics.{metric_key}.momentum_direction",
    ]
    if facts["consensus_available"] and isinstance(metric.get("surprise"), dict):
        evidence_paths.extend(
            (
                f"facts.metrics.{metric_key}.surprise.display",
                f"facts.metrics.{metric_key}.surprise.direction",
            )
        )
    return {
        "title": f"{label} 흐름",
        "detail": detail,
        "evidence_paths": evidence_paths,
    }


def _group_interpretation(facts: dict[str, Any], metric_keys: tuple[str, str], label: str) -> str:
    directions = [facts["metrics"][key]["momentum_direction"] for key in metric_keys]
    if all(direction == "accelerating" for direction in directions):
        return f"{label} 전월비와 전년비 모두 직전 발표보다 물가 상승 모멘텀이 강화됐다."
    if all(direction == "decelerating" for direction in directions):
        return f"{label} 전월비와 전년비 모두 직전 발표보다 물가 상승 모멘텀이 둔화됐다."
    if all(direction == "unchanged" for direction in directions):
        return f"{label} 전월비와 전년비 모두 직전 발표와 동일한 흐름이다."
    return f"{label} 전월비와 전년비의 직전 발표 대비 방향이 혼재돼 있다."


def policy_signal(facts: dict[str, Any]) -> str:
    try:
        directions = [facts["metrics"][key]["momentum_direction"] for key in METRIC_ORDER]
    except (KeyError, TypeError):
        return "indeterminate"
    if all(direction == "accelerating" for direction in directions):
        return "hawkish"
    if all(direction == "decelerating" for direction in directions):
        return "dovish"
    if directions.count("unchanged") >= 2:
        return "neutral"
    if any(direction == "accelerating" for direction in directions) or any(
        direction == "decelerating" for direction in directions
    ):
        return "mixed"
    return "indeterminate"


def generate_analysis(
    *,
    facts: dict[str, Any],
    instructions: str | None = None,
    schema: dict[str, Any] | None = None,
) -> AnalysisProviderResult:
    del instructions, schema
    signal = policy_signal(facts)
    signal_text = {
        "hawkish": "물가 모멘텀 강화 방향",
        "dovish": "물가 모멘텀 둔화 방향",
        "mixed": "물가 모멘텀 혼재 방향",
        "neutral": "물가 모멘텀 변화 제한 방향",
        "indeterminate": "물가 모멘텀 판정 불가",
    }[signal]
    confidence = "medium" if all(key in facts.get("metrics", {}) for key in METRIC_ORDER) else "low"

    analysis = {
        "language": "ko",
        "executive_summary": {
            "one_line": f"CPI 지표는 직전 발표 대비 {signal_text}을 나타냈다.",
            "detail": (
                "이 평가는 입력된 최초 발표값과 직전 발표값의 방향만 기계적으로 비교한 결과다. "
                "시장 반응이나 입력에 없는 세부 항목은 판단에 포함하지 않았다."
            ),
        },
        "inflation_interpretation": {
            "headline": _group_interpretation(
                facts,
                ("headline_mom", "headline_yoy"),
                "헤드라인 물가",
            ),
            "core": _group_interpretation(facts, ("core_mom", "core_yoy"), "근원 물가"),
            "momentum": "직전 발표 대비 네 지표의 결정적 방향을 종합한 기계적 해석이다.",
        },
        "policy_implication": {
            "signal": signal,
            "explanation": (
                f"정책 신호는 {signal_text}으로 분류됐다. 이는 CPI 모멘텀 방향만 사용하는 "
                "기계적 해석이며 실제 정책 결정을 예측하지 않는다."
            ),
            "evidence_paths": [
                f"facts.metrics.{key}.momentum_direction" for key in METRIC_ORDER
            ],
        },
        "key_points": [_key_point(key, facts) for key in METRIC_ORDER],
        "risks_and_caveats": [
            "이 결과는 입력된 CPI 최초 발표값만 사용한 규칙 기반 해석이다.",
            "정책 신호는 기계적 분류이며 투자 판단이나 정책 예측으로 사용할 수 없다.",
        ],
        "unsupported_sections": [
            {"section": section, "reason": reason}
            for section, reason in UNSUPPORTED_REASONS.items()
        ],
        "confidence": confidence,
    }
    return AnalysisProviderResult(
        provider_name="rule_based",
        model_requested=None,
        model_returned=None,
        response_id=None,
        analysis=analysis,
        usage=zero_usage(),
        external_api_called=False,
        fallback_used=False,
        fallback_reason=None,
        api_calls=0,
    )
