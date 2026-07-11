from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
REFERENCE_PERIOD_FORMAT = "%Y-%m"

SOURCE_SERIES = {
    "headline_mom": "WPSFD4",
    "headline_yoy": "WPUFD4",
    "core_mom": "WPSFD49116",
    "core_yoy": "WPUFD49116",
}

METRIC_DEFINITIONS = {
    "headline_mom": {
        "series_id": "WPSFD4",
        "meaning": "Final demand",
        "seasonal_adjustment": "seasonally_adjusted",
        "calculation": "mom",
        "months_back": 1,
    },
    "headline_yoy": {
        "series_id": "WPUFD4",
        "meaning": "Final demand",
        "seasonal_adjustment": "not_seasonally_adjusted",
        "calculation": "yoy",
        "months_back": 12,
    },
    "core_mom": {
        "series_id": "WPSFD49116",
        "meaning": "Final demand less foods, energy, and trade services",
        "seasonal_adjustment": "seasonally_adjusted",
        "calculation": "mom",
        "months_back": 1,
    },
    "core_yoy": {
        "series_id": "WPUFD49116",
        "meaning": "Final demand less foods, energy, and trade services",
        "seasonal_adjustment": "not_seasonally_adjusted",
        "calculation": "yoy",
        "months_back": 12,
    },
}


class PpiError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Observation:
    period: str
    value: Decimal
    calculations: dict[str, Any] | None


@dataclass(frozen=True)
class FetchResult:
    response: dict[str, Any]
    request_mode: str
    registration_key_used: bool
    fallback_used: bool
    request_count: int


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_percent_display(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%"


def percent_change(current: Decimal, comparison: Decimal) -> Decimal:
    if current <= 0 or comparison <= 0:
        raise PpiError("PPI_INVALID_INDEX_VALUE", "index levels must be greater than zero")
    with localcontext() as context:
        context.prec = 34
        return (current / comparison - Decimal("1")) * Decimal("100")


def validate_reference_period(value: str) -> str:
    try:
        parsed = datetime.strptime(value, REFERENCE_PERIOD_FORMAT)
    except ValueError as exc:
        raise PpiError("PPI_INVALID_REFERENCE_PERIOD", "reference period must be YYYY-MM") from exc
    return parsed.strftime(REFERENCE_PERIOD_FORMAT)


def shift_month(period: str, months_back: int) -> str:
    year, month = (int(part) for part in period.split("-", 1))
    absolute = year * 12 + month - 1 - months_back
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def parse_month(year: Any, period: Any) -> str | None:
    if not isinstance(year, str) or not isinstance(period, str) or not period.startswith("M"):
        return None
    try:
        month = int(period[1:])
        year_number = int(year)
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year_number:04d}-{month:02d}"


def sanitize_text(value: str, api_key: str | None) -> str:
    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    return re.sub(
        r"(?i)\b(key|token|password|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        value,
    )


