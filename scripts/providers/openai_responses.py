from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from scripts.providers.base import AnalysisProviderError, AnalysisProviderResult


RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
HTTP_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "AUTHENTICATION_FAILED",
    403: "PERMISSION_DENIED",
    404: "MODEL_OR_ENDPOINT_NOT_FOUND",
    429: "RATE_LIMITED",
    500: "TRANSIENT_API_ERROR",
    502: "TRANSIENT_API_ERROR",
    503: "TRANSIENT_API_ERROR",
    504: "TRANSIENT_API_ERROR",
}


class OpenAIResponsesError(Exception):
    """A safe, classified OpenAI Responses API failure."""

    def __init__(self, code: str, message: str, *, attempts: int = 0):
        self.code = code
        self.message = message
        self.attempts = attempts
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class OpenAIResponseResult:
    output: dict[str, Any]
    response_id: str
    model_requested: str
    model_returned: str
    usage: dict[str, int]
    api_calls: int


def configured_model() -> str:
    return os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL


def build_request_payload(
    *,
    model: str,
    instructions: str,
    facts: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": model,
        "store": False,
        "reasoning": {"effort": REASONING_EFFORT},
        "instructions": instructions,
        "input": json.dumps(facts, ensure_ascii=False, sort_keys=True),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cpi_analysis_v1",
                "strict": True,
                "schema": schema,
            }
        },
    }


def _sanitize(value: Any, api_key: str) -> str:
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return text[:500]


def _http_error_detail(error: urllib.error.HTTPError, api_key: str) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    detail = body or getattr(error, "reason", "") or f"HTTP {error.code}"
    return _sanitize(detail, api_key)


def _usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    def token_count(name: str) -> int:
        value = usage.get(name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return {
        "input_tokens": token_count("input_tokens"),
        "output_tokens": token_count("output_tokens"),
        "total_tokens": token_count("total_tokens"),
    }


def _extract_structured_output(
    response: dict[str, Any],
    *,
    model_requested: str,
    attempts: int,
) -> OpenAIResponseResult:
    if response.get("status") == "incomplete":
        raise OpenAIResponsesError(
            "INCOMPLETE_RESPONSE",
            "the model response is incomplete",
            attempts=attempts,
        )

    output = response.get("output")
    if not isinstance(output, list):
        raise OpenAIResponsesError(
            "STRUCTURED_OUTPUT_MISSING",
            "response output is missing",
            attempts=attempts,
        )

    refusals: list[str] = []
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                refusal = part.get("refusal")
                refusals.append(refusal if isinstance(refusal, str) else "model refusal")
            elif part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())

    if refusals:
        raise OpenAIResponsesError(
            "MODEL_REFUSAL",
            "the model refused the request",
            attempts=attempts,
        )
    if not texts:
        raise OpenAIResponsesError(
            "STRUCTURED_OUTPUT_MISSING",
            "no non-empty output_text was returned",
            attempts=attempts,
        )
    if len(set(texts)) != 1:
        raise OpenAIResponsesError(
            "STRUCTURED_OUTPUT_MISSING",
            "conflicting output_text values were returned",
            attempts=attempts,
        )

    try:
        parsed = json.loads(texts[0])
    except json.JSONDecodeError as exc:
        raise OpenAIResponsesError(
            "INVALID_API_RESPONSE",
            "output_text is not valid JSON",
            attempts=attempts,
        ) from exc
    if not isinstance(parsed, dict):
        raise OpenAIResponsesError(
            "INVALID_API_RESPONSE",
            "structured output must be a JSON object",
            attempts=attempts,
        )

    response_id = response.get("id")
    model_returned = response.get("model")
    if not isinstance(response_id, str) or not response_id:
        raise OpenAIResponsesError(
            "INVALID_API_RESPONSE",
            "response id is missing",
            attempts=attempts,
        )
    if not isinstance(model_returned, str) or not model_returned:
        raise OpenAIResponsesError(
            "INVALID_API_RESPONSE",
            "returned model is missing",
            attempts=attempts,
        )

    return OpenAIResponseResult(
        output=parsed,
        response_id=response_id,
        model_requested=model_requested,
        model_returned=model_returned,
        usage=_usage(response),
        api_calls=attempts,
    )


def generate_structured_analysis(
    *,
    facts: dict[str, Any],
    instructions: str,
    schema: dict[str, Any],
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout: float = 30.0,
) -> OpenAIResponseResult:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIResponsesError(
            "OPENAI_API_KEY_MISSING",
            "OPENAI_API_KEY environment variable is not set",
        )

    model = configured_model()
    payload = build_request_payload(
        model=model,
        instructions=instructions,
        facts=facts,
        schema=schema,
    )
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    open_url = opener or urllib.request.urlopen
    attempts = 0

    while attempts < 2:
        attempts += 1
        request = urllib.request.Request(
            RESPONSES_ENDPOINT,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            api_response = open_url(request, timeout=timeout)
            try:
                raw = api_response.read()
            finally:
                close = getattr(api_response, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as exc:
            code = HTTP_ERROR_CODES.get(exc.code, "HTTP_ERROR")
            detail = _http_error_detail(exc, api_key)
            if exc.code in RETRYABLE_HTTP_STATUS and attempts < 2:
                sleep_fn(1.0)
                continue
            raise OpenAIResponsesError(code, detail, attempts=attempts) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OpenAIResponsesError(
                "NETWORK_ERROR",
                _sanitize(getattr(exc, "reason", exc), api_key),
                attempts=attempts,
            ) from exc

        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIResponsesError(
                "INVALID_API_RESPONSE",
                "API response is not valid UTF-8 JSON",
                attempts=attempts,
            ) from exc
        if not isinstance(response, dict):
            raise OpenAIResponsesError(
                "INVALID_API_RESPONSE",
                "API response root must be an object",
                attempts=attempts,
            )
        return _extract_structured_output(
            response,
            model_requested=model,
            attempts=attempts,
        )

    raise OpenAIResponsesError(
        "TRANSIENT_API_ERROR",
        "maximum API attempts reached",
        attempts=attempts,
    )


def generate_analysis(
    *,
    facts: dict[str, Any],
    instructions: str,
    schema: dict[str, Any],
) -> AnalysisProviderResult:
    """Adapt the optional paid OpenAI provider to the common provider contract."""
    try:
        result = generate_structured_analysis(
            facts=facts,
            instructions=instructions,
            schema=schema,
        )
    except OpenAIResponsesError as exc:
        raise AnalysisProviderError(
            exc.code,
            exc.message,
            external_api_called=exc.attempts > 0,
            api_calls=exc.attempts,
            model_requested=configured_model(),
        ) from exc
    return AnalysisProviderResult(
        provider_name="openai",
        model_requested=result.model_requested,
        model_returned=result.model_returned,
        response_id=result.response_id,
        analysis=result.output,
        usage=result.usage,
        external_api_called=result.api_calls > 0,
        fallback_used=False,
        fallback_reason=None,
        api_calls=result.api_calls,
    )
