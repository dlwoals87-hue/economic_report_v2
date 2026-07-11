from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.collectors import bls_ppi


METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
SERIES = {
    "headline_mom": "WPSFD4", "headline_yoy": "WPUFD4",
    "core_mom": "WPSFD49116", "core_yoy": "WPUFD49116",
}


class PpiCanonicalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def sha256_payload(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload)
    if isinstance(value.get("integrity"), dict):
        value["integrity"].pop("sha256", None)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PpiCanonicalError("PPI_INVALID_TIMESTAMP", f"{field} must be timezone-aware ISO 8601") from exc
    if parsed.tzinfo is None:
        raise PpiCanonicalError("PPI_INVALID_TIMESTAMP", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_processed(processed: dict[str, Any], reference_period: str) -> None:
    integrity = processed.get("integrity")
    if not isinstance(integrity, dict) or not bls_ppi.validate_integrity(processed):
        raise PpiCanonicalError("PPI_PROCESSED_SHA_MISMATCH", "processed PPI integrity check failed")
    if processed.get("indicator_type") != "PPI" or processed.get("country") != "US":
        raise PpiCanonicalError("PPI_PROCESSED_INVALID", "processed PPI identity is invalid")
    if processed.get("reference_period") != reference_period:
        raise PpiCanonicalError("PPI_REFERENCE_PERIOD_MISMATCH", "processed reference period differs")
    source = processed.get("source")
    if not isinstance(source, dict) or source.get("data_origin") != "historical_lookup" or source.get("vintage_status") != "current_api_snapshot" or source.get("not_as_released") is not True:
        raise PpiCanonicalError("PPI_PROCESSED_INVALID", "processed provenance is invalid")
    metrics = processed.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(METRICS):
        raise PpiCanonicalError("PPI_PARTIAL_SERIES", "four PPI metrics are required")
    for name in METRICS:
        metric = metrics[name]
        if not isinstance(metric, dict) or metric.get("series_id") != SERIES[name]:
            raise PpiCanonicalError("PPI_SERIES_MISMATCH", f"{name} has an invalid series")
        expected_adjustment = "seasonally_adjusted" if name.endswith("mom") else "not_seasonally_adjusted"
        if metric.get("seasonal_adjustment") != expected_adjustment:
            raise PpiCanonicalError("PPI_SEASONAL_ADJUSTMENT_MISMATCH", f"{name} adjustment is invalid")
        if not isinstance(metric.get("value_raw"), str) or not isinstance(metric.get("value_display"), str):
            raise PpiCanonicalError("PPI_PROCESSED_INVALID", f"{name} values are invalid")


def build_canonical(
    event_id: str,
    reference_period: str,
    original_release_datetime_utc: str,
    observation: dict[str, Any],
) -> dict[str, Any]:
    processed = observation.get("processed")
    if not isinstance(processed, dict):
        raise PpiCanonicalError("PPI_PROCESSED_INVALID", "historical observation lacks processed PPI")
    validate_processed(processed, reference_period)
    observation_integrity = observation.get("integrity")
    if not isinstance(observation_integrity, dict) or observation_integrity.get("sha256") != sha256_payload(observation):
        raise PpiCanonicalError("PPI_OBSERVATION_SHA_MISMATCH", "historical observation integrity check failed")
    release = parse_utc(original_release_datetime_utc, "original_release_datetime_utc")
    retrieved_at = observation.get("retrieved_at_utc")
    parse_utc(retrieved_at, "retrieved_at_utc")
    canonical_metrics: dict[str, Any] = {}
    for name in METRICS:
        metric = processed["metrics"][name]
        canonical_metrics[name] = {
            "actual_raw": metric["value_raw"], "actual_display": metric["value_display"],
            "expected_raw": None, "expected_display": None,
            "previous_raw": None, "previous_display": None,
            "surprise_raw": None, "surprise_display": None,
            "source_series_id": metric["series_id"],
            "seasonal_adjustment": metric["seasonal_adjustment"],
            "calculation": metric["calculation"],
        }
    result = {
        "schema_version": "1.0",
        "meta": {
            "event_id": event_id, "indicator_type": "PPI", "indicator_name": "US Producer Price Index",
            "country": "US", "reference_period": reference_period,
            "original_release_datetime_utc": iso_utc(release),
            "original_release_datetime_kst": release.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
            "retrieved_at_utc": retrieved_at, "data_origin": "historical_backfill",
            "vintage_status": "current_api_snapshot", "not_as_released": True, "is_sample": False,
        },
        "metrics": canonical_metrics,
        "source": {
            "provider": "BLS", "historical_observation_sha256": observation_integrity["sha256"],
            "processed_ppi_sha256": processed["integrity"]["sha256"], "source_lookup_origin": "historical_lookup",
        },
        "integrity": {"sha256": None},
    }
    result["integrity"]["sha256"] = sha256_payload(result)
    return result


def validate_canonical(canonical: dict[str, Any], event_id: str) -> None:
    if canonical.get("integrity", {}).get("sha256") != sha256_payload(canonical):
        raise PpiCanonicalError("PPI_CANONICAL_SHA_MISMATCH", "canonical integrity check failed")
    meta = canonical.get("meta")
    if not isinstance(meta, dict) or meta.get("event_id") != event_id or meta.get("indicator_type") != "PPI":
        raise PpiCanonicalError("PPI_CANONICAL_INVALID", "canonical identity is invalid")
    if meta.get("data_origin") != "historical_backfill" or meta.get("not_as_released") is not True:
        raise PpiCanonicalError("PPI_CANONICAL_INVALID", "canonical provenance is invalid")
    metrics = canonical.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(METRICS):
        raise PpiCanonicalError("PPI_CANONICAL_INVALID", "canonical metrics are invalid")
    for name in METRICS:
        metric = metrics[name]
        if metric.get("expected_raw") is not None or metric.get("surprise_raw") is not None:
            raise PpiCanonicalError("PPI_CANONICAL_INVALID", "expected and surprise must be null")
        if metric.get("previous_raw") is not None or metric.get("previous_display") is not None:
            raise PpiCanonicalError("PPI_CANONICAL_INVALID", "previous PPI rate is unavailable")
        if metric.get("source_series_id") != SERIES[name]:
            raise PpiCanonicalError("PPI_CANONICAL_INVALID", "canonical series mapping is invalid")
