from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ZERO_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}


class AnalysisProviderError(Exception):
    """A provider-independent, safely classified analysis failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        external_api_called: bool = False,
        api_calls: int = 0,
        model_requested: str | None = None,
    ):
        self.code = code
        self.message = message
        self.external_api_called = external_api_called
        self.api_calls = api_calls
        self.model_requested = model_requested
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class AnalysisProviderResult:
    provider_name: str
    model_requested: str | None
    model_returned: str | None
    response_id: str | None
    analysis: dict[str, Any]
    usage: dict[str, int]
    external_api_called: bool
    fallback_used: bool = False
    fallback_reason: str | None = None
    api_calls: int = 0


def zero_usage() -> dict[str, int]:
    return dict(ZERO_USAGE)
