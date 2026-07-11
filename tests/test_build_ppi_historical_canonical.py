from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.automation import run_ppi_historical_backfill as backfill
from scripts.collectors import bls_ppi
from scripts.pipelines import build_ppi_historical_canonical as canonical


def processed() -> dict:
    metrics = {}
    for name, series in canonical.SERIES.items():
        metrics[name] = {"series_id": series, "seasonal_adjustment": "seasonally_adjusted" if name.endswith("mom") else "not_seasonally_adjusted", "value_raw": "1.25", "value_display": "1.3%", "calculation": "mom" if name.endswith("mom") else "yoy"}
    result = {"schema_version": "1.0", "indicator_type": "PPI", "country": "US", "reference_period": "2026-05", "source": {"data_origin": "historical_lookup", "vintage_status": "current_api_snapshot", "not_as_released": True}, "metrics": metrics, "integrity": {"sha256": None}}
    return bls_ppi.with_integrity({key: value for key, value in result.items() if key != "integrity"})


class PpiCanonicalTests(unittest.TestCase):
    def observation(self):
        return backfill.build_observation(processed(), "US_PPI_2026_05", "2026-06-11T12:30:00Z", datetime(2026, 7, 11, tzinfo=timezone.utc))

    def test_processed_sha_and_series_mapping_are_required(self):
        observation = self.observation()
        result = canonical.build_canonical("US_PPI_2026_05", "2026-05", "2026-06-11T12:30:00Z", observation)
        canonical.validate_canonical(result, "US_PPI_2026_05")
        self.assertEqual(result["metrics"]["core_mom"]["source_series_id"], "WPSFD49116")
        bad = processed(); bad["metrics"]["headline_mom"]["series_id"] = "WPUFD4"
        with self.assertRaises(canonical.PpiCanonicalError):
            canonical.validate_processed(bad, "2026-05")

    def test_expected_surprise_and_previous_are_null(self):
        result = canonical.build_canonical("US_PPI_2026_05", "2026-05", "2026-06-11T12:30:00Z", self.observation())
        for metric in result["metrics"].values():
            self.assertIsNone(metric["expected_raw"])
            self.assertIsNone(metric["surprise_raw"])
            self.assertIsNone(metric["previous_raw"])

    def test_historical_times_and_provenance_are_distinct(self):
        result = canonical.build_canonical("US_PPI_2026_05", "2026-05", "2026-06-11T12:30:00Z", self.observation())
        self.assertEqual(result["meta"]["original_release_datetime_utc"], "2026-06-11T12:30:00Z")
        self.assertEqual(result["meta"]["retrieved_at_utc"], "2026-07-11T00:00:00Z")
        self.assertTrue(result["meta"]["not_as_released"])
