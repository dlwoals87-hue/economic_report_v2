"""Safe Trading Economics calendar transport and forecast normalization."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ORIGIN = "https://api.tradingeconomics.com"
HOST = "api.tradingeconomics.com"
CALENDAR_PATH = "/calendar/country/united%20states/indicator/Producer%20Prices"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1_000_000
METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?$")


class ProviderError(Exception):
    """A stable, secret-free provider status."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(status)


def _provider_error(status: str) -> None:
    raise ProviderError(status)


def _validate_provider_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.port is not None:
        _provider_error("PPI_CONSENSUS_PROVIDER_UNSAFE_ENDPOINT")


def _status_error(status: int) -> None:
    if status in (401, 403):
        _provider_error("PPI_CONSENSUS_PROVIDER_AUTH_ERROR")
    if status == 429:
        _provider_error("PPI_CONSENSUS_PROVIDER_RATE_LIMITED")
    if 500 <= status <= 599:
        _provider_error("PPI_CONSENSUS_PROVIDER_SERVER_ERROR")
    if status < 200 or status >= 300:
        _provider_error("PPI_CONSENSUS_PROVIDER_ERROR")


def _content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        return str(get_content_type()).lower()
    get = getattr(headers, "get", None)
    return str(get("Content-Type", "")).split(";", 1)[0].strip().lower() if callable(get) else ""


def _http_error(exc: HTTPError) -> None:
    _status_error(exc.code)


def fetch_calendar(
    api_key: str | None,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> list[dict[str, Any]]:
    """Fetch the fixed US PPI endpoint without exposing credentials.

    ``opener`` has the :func:`urllib.request.urlopen` call shape and exists for
    deterministic, network-free tests.
    """

    if not api_key or not api_key.strip():
        _provider_error("CONSENSUS_PROVIDER_KEY_MISSING")
    if timeout_seconds <= 0 or max_response_bytes <= 0:
        _provider_error("PPI_CONSENSUS_PROVIDER_ERROR")

    endpoint = f"{ORIGIN}{CALENDAR_PATH}?{urlencode({'c': api_key})}"
    _validate_provider_url(endpoint)
    request = Request(endpoint, headers={"Accept": "application/json"})
    open_request = opener or urlopen
    try:
        response = open_request(request, timeout=timeout_seconds)
    except HTTPError as exc:
        _http_error(exc)
    except (socket.timeout, TimeoutError):
        _provider_error("PPI_CONSENSUS_PROVIDER_TIMEOUT")
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            _provider_error("PPI_CONSENSUS_PROVIDER_TIMEOUT")
        _provider_error("PPI_CONSENSUS_PROVIDER_ERROR")
    except OSError:
        _provider_error("PPI_CONSENSUS_PROVIDER_ERROR")

    try:
        final_url = response.geturl() if hasattr(response, "geturl") else endpoint
        _validate_provider_url(final_url)
        status = response.getcode() if hasattr(response, "getcode") else getattr(response, "status", 200)
        _status_error(int(status))
        if _content_type(response) != "application/json":
            _provider_error("PPI_CONSENSUS_PROVIDER_INVALID_CONTENT_TYPE")
        body = response.read(max_response_bytes + 1)
        if len(body) > max_response_bytes:
            _provider_error("PPI_CONSENSUS_PROVIDER_RESPONSE_TOO_LARGE")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _provider_error("PPI_CONSENSUS_PROVIDER_INVALID_JSON")
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            _provider_error("PPI_CONSENSUS_PROVIDER_INVALID_JSON")
        return payload
    except ProviderError:
        raise
    except (OSError, ValueError, TypeError):
        _provider_error("PPI_CONSENSUS_PROVIDER_ERROR")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)) or value is None:
        _provider_error("PPI_CONSENSUS_INVALID_FORECAST")
    if isinstance(value, str):
        text = value.strip()
        if not text or not _NUMBER.fullmatch(text):
            _provider_error("PPI_CONSENSUS_INVALID_FORECAST")
        if text.endswith("%"):
            text = text[:-1].strip()
    elif isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        _provider_error("PPI_CONSENSUS_INVALID_FORECAST")
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        _provider_error("PPI_CONSENSUS_INVALID_FORECAST")
    if not decimal_value.is_finite():
        _provider_error("PPI_CONSENSUS_INVALID_FORECAST")
    return decimal_value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _has_value(row: dict[str, Any], field: str) -> bool:
    return field in row and row[field] is not None


def forecast_value(row: dict[str, Any]) -> str | None:
    """Return the permitted consensus value or raise a contract status."""

    has_forecast_value = _has_value(row, "ForecastValue")
    has_forecast = _has_value(row, "Forecast")
    if has_forecast_value:
        primary = _decimal(row["ForecastValue"])
        if has_forecast:
            fallback = _decimal(row["Forecast"])
            if primary != fallback:
                _provider_error("PPI_CONSENSUS_FORECAST_CONFLICT")
        return _decimal_text(primary)
    if has_forecast:
        return _decimal_text(_decimal(row["Forecast"]))
    if _has_value(row, "TEForecast") or _has_value(row, "TEForecastValue"):
        _provider_error("PPI_CONSENSUS_PROHIBITED_TEFORECAST")
    # Actual and Previous are intentionally ignored rather than substituted.
    return None


def normalize(
    rows: list[dict[str, Any]],
    *,
    event_id: str,
    reference_period: str,
    release_datetime_utc: str,
    retrieved_at_utc: str,
) -> dict[str, Any]:
    """Normalize permitted forecast values into the immutable provider shape."""

    values: dict[str, dict[str, str]] = {}
    for row in rows:
        metric = row.get("Metric")
        if (
            row.get("Country") != "United States"
            or row.get("Unit") != "%"
            or metric not in METRICS
            or row.get("ReferencePeriod") != reference_period
            or row.get("ReleaseDate") != release_datetime_utc
        ):
            continue
        if metric in values:
            _provider_error("PPI_CONSENSUS_AMBIGUOUS")
        value = forecast_value(row)
        if value is not None:
            values[metric] = {"expected": value}

    status = "complete" if len(values) == len(METRICS) else "partial" if values else "unavailable"
    raw_payload_sha256 = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event_id,
        "provider": "trading_economics",
        "provider_data_type": "market_consensus",
        "retrieved_at_utc": retrieved_at_utc,
        "release_datetime_utc": release_datetime_utc,
        "reference_period": reference_period,
        "status": status,
        "metrics": values,
        "source_fields": {
            "primary": "ForecastValue",
            "fallback": "Forecast",
            "prohibited": ["TEForecast", "TEForecastValue", "Actual", "Previous"],
        },
        "provider_event_ids": {},
        "raw_payload_sha256": raw_payload_sha256,
        "integrity": {"sha256": None},
    }
    integrity_payload = {**result, "integrity": {}}
    result["integrity"]["sha256"] = hashlib.sha256(
        json.dumps(integrity_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return result
