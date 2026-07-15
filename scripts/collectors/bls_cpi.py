from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

SOURCE_SERIES = {
    "headline_mom": "CUSR0000SA0",
    "headline_yoy": "CUUR0000SA0",
    "core_mom": "CUSR0000SA0L1E",
    "core_yoy": "CUUR0000SA0L1E",
}

METRIC_DEFINITIONS = {
    "headline_mom": {
        "series_id": "CUSR0000SA0",
        "months_back": 1,
        "seasonal_adjustment": "seasonally_adjusted",
        "formula": "(current_sa_index / previous_month_sa_index - 1) * 100",
    },
    "headline_yoy": {
        "series_id": "CUUR0000SA0",
        "months_back": 12,
        "seasonal_adjustment": "not_seasonally_adjusted",
        "formula": "(current_nsa_index / same_month_prior_year_nsa_index - 1) * 100",
    },
    "core_mom": {
        "series_id": "CUSR0000SA0L1E",
        "months_back": 1,
        "seasonal_adjustment": "seasonally_adjusted",
        "formula": "(current_sa_index / previous_month_sa_index - 1) * 100",
    },
    "core_yoy": {
        "series_id": "CUUR0000SA0L1E",
        "months_back": 12,
        "seasonal_adjustment": "not_seasonally_adjusted",
        "formula": "(current_nsa_index / same_month_prior_year_nsa_index - 1) * 100",
    },
}


class BlsCpiError(Exception):
    """Base error for this collector."""


class HttpRequestError(BlsCpiError):
    """Raised when the BLS HTTP request fails."""


class JsonResponseError(BlsCpiError):
    """Raised when the BLS response is not valid JSON."""


class DataValidationError(BlsCpiError):
    """Raised when the BLS response fails local validation."""


@dataclass(frozen=True)
class Observation:
    year: int
    month: int
    period: str
    value: Decimal


