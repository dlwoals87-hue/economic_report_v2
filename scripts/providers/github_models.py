from __future__ import annotations

import json
import os
from typing import Any, Callable

from scripts.providers.base import AnalysisProviderError, AnalysisProviderResult, zero_usage


TOKEN_ENV = "GITHUB_TOKEN"
MODEL_ENV = "GITHUB_MODELS_MODEL"
ENDPOINT_ENV = "GITHUB_MODELS_ENDPOINT"


def configured_model() -> str | None:
    return os.environ.get(MODEL_ENV) or None


def configured_endpoint() -> str | None:
    return os.environ.get(ENDPOINT_ENV) or None


def build_request_payload(
    *,
    model: str,
    facts: dict[str, Any],
    instructions: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": model,
        "store": False,
        "messages": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(facts, ensure_ascii=False, sort_keys=True),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cpi_analysis_v1",
                "strict": True,
                "schema": schema,
            },
        },
    }


def _token_count(usage: dict[str, Any], *names: str) -> int:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def parse_response(response: dict[str, Any], *, model_requested: str) -> AnalysisProviderResult:
    if not isinstance(response, dict):
        raise AnalysisProviderError(
            "INVALID_API_RESPONSE",
            "GitHub Models response root must be an object",
            external_api_called=True,
            api_calls=1,
            model_requested=model_requested,
        )
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise AnalysisProviderError(
            "STRUCTURED_OUTPUT_MISSING",
            "GitHub Models response must contain one choice",
            external_api_called=True,
            api_calls=1,
            model_requested=model_requested,
        )
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        analysis = content
    elif isinstance(content, str) and content.strip():
        try:
            analysis = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AnalysisProviderError(
                "INVALID_API_RESPONSE",
                "GitHub Models content is not valid JSON",
                external_api_called=True,
                api_calls=1,
                model_requested=model_requested,
            ) from exc
    else:
        raise AnalysisProviderError(
            "STRUCTURED_OUTPUT_MISSING",
            "GitHub Models structured content is missing",
            external_api_called=True,
            api_calls=1,
            model_requested=model_requested,
        )
    if not isinstance(analysis, dict):
        raise AnalysisProviderError(
            "INVALID_API_RESPONSE",
            "GitHub Models structured content must be an object",
            external_api_called=True,
            api_calls=1,
            model_requested=model_requested,
        )

    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    returned_model = response.get("model")
    response_id = response.get("id")
    return AnalysisProviderResult(
        provider_name="github_models",
        model_requested=model_requested,
        model_returned=returned_model if isinstance(returned_model, str) else model_requested,
        response_id=response_id if isinstance(response_id, str) else None,
        analysis=analysis,
        usage={
            "input_tokens": _token_count(usage, "input_tokens", "prompt_tokens"),
            "output_tokens": _token_count(usage, "output_tokens", "completion_tokens"),
            "total_tokens": _token_count(usage, "total_tokens"),
        },
        external_api_called=True,
        fallback_used=False,
        fallback_reason=None,
        api_calls=1,
    )


def generate_analysis(
    *,
    facts: dict[str, Any],
    instructions: str,
    schema: dict[str, Any],
    transport: Callable[..., dict[str, Any]] | None = None,
) -> AnalysisProviderResult:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise AnalysisProviderError(
            "GITHUB_MODELS_TOKEN_MISSING",
            f"{TOKEN_ENV} environment variable is not set",
        )
    model = configured_model()
    endpoint = configured_endpoint()
    if not model:
        raise AnalysisProviderError(
            "GITHUB_MODELS_MODEL_MISSING",
            f"{MODEL_ENV} environment variable is not set",
        )
    if not endpoint:
        raise AnalysisProviderError(
            "GITHUB_MODELS_ENDPOINT_MISSING",
            f"{ENDPOINT_ENV} environment variable is not set",
            model_requested=model,
        )
    if transport is None:
        raise AnalysisProviderError(
            "GITHUB_MODELS_NOT_CONNECTED",
            "GitHub Models transport is disabled in this stage",
            model_requested=model,
        )

    payload = build_request_payload(
        model=model,
        facts=facts,
        instructions=instructions,
        schema=schema,
    )
    try:
        response = transport(
            endpoint=endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
    except AnalysisProviderError as exc:
        raise AnalysisProviderError(
            exc.code,
            exc.message.replace(token, "[REDACTED]")[:500],
            external_api_called=True,
            api_calls=max(1, exc.api_calls),
            model_requested=model,
        ) from exc
    except (OSError, TimeoutError) as exc:
        safe_message = str(exc).replace(token, "[REDACTED]")[:500]
        raise AnalysisProviderError(
            "NETWORK_ERROR",
            safe_message,
            external_api_called=True,
            api_calls=1,
            model_requested=model,
        ) from exc
    return parse_response(response, model_requested=model)