def sanitize_payload(value: Any, api_key: str | None) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_payload(item, api_key)
            for key, item in value.items()
            if not any(token in key.lower() for token in ("key", "token", "password", "secret"))
        }
    if isinstance(value, list):
        return [sanitize_payload(item, api_key) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, api_key)
    return value


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_for(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def with_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["integrity"] = {"sha256": sha256_for(payload)}
    return result


def validate_integrity(payload: dict[str, Any]) -> bool:
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or not isinstance(integrity.get("sha256"), str):
        return False
    unsigned = dict(payload)
    unsigned.pop("integrity", None)
    return integrity["sha256"] == sha256_for(unsigned)


def build_request_payload(reference_period: str, api_key: str | None = None, registered: bool = False) -> dict[str, Any]:
    reference_period = validate_reference_period(reference_period)
    year = int(reference_period[:4])
    payload: dict[str, Any] = {
        "seriesid": list(SOURCE_SERIES.values()),
        "startyear": str(year - 1),
        "endyear": str(year),
    }
    if registered:
        if not api_key:
            raise PpiError("PPI_BLS_API_KEY_REQUIRED", "registered mode requires BLS_API_KEY")
        payload["registrationKey"] = api_key
    return payload


def post_bls_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        BLS_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise PpiError("PPI_BLS_HTTP_ERROR", f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise PpiError("PPI_BLS_HTTP_ERROR", "network error") from exc
    except TimeoutError as exc:
        raise PpiError("PPI_BLS_HTTP_ERROR", "network timeout") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PpiError("PPI_BLS_INVALID_JSON", "BLS returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise PpiError("PPI_BLS_INVALID_JSON", "BLS JSON root is not an object")
    return parsed


def registration_key_rejected(response: dict[str, Any], api_key: str | None) -> bool:
    if response.get("status") != "REQUEST_NOT_PROCESSED":
        return False
    message = sanitize_text("; ".join(str(item) for item in response.get("message", [])), api_key).lower()
    return ("invalid" in message and "key" in message) or "proper key" in message


def fetch_bls_response(api_key: str | None, reference_period: str, logger: Callable[[str], None] | None = print) -> FetchResult:
    if api_key:
        if logger:
            logger("BLS request mode: registered")
        response = post_bls_payload(build_request_payload(reference_period, api_key, registered=True))
        if not registration_key_rejected(response, api_key):
            return FetchResult(response, "registered", True, False, 1)
        if logger:
            logger("Registered key rejected; retrying in unregistered mode")
        fallback = post_bls_payload(build_request_payload(reference_period))
        return FetchResult(fallback, "unregistered_fallback", False, True, 2)
    if logger:
        logger("BLS request mode: unregistered")
    return FetchResult(post_bls_payload(build_request_payload(reference_period)), "unregistered", False, False, 1)


def parse_bls_response(response: dict[str, Any], api_key: str | None = None) -> tuple[dict[str, dict[str, Observation]], dict[str, Any]]:
    if response.get("status") != "REQUEST_SUCCEEDED":
        message = sanitize_text("; ".join(str(item) for item in response.get("message", [])), api_key)
        raise PpiError("PPI_BLS_REQUEST_NOT_PROCESSED", message)
    results = response.get("Results")
    series_list = results.get("series") if isinstance(results, dict) else None
    if not isinstance(series_list, list):
        raise PpiError("PPI_PARTIAL_SERIES", "BLS response missing Results.series")

    parsed: dict[str, dict[str, Observation]] = {}
    seen: set[str] = set()
    for series in series_list:
        if not isinstance(series, dict) or not isinstance(series.get("seriesID"), str):
            raise PpiError("PPI_PARTIAL_SERIES", "BLS response contains an invalid series")
        series_id = series["seriesID"]
        if series_id in seen:
            raise PpiError("PPI_PARTIAL_SERIES", f"duplicate series {series_id}")
        seen.add(series_id)
        data = series.get("data")
        if not isinstance(data, list):
            raise PpiError("PPI_PARTIAL_SERIES", f"series {series_id} has no data array")
        observations: dict[str, Observation] = {}
        for item in data:
            if not isinstance(item, dict):
                raise PpiError("PPI_INVALID_INDEX_VALUE", f"series {series_id} has invalid observation")
            period = parse_month(item.get("year"), item.get("period"))
            if period is None:
                continue
            if period in observations:
                raise PpiError("PPI_DUPLICATE_PERIOD", f"series {series_id} repeats {period}")
            value = item.get("value")
            if not isinstance(value, str):
                raise PpiError("PPI_INVALID_INDEX_VALUE", f"series {series_id} {period} value is invalid")
            try:
                decimal_value = Decimal(value)
            except InvalidOperation as exc:
                raise PpiError("PPI_INVALID_INDEX_VALUE", f"series {series_id} {period} value is invalid") from exc
            calculations = item.get("calculations")
            if calculations is not None and not isinstance(calculations, dict):
                raise PpiError("PPI_CALCULATION_MISMATCH", f"series {series_id} {period} calculations are invalid")
            observations[period] = Observation(period, decimal_value, calculations)
        parsed[series_id] = observations

    expected = set(SOURCE_SERIES.values())
    if set(parsed) != expected:
        missing = sorted(expected - set(parsed))
        unexpected = sorted(set(parsed) - expected)
        raise PpiError("PPI_PARTIAL_SERIES", f"missing={missing}; unexpected={unexpected}")
    return parsed, {"requested_series_count": 4, "returned_series_count": len(series_list)}


def api_calculation(observation: Observation, months_back: int) -> Decimal | None:
    if observation.calculations is None:
        return None
    values = observation.calculations.get("pct_changes", observation.calculations)
    if not isinstance(values, dict):
        return None
    candidate = values.get(str(months_back), values.get(months_back))
    if candidate is None:
        return None
    try:
        return Decimal(str(candidate))
    except InvalidOperation as exc:
        raise PpiError("PPI_CALCULATION_MISMATCH", "BLS percentage calculation is invalid") from exc


def build_metrics(series_data: dict[str, dict[str, Observation]], reference_period: str) -> dict[str, dict[str, Any]]:
    reference_period = validate_reference_period(reference_period)
    metrics: dict[str, dict[str, Any]] = {}
    for name, definition in METRIC_DEFINITIONS.items():
        observations = series_data.get(str(definition["series_id"]))
        if observations is None:
            raise PpiError("PPI_PARTIAL_SERIES", f"missing {definition['series_id']}")
        current = observations.get(reference_period)
        if current is None:
            raise PpiError("PPI_REFERENCE_PERIOD_NOT_FOUND", f"{name} missing {reference_period}")
        months_back = int(definition["months_back"])
        comparison_period = shift_month(reference_period, months_back)
        comparison = observations.get(comparison_period)
        if comparison is None:
            code = "PPI_PREVIOUS_MONTH_NOT_FOUND" if months_back == 1 else "PPI_PREVIOUS_YEAR_MONTH_NOT_FOUND"
            raise PpiError(code, f"{name} missing {comparison_period}")
        raw = percent_change(current.value, comparison.value)
        provided = api_calculation(current, months_back)
        if provided is not None and format_percent_display(provided) != format_percent_display(raw):
            raise PpiError("PPI_CALCULATION_MISMATCH", f"{name} BLS calculation differs from index calculation")
        metrics[name] = {
            "series_id": definition["series_id"],
            "meaning": definition["meaning"],
            "seasonal_adjustment": definition["seasonal_adjustment"],
            "reference_period": reference_period,
            "comparison_period": comparison_period,
            "current_index": decimal_to_plain(current.value),
            "comparison_index": decimal_to_plain(comparison.value),
            "value_raw": decimal_to_plain(raw),
            "value_display": format_percent_display(raw),
            "calculation": definition["calculation"],
            "calculation_formula": "((current_index / comparison_index) - 1) * 100",
        }
    return metrics


def normalized_response(response: dict[str, Any], api_key: str | None) -> dict[str, Any]:
    sanitized = sanitize_payload(response, api_key)
    results = sanitized.get("Results") if isinstance(sanitized, dict) else None
    series = results.get("series") if isinstance(results, dict) else None
    if not isinstance(series, list):
        return sanitized
    for item in series:
        if isinstance(item, dict) and isinstance(item.get("data"), list):
            item["data"].sort(key=lambda row: (str(row.get("year")), str(row.get("period"))))
    series.sort(key=lambda item: str(item.get("seriesID")) if isinstance(item, dict) else "")
    # BLS responseTime is transport metadata, not source data. Only the
    # normalized successful series snapshot participates in idempotency.
    return {"status": sanitized.get("status"), "Results": {"series": series}}


def collection_fingerprint(reference_period: str, response: dict[str, Any], metrics: dict[str, dict[str, Any]], api_key: str | None) -> str:
    return sha256_for({
        "reference_period": reference_period,
        "response": normalized_response(response, api_key),
        "metrics": metrics,
    })


def assert_safe_output_root(output_root: Path, root: Path) -> Path:
    if not output_root.is_absolute() or ".." in output_root.parts:
        raise PpiError("PPI_UNSAFE_OUTPUT_ROOT", "output root must be an absolute path without ..")
    candidate = output_root.resolve(strict=False)
    project = root.resolve()
    try:
        candidate.relative_to(project)
    except ValueError:
        pass
    else:
        raise PpiError("PPI_UNSAFE_OUTPUT_ROOT", "output root must be outside the project")
    current = output_root
    while current != current.parent:
        if current.exists() and current.is_symlink():
            raise PpiError("PPI_UNSAFE_OUTPUT_ROOT", "symlink output roots are not allowed")
        current = current.parent
    return candidate


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PpiError("PPI_COLLECTION_CONFLICT", f"cannot read existing {path.name}") from exc
    if not isinstance(value, dict):
        raise PpiError("PPI_COLLECTION_CONFLICT", f"existing {path.name} is invalid")
    return value


def existing_status(output_root: Path, fingerprint: str) -> str | None:
    paths = [output_root / name for name in ("raw_bls_ppi.json", "processed_ppi.json", "result.json")]
    exists = [path.exists() for path in paths]
    if not any(exists):
        return None
    if not all(exists):
        raise PpiError("PPI_COLLECTION_CONFLICT", "incomplete existing collection")
    raw = read_json(paths[0])
    processed = read_json(paths[1])
    result = read_json(paths[2])
    raw_response = raw.get("response")
    raw_reference_period = raw.get("reference_period")
    metrics = processed.get("metrics")
    if (
        not validate_integrity(processed)
        or not isinstance(raw_response, dict)
        or not isinstance(raw_reference_period, str)
        or not isinstance(metrics, dict)
        or result.get("processed_sha256") != processed["integrity"]["sha256"]
    ):
        raise PpiError("PPI_COLLECTION_CONFLICT", "existing collection fails integrity")
    persisted_fingerprint = collection_fingerprint(
        raw_reference_period,
        raw_response,
        metrics,
        None,
    )
    if persisted_fingerprint != fingerprint:
        raise PpiError("PPI_COLLECTION_CONFLICT", "existing collection differs or fails integrity")
    return "PPI_COLLECTION_ALREADY_COMPLETE"


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            handle.write(encoded)
            temporary_name = handle.name
        with path.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(Path(temporary_name).read_text(encoding="utf-8"))
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def collect_ppi(
    reference_period: str,
    output_root: Path,
    *,
    root: Path | None = None,
    response: dict[str, Any] | None = None,
    use_live_bls: bool = False,
    api_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference_period = validate_reference_period(reference_period)
    root = root or project_root()
    output_root = assert_safe_output_root(output_root, root)
    retrieved_at = now or utc_now()
    if response is None:
        if not use_live_bls:
            raise PpiError("PPI_LIVE_BLS_NOT_ENABLED", "pass --use-live-bls or provide --bls-response")
        fetched = fetch_bls_response(api_key, reference_period)
        response = fetched.response
        request_mode = fetched.request_mode
        registration_key_used = fetched.registration_key_used
        data_api_called = True
    else:
        request_mode = "fixture"
        registration_key_used = False
        data_api_called = False

    series_data, validation = parse_bls_response(response, api_key)
    metrics = build_metrics(series_data, reference_period)
    fingerprint = collection_fingerprint(reference_period, response, metrics, api_key)
    status = existing_status(output_root, fingerprint)
    if status:
        return {
            "status": status,
            "reference_period": reference_period,
            "data_api_called": data_api_called,
            "ai_api_called": False,
            "cost": "free",
            "collection_sha256": fingerprint,
        }

    raw_payload = {
        "schema_version": "1.0",
        "retrieved_at_utc": iso_utc(retrieved_at),
        "reference_period": reference_period,
        "source_provider": "BLS",
        "current_api_snapshot": True,
        "series_mapping": SOURCE_SERIES,
        "response": normalized_response(response, api_key),
    }
    processed_payload = with_integrity({
        "schema_version": "1.0",
        "indicator_type": "PPI",
        "country": "US",
        "reference_period": reference_period,
        "retrieved_at_utc": iso_utc(retrieved_at),
        "source": {
            "provider": "BLS",
            "data_origin": "historical_lookup",
            "vintage_status": "current_api_snapshot",
            "not_as_released": True,
        },
        "series_mapping": SOURCE_SERIES,
        "metrics": metrics,
        "validation": validation,
    })
    result_payload = {
        "status": "PPI_COLLECTION_COMPLETED",
        "reference_period": reference_period,
        "data_api_called": data_api_called,
        "ai_api_called": False,
        "cost": "free",
        "request_mode": request_mode,
        "registration_key_used": registration_key_used,
        "collection_sha256": fingerprint,
        "processed_sha256": processed_payload["integrity"]["sha256"],
    }
    for name, payload in (
        ("raw_bls_ppi.json", raw_payload),
        ("processed_ppi.json", processed_payload),
        ("result.json", result_payload),
    ):
        write_json_exclusive(output_root / name, payload)
    return result_payload


def load_response_fixture(path: Path) -> dict[str, Any]:
    return read_json(path)


def parse_now(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PpiError("PPI_INVALID_NOW_UTC", "--now-utc must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise PpiError("PPI_INVALID_NOW_UTC", "--now-utc requires timezone")
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect historical PPI data from BLS.")
    parser.add_argument("--reference-period", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--use-live-bls", action="store_true")
    parser.add_argument("--bls-response")
    parser.add_argument("--now-utc")
    args = parser.parse_args(argv)
    if args.use_live_bls and args.bls_response:
        parser.error("--use-live-bls and --bls-response cannot be used together")
    try:
        response = load_response_fixture(Path(args.bls_response)) if args.bls_response else None
        result = collect_ppi(
            args.reference_period,
            Path(args.output_root),
            response=response,
            use_live_bls=args.use_live_bls,
            api_key=os.environ.get("BLS_API_KEY"),
            now=parse_now(args.now_utc),
        )
    except PpiError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