@dataclass(frozen=True)
class FetchResult:
    response: dict[str, Any]
    first_request_mode: str
    registration_key_rejected: bool
    fallback_used: bool
    final_request_mode: str
    request_mode: str
    registration_key_used: bool
    request_count: int


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compact_utc_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def kst_iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_percent_display(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%"


def percent_change(current: Decimal, comparison: Decimal) -> Decimal:
    if comparison == 0:
        raise DataValidationError("Comparison index is zero.")
    with localcontext() as context:
        context.prec = 34
        return (current / comparison - Decimal("1")) * Decimal("100")


def parse_period(year_text: str, period_text: str) -> tuple[int, int] | None:
    if not period_text.startswith("M"):
        return None
    try:
        month = int(period_text[1:])
        year = int(year_text)
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def period_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def shift_month(period: str, months_back: int) -> str:
    year_text, month_text = period.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    absolute = year * 12 + (month - 1) - months_back
    shifted_year = absolute // 12
    shifted_month = absolute % 12 + 1
    return period_key(shifted_year, shifted_month)


def request_year_range(now: datetime) -> tuple[str, str]:
    current_year = now.astimezone(timezone.utc).year
    return str(current_year - 2), str(current_year)


def sanitize_secret_text(text: str, secret: str | None) -> str:
    if secret:
        return text.replace(secret, "[REDACTED]")
    return text


def bls_message_text(message: Any, api_key: str | None) -> str:
    if isinstance(message, list):
        text = "; ".join(str(item) for item in message)
    elif message is None:
        text = ""
    else:
        text = str(message)
    return sanitize_secret_text(text, api_key)


def is_registration_key_rejected(response: dict[str, Any], api_key: str | None = None) -> bool:
    if response.get("status") != "REQUEST_NOT_PROCESSED":
        return False
    message = bls_message_text(response.get("message"), api_key).lower()
    return ("invalid" in message and "key" in message) or "proper key" in message


def build_request_payload(
    request_now: datetime,
    api_key: str | None = None,
    registered: bool = False,
    series_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    startyear, endyear = request_year_range(request_now)
    payload = {
        "seriesid": list(SOURCE_SERIES.values()) if series_ids is None else list(series_ids),
        "startyear": startyear,
        "endyear": endyear,
    }
    if registered:
        if not api_key:
            raise DataValidationError("Registered BLS request mode requires BLS_API_KEY.")
        payload["registrationKey"] = api_key
    return payload


def post_bls_payload(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        BLS_API_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise HttpRequestError(f"HTTP error from BLS API: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise HttpRequestError(f"Network error from BLS API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HttpRequestError("Network timeout from BLS API.") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise JsonResponseError(f"BLS API returned invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise JsonResponseError("BLS API JSON root is not an object.")
    return parsed


def fetch_bls_response(
    api_key: str | None,
    now: datetime | None = None,
    logger: Callable[[str], None] | None = print,
    series_ids: list[str] | tuple[str, ...] | None = None,
) -> FetchResult:
    request_now = now or utc_now()
    request_count = 0

    if api_key:
        if logger:
            logger("BLS request mode: registered")
        registered_payload = build_request_payload(request_now, api_key=api_key, registered=True, series_ids=series_ids)
        registered_response = post_bls_payload(registered_payload)
        request_count += 1
        if is_registration_key_rejected(registered_response, api_key):
            if logger:
                logger("Registered key rejected; retrying in unregistered mode")
                logger("BLS request mode: unregistered")
            unregistered_payload = build_request_payload(request_now, registered=False, series_ids=series_ids)
            unregistered_response = post_bls_payload(unregistered_payload)
            request_count += 1
            return FetchResult(
                response=unregistered_response,
                first_request_mode="registered",
                registration_key_rejected=True,
                fallback_used=True,
                final_request_mode="unregistered",
                request_mode="unregistered_fallback",
                registration_key_used=False,
                request_count=request_count,
            )
        return FetchResult(
            response=registered_response,
            first_request_mode="registered",
            registration_key_rejected=False,
            fallback_used=False,
            final_request_mode="registered",
            request_mode="registered",
            registration_key_used=True,
            request_count=request_count,
        )

    if logger:
        logger("BLS request mode: unregistered")
    unregistered_payload = build_request_payload(request_now, registered=False, series_ids=series_ids)
    unregistered_response = post_bls_payload(unregistered_payload)
    request_count += 1
    return FetchResult(
        response=unregistered_response,
        first_request_mode="unregistered",
        registration_key_rejected=False,
        fallback_used=False,
        final_request_mode="unregistered",
        request_mode="unregistered",
        registration_key_used=False,
        request_count=request_count,
    )


def validate_bls_status(response: dict[str, Any], api_key: str | None = None) -> None:
    status = response.get("status")
    if status != "REQUEST_SUCCEEDED":
        message = bls_message_text(response.get("message"), api_key)
        raise DataValidationError(
            f"BLS API status: {status!r}; message: {message}"
        )


def extract_series_list(response: dict[str, Any], api_key: str | None = None) -> list[dict[str, Any]]:
    validate_bls_status(response, api_key)
    results = response.get("Results")
    if not isinstance(results, dict):
        raise DataValidationError("BLS response missing Results object.")
    series_list = results.get("series")
    if not isinstance(series_list, list):
        raise DataValidationError("BLS response missing Results.series list.")
    return series_list


def parse_bls_response(
    response: dict[str, Any],
    requested_series: list[str] | None = None,
    api_key: str | None = None,
) -> tuple[dict[str, dict[str, Observation]], dict[str, Any]]:
    requested = requested_series or list(SOURCE_SERIES.values())
    series_list = extract_series_list(response, api_key)
    seen: set[str] = set()
    duplicates: list[str] = []
    parsed: dict[str, dict[str, Observation]] = {}
    m13_count = 0
    non_numeric_observation_count = 0

    for series in series_list:
        if not isinstance(series, dict):
            raise DataValidationError("BLS series item is not an object.")
        series_id = series.get("seriesID")
        if not isinstance(series_id, str):
            raise DataValidationError("BLS series item missing seriesID.")
        if series_id in seen:
            duplicates.append(series_id)
        seen.add(series_id)

        data = series.get("data")
        if not isinstance(data, list):
            raise DataValidationError(f"Series {series_id} missing data list.")

        observations: dict[str, Observation] = {}
        for item in data:
            if not isinstance(item, dict):
                raise DataValidationError(f"Series {series_id} has non-object observation.")
            period = item.get("period")
            year = item.get("year")
            if period == "M13":
                m13_count += 1
                continue
            if not isinstance(period, str) or not isinstance(year, str):
                continue
            parsed_period = parse_period(year, period)
            if parsed_period is None:
                continue
            value_text = item.get("value")
            if not isinstance(value_text, str):
                raise DataValidationError(f"Series {series_id} has non-string value.")
            try:
                value = Decimal(value_text)
            except InvalidOperation:
                non_numeric_observation_count += 1
                continue
            key = period_key(*parsed_period)
            observations[key] = Observation(
                year=parsed_period[0],
                month=parsed_period[1],
                period=period,
                value=value,
            )

        if not observations:
            raise DataValidationError(f"Series {series_id} has no valid monthly observations.")
        parsed[series_id] = observations

    missing = [series_id for series_id in requested if series_id not in seen]
    unexpected = [series_id for series_id in seen if series_id not in requested]
    if duplicates:
        raise DataValidationError(f"Duplicate BLS series returned: {', '.join(sorted(duplicates))}")
    if missing:
        raise DataValidationError(f"Missing BLS series: {', '.join(missing)}")
    if unexpected:
        raise DataValidationError(f"Unexpected BLS series returned: {', '.join(sorted(unexpected))}")

    validation = {
        "requested_series_count": len(requested),
        "returned_series_count": len(series_list),
        "missing_series": missing,
        "duplicate_series": duplicates,
        "m13_excluded": True,
        "m13_observation_count": m13_count,
        "non_numeric_observation_count": non_numeric_observation_count,
    }
    return parsed, validation


def find_common_latest_period(series_data: dict[str, dict[str, Observation]]) -> str:
    common_periods: set[str] | None = None
    for observations in series_data.values():
        keys = set(observations.keys())
        common_periods = keys if common_periods is None else common_periods & keys
    if not common_periods:
        raise DataValidationError("No common reference period found across all CPI series.")
    return max(common_periods, key=lambda item: tuple(int(part) for part in item.split("-")))


def calculate_metric_period(
    observations: dict[str, Observation],
    metric_name: str,
    reference_period: str,
    months_back: int,
    period_label: str,
) -> dict[str, Any]:
    comparison_period = shift_month(reference_period, months_back)
    latest = observations.get(reference_period)
    comparison = observations.get(comparison_period)
    if latest is None:
        raise DataValidationError(
            f"{metric_name} missing {period_label} reference period {reference_period}."
        )
    if comparison is None:
        raise DataValidationError(
            f"{metric_name} missing {period_label} comparison period {comparison_period}."
        )
    raw = percent_change(latest.value, comparison.value)
    raw_text = decimal_to_plain(raw)
    return {
        "reference_period": reference_period,
        "latest_index": decimal_to_plain(latest.value),
        "comparison_period": comparison_period,
        "comparison_index": decimal_to_plain(comparison.value),
        "raw": raw_text,
        "display": format_percent_display(raw),
    }


def build_metrics(
    series_data: dict[str, dict[str, Observation]],
    reference_period: str,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    previous_reference_period = shift_month(reference_period, 1)
    for metric_name, definition in METRIC_DEFINITIONS.items():
        series_id = definition["series_id"]
        months_back = int(definition["months_back"])
        observations = series_data.get(series_id)
        if observations is None:
            raise DataValidationError(f"Series {series_id} is not available for {metric_name}.")
        current = calculate_metric_period(
            observations=observations,
            metric_name=metric_name,
            reference_period=reference_period,
            months_back=months_back,
            period_label="current",
        )
        previous = calculate_metric_period(
            observations=observations,
            metric_name=metric_name,
            reference_period=previous_reference_period,
            months_back=months_back,
            period_label="previous",
        )
        metrics[metric_name] = {
            "series_id": series_id,
            "reference_period": reference_period,
            "current_reference_period": reference_period,
            "previous_reference_period": previous_reference_period,
            "latest_index": current["latest_index"],
            "comparison_period": current["comparison_period"],
            "comparison_index": current["comparison_index"],
            "previous_latest_index": previous["latest_index"],
            "previous_comparison_period": previous["comparison_period"],
            "previous_comparison_index": previous["comparison_index"],
            "actual_as_released": None,
            "previous_as_released": None,
            "actual_current": current["raw"],
            "actual_current_raw": current["raw"],
            "actual_current_display": current["display"],
            "previous_current": previous["raw"],
            "previous_current_raw": previous["raw"],
            "previous_current_display": previous["display"],
            "as_released_status": "not_captured",
            "previous_as_released_status": "not_captured",
            "is_revised": None,
            "unit": "%",
            "seasonal_adjustment": str(definition["seasonal_adjustment"]),
            "calculation_formula": str(definition["formula"]),
        }
    return metrics


def safe_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def unique_snapshot_path(raw_dir: Path, retrieved_at: datetime) -> Path:
    base = raw_dir / f"retrieved_{compact_utc_timestamp(retrieved_at)}.json"
    if not base.exists():
        return base
    stem = base.stem
    for index in range(1, 100):
        candidate = raw_dir / f"{stem}_{index:02d}.json"
        if not candidate.exists():
            return candidate
    raise DataValidationError("Could not create a unique raw snapshot path.")


def write_json(path: Path, payload: dict[str, Any], overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_processed_payload(
    reference_period: str,
    retrieved_at: datetime,
    metrics: dict[str, dict[str, Any]],
    validation: dict[str, Any],
    raw_snapshot_path: Path,
    root: Path,
    request_mode: str,
    registration_key_used: bool,
) -> dict[str, Any]:
    processed_validation = dict(validation)
    processed_validation["common_reference_period_found"] = True
    return {
        "schema_version": "1.0",
        "indicator_type": "CPI",
        "provider": "BLS",
        "reference_period": reference_period,
        "previous_reference_period": shift_month(reference_period, 1),
        "retrieved_at_utc": iso_utc(retrieved_at),
        "retrieved_at_kst": kst_iso(retrieved_at),
        "request_mode": request_mode,
        "registration_key_used": registration_key_used,
        "source_series": SOURCE_SERIES,
        "metrics": metrics,
        "validation": processed_validation,
        "raw_snapshot_path": safe_relative_path(raw_snapshot_path, root),
    }


def collect_and_save(api_key: str | None, root: Path, now: datetime | None = None) -> dict[str, Any]:
    retrieved_at = now or utc_now()
    fetch_result = fetch_bls_response(api_key, retrieved_at)
    response = fetch_result.response
    series_data, validation = parse_bls_response(response, api_key=api_key)
    reference_period = find_common_latest_period(series_data)
    metrics = build_metrics(series_data, reference_period)

    raw_dir = root / "data" / "raw" / "bls" / "cpi" / reference_period
    raw_path = unique_snapshot_path(raw_dir, retrieved_at)
    raw_payload = {
        "retrieved_at_utc": iso_utc(retrieved_at),
        "provider": "U.S. Bureau of Labor Statistics",
        "api_version": "v2",
        "request_mode": fetch_result.request_mode,
        "registration_key_used": fetch_result.registration_key_used,
        "response": response,
    }
    write_json(raw_path, raw_payload, overwrite=False)

    processed_payload = build_processed_payload(
        reference_period=reference_period,
        retrieved_at=retrieved_at,
        metrics=metrics,
        validation=validation,
        raw_snapshot_path=raw_path,
        root=root,
        request_mode=fetch_result.request_mode,
        registration_key_used=fetch_result.registration_key_used,
    )
    processed_path = root / "data" / "processed" / "bls" / "cpi_latest.json"
    write_json(processed_path, processed_payload, overwrite=True)

    return {
        "reference_period": reference_period,
        "raw_snapshot_path": raw_path,
        "processed_path": processed_path,
        "processed_payload": processed_payload,
        "fetch_result": fetch_result,
    }


def main() -> int:
    api_key = os.environ.get("BLS_API_KEY")
    if not api_key:
        print("BLS_API_KEY detected: no", flush=True)
    else:
        print("BLS_API_KEY detected: yes", flush=True)

    root = project_root()
    try:
        result = collect_and_save(api_key=api_key, root=root)
    except BlsCpiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = result["processed_payload"]
    validation = payload["validation"]
    fetch_result = result["fetch_result"]
    print(f"First request mode: {fetch_result.first_request_mode}")
    print(f"Registered key rejected: {'yes' if fetch_result.registration_key_rejected else 'no'}")
    print(f"Fallback used: {'yes' if fetch_result.fallback_used else 'no'}")
    print(f"Final request mode: {fetch_result.final_request_mode}")
    print("API status: REQUEST_SUCCEEDED")
    print(f"Requested series: {validation['requested_series_count']}")
    print(f"Returned series: {validation['returned_series_count']}")
    print(f"Missing series: {validation['missing_series']}")
    print(f"Latest common reference_period: {result['reference_period']}")
    print(f"Previous reference_period: {payload['previous_reference_period']}")
    print(f"Raw snapshot: {safe_relative_path(result['raw_snapshot_path'], root)}")
    print(f"Processed JSON: {safe_relative_path(result['processed_path'], root)}")
    for metric_name, metric in payload["metrics"].items():
        print(
            f"{metric_name}: current {metric['actual_current_display']}, "
            f"previous {metric['previous_current_display']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
