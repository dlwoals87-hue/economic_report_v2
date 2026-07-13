"""Fixture-safe collector for the official BLS Employment Situation series."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

SERIES = {
    "payroll": "CES0000000001",
    "unemployment": "LNS14000000",
    "ahe": "CES0500000003",
}
METRICS = (
    "nonfarm_payroll_change_k",
    "unemployment_rate",
    "average_hourly_earnings_mom",
)
BLS_SOURCE_IDENTIFIER = "BLS Public Data API v2"

# This is an intentionally exact allowlist, not a title-substring matcher.
OFFICIAL_SERIES_CONTRACT = {
    SERIES["payroll"]: {
        "role": "payroll_level",
        "official_title": "All employees, thousands, total nonfarm, seasonally adjusted",
        "seasonality": "Seasonally Adjusted",
        "frequency": "monthly",
        "source_level_unit": "thousand persons",
        "measure_data_type": "ALL EMPLOYEES, THOUSANDS",
        "derived_metric": "nonfarm_payroll_change_k",
        "derived_unit": "thousand persons",
    },
    SERIES["unemployment"]: {
        "role": "unemployment_rate",
        "official_title": "(Seas) Unemployment Rate",
        "seasonality": "Seasonally Adjusted",
        "frequency": "monthly",
        "source_level_unit": "percent",
        "measure_data_type": "Percent or rate",
        "derived_metric": "unemployment_rate",
        "derived_unit": "percent",
    },
    SERIES["ahe"]: {
        "role": "average_hourly_earnings_level",
        "official_title": "Average hourly earnings of all employees, total private, seasonally adjusted",
        "seasonality": "Seasonally Adjusted",
        "frequency": "monthly",
        "source_level_unit": "USD per hour",
        "measure_data_type": "AVERAGE HOURLY EARNINGS OF ALL EMPLOYEES",
        "derived_metric": "average_hourly_earnings_mom",
        "derived_unit": "percent",
    },
}
REFERENCE_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SENSITIVE_HASH_KEYS = {"api_key", "apikey", "authorization", "token", "endpoint", "url"}


class ResponseError(Exception):
    """A validated response failure that maps to a public result status."""

    def __init__(self, status: str, reason: str | None = None) -> None:
        self.status = status
        self.reason = reason
        super().__init__(status)


def month(year: Any, period: Any) -> str:
    if not isinstance(year, str) or not isinstance(period, str):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")
    return f"{year}-{period[1:]}"


def previous_month(reference_period: str) -> str:
    if not REFERENCE_PERIOD_RE.fullmatch(reference_period):
        raise ResponseError("NFP_BLS_REFERENCE_MISMATCH")
    year, value = map(int, reference_period.split("-"))
    return f"{year - 1}-12" if value == 1 else f"{year}-{value - 1:02d}"


def dec(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        raise ResponseError("NFP_BLS_INVALID_VALUE")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ResponseError("NFP_BLS_INVALID_VALUE") from exc
    if not number.is_finite():
        raise ResponseError("NFP_BLS_INVALID_VALUE")
    return number


def text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _hashable_response(value: Any) -> Any:
    """Exclude request credentials and endpoints from the raw-response digest input."""
    if isinstance(value, dict):
        return {
            key: _hashable_response(item)
            for key, item in value.items()
            if isinstance(key, str) and key.lower().replace("-", "_") not in SENSITIVE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_hashable_response(item) for item in value]
    return value


def response_sha(payload: Any) -> str | None:
    try:
        return stable_sha(_hashable_response(payload))
    except (TypeError, ValueError):
        return None


def _metadata(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("catalog", "metadata"):
        value = row.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ResponseError("NFP_BLS_INVALID_RESPONSE")
            return value
    return None


def _catalog_value(metadata: dict[str, Any], name: str) -> Any:
    aliases = {
        "official_title": ("official_title", "title", "series_title"),
        "seasonality": ("seasonality", "seasonal", "seasonal_adjustment"),
        "frequency": ("frequency", "periodicity"),
        "source_level_unit": ("source_level_unit", "unit", "unit_of_measure"),
        "measure_data_type": ("measure_data_type", "data_type"),
    }
    for key in aliases[name]:
        if key in metadata:
            return metadata[key]
    return None


def _verify_catalog(series_id: str, metadata: dict[str, Any]) -> None:
    contract = OFFICIAL_SERIES_CONTRACT[series_id]
    for name in (
        "official_title",
        "seasonality",
        "frequency",
        "source_level_unit",
        "measure_data_type",
    ):
        actual = _catalog_value(metadata, name)
        expected = contract[name]
        if not isinstance(actual, str) or actual != expected:
            raise ResponseError("NFP_SERIES_CONTRACT_UNVERIFIED")


def _series_rows(payload: Any) -> tuple[dict[str, dict[str, Any]], bool, list[str]]:
    if not isinstance(payload, dict):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")
    results = payload.get("Results")
    if not isinstance(results, dict) or not isinstance(results.get("series"), list):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")

    expected_rows: dict[str, dict[str, Any]] = {}
    extra_ids: list[str] = []
    any_catalog = False
    for row in results["series"]:
        if not isinstance(row, dict) or not isinstance(row.get("seriesID"), str):
            raise ResponseError("NFP_BLS_INVALID_RESPONSE")
        series_id = row["seriesID"]
        if series_id not in OFFICIAL_SERIES_CONTRACT:
            extra_ids.append(series_id)
            continue
        if series_id in expected_rows:
            raise ResponseError("NFP_BLS_DUPLICATE_SERIES")
        expected_rows[series_id] = row
        any_catalog = any_catalog or _metadata(row) is not None

    missing = set(OFFICIAL_SERIES_CONTRACT) - set(expected_rows)
    if missing:
        if expected_rows:
            raise ResponseError("NFP_BLS_PARTIAL", "NFP_BLS_SERIES_MISSING")
        raise ResponseError("NFP_BLS_SERIES_MISSING")
    if any_catalog:
        for series_id, row in expected_rows.items():
            metadata = _metadata(row)
            if metadata is None:
                raise ResponseError("NFP_SERIES_CONTRACT_UNVERIFIED")
            _verify_catalog(series_id, metadata)
    return expected_rows, any_catalog, sorted(extra_ids)


def _validate_provider_response(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")
    status = payload.get("status")
    if status is not None:
        if not isinstance(status, str):
            raise ResponseError("NFP_BLS_INVALID_RESPONSE")
        if status != "REQUEST_SUCCEEDED":
            raise ResponseError("NFP_BLS_PROVIDER_ERROR")
    message = payload.get("message")
    if message:
        raise ResponseError("NFP_BLS_PROVIDER_ERROR")


def _records(row: dict[str, Any]) -> dict[str, Decimal]:
    data = row.get("data")
    if not isinstance(data, list):
        raise ResponseError("NFP_BLS_INVALID_RESPONSE")
    values: dict[str, Decimal] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ResponseError("NFP_BLS_INVALID_RESPONSE")
        key = month(item.get("year"), item.get("period"))
        if key in values:
            raise ResponseError("NFP_BLS_DUPLICATE_PERIOD")
        values[key] = dec(item.get("value"))
    return values


def _require_period(values: dict[str, Decimal], reference: str, previous: str | None = None) -> None:
    if reference in values:
        if previous is not None and previous not in values:
            older = [key for key in values if key < reference]
            if older:
                raise ResponseError("NFP_BLS_PERIOD_GAP")
            raise ResponseError("NFP_BLS_PARTIAL", "NFP_BLS_PERIOD_MISSING")
        return
    if values and max(values) < reference:
        raise ResponseError("NFP_BLS_STALE")
    if values and min(values) > reference:
        raise ResponseError("NFP_BLS_REFERENCE_MISMATCH")
    raise ResponseError("NFP_BLS_PARTIAL", "NFP_BLS_PERIOD_MISSING")


def _base_result(payload: Any, reference_period: str, retrieved_at_utc: str) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "indicator_type": "NFP",
        "country": "US",
        "reference_period": reference_period,
        "retrieved_at_utc": retrieved_at_utc,
        "source_provider": "bls",
        "source_type": "official_government_api",
        "source_identifier": BLS_SOURCE_IDENTIFIER,
        "data_origin": "historical_backfill",
        "vintage_status": "current_api_snapshot",
        "not_as_released": True,
        "metrics": {},
        "source_series": SERIES,
        "source_periods": {},
        "calculations": {},
        "metadata_validation": {
            "mode": "local_official_contract",
            "metadata_from_api_response": False,
            "official_contract": OFFICIAL_SERIES_CONTRACT,
        },
        "raw_response_sha256": response_sha(payload),
        "external_api_called": False,
        "external_ai_api_called": False,
        "cost": "free",
        "integrity": {"sha256": None},
    }


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    result["integrity"]["sha256"] = stable_sha({**result, "integrity": {}})
    return result


def integrity_matches(result: Any) -> bool:
    if not isinstance(result, dict) or not isinstance(result.get("integrity"), dict):
        return False
    actual = result["integrity"].get("sha256")
    if not isinstance(actual, str):
        return False
    try:
        return actual == stable_sha({**result, "integrity": {}})
    except (TypeError, ValueError):
        return False


def collect_from_response(
    payload: dict[str, Any], reference_period: str, retrieved_at_utc: str
) -> dict[str, Any]:
    """Normalize an injected BLS fixture; this function makes no HTTP request."""
    base = _base_result(payload, reference_period, retrieved_at_utc)
    try:
        previous = previous_month(reference_period)
        _validate_provider_response(payload)
        rows, has_catalog, extra_ids = _series_rows(payload)
        records = {series_id: _records(row) for series_id, row in rows.items()}
        payroll = records[SERIES["payroll"]]
        unemployment = records[SERIES["unemployment"]]
        ahe = records[SERIES["ahe"]]
        _require_period(payroll, reference_period, previous)
        _require_period(unemployment, reference_period)
        _require_period(ahe, reference_period, previous)
        if ahe[previous] <= Decimal(0):
            raise ResponseError("NFP_BLS_DIVIDE_BY_ZERO")

        payroll_change = payroll[reference_period] - payroll[previous]
        with localcontext() as context:
            context.prec = 28
            ahe_mom = (ahe[reference_period] / ahe[previous] - Decimal(1)) * Decimal(100)
        base["metrics"] = {
            "nonfarm_payroll_change_k": {
                "value": text(payroll_change),
                "unit": OFFICIAL_SERIES_CONTRACT[SERIES["payroll"]]["derived_unit"],
                "source_series_id": SERIES["payroll"],
                "source_period": reference_period,
                "previous_source_period": previous,
                "calculation_method": "current_minus_previous",
                "source_values": {
                    "current": text(payroll[reference_period]),
                    "previous": text(payroll[previous]),
                },
                "status": "available",
            },
            "unemployment_rate": {
                "value": text(unemployment[reference_period]),
                "unit": OFFICIAL_SERIES_CONTRACT[SERIES["unemployment"]]["derived_unit"],
                "source_series_id": SERIES["unemployment"],
                "source_period": reference_period,
                "calculation_method": "official_series_value",
                "source_values": {"current": text(unemployment[reference_period])},
                "status": "available",
            },
            "average_hourly_earnings_mom": {
                "value": text(ahe_mom),
                "unit": OFFICIAL_SERIES_CONTRACT[SERIES["ahe"]]["derived_unit"],
                "source_series_id": SERIES["ahe"],
                "source_period": reference_period,
                "previous_source_period": previous,
                "calculation_method": "((current/previous)-1)*100",
                "rounding": "Decimal precision 28; no additional rounding",
                "source_values": {
                    "current": text(ahe[reference_period]),
                    "previous": text(ahe[previous]),
                },
                "status": "available",
            },
        }
        base["status"] = "NFP_BLS_COLLECTED"
        base["source_periods"] = {
            "nonfarm_payroll_change_k": {"current": reference_period, "previous": previous},
            "unemployment_rate": {"current": reference_period},
            "average_hourly_earnings_mom": {"current": reference_period, "previous": previous},
        }
        base["calculations"] = {
            "payroll_previous_period": previous,
            "ahe_previous_period": previous,
        }
        base["metadata_validation"] = {
            "mode": "api_catalog_verified" if has_catalog else "local_official_contract",
            "metadata_from_api_response": has_catalog,
            "official_contract": OFFICIAL_SERIES_CONTRACT,
            "ignored_extra_series_ids": extra_ids,
        }
    except ResponseError as exc:
        base["status"] = exc.status
        if exc.reason:
            base["incomplete_reason"] = exc.reason
    except (DivisionByZero, InvalidOperation):
        base["status"] = "NFP_BLS_DIVIDE_BY_ZERO"
    return _finish(base)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-period", required=True)
    parser.add_argument("--fixture-json", required=True)
    parser.add_argument(
        "--retrieved-at-utc",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.fixture_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    result = collect_from_response(payload, args.reference_period, args.retrieved_at_utc)
    Path(args.result_json).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
