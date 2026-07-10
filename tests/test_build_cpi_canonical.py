from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pipelines" / "build_cpi_canonical.py"
SPEC = importlib.util.spec_from_file_location("build_cpi_canonical", MODULE_PATH)
build_cpi_canonical = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["build_cpi_canonical"] = build_cpi_canonical
SPEC.loader.exec_module(build_cpi_canonical)


def sample_processed():
    return {
        "schema_version": "1.0",
        "indicator_type": "CPI",
        "provider": "BLS",
        "reference_period": "2026-05",
        "retrieved_at_utc": "2026-07-10T11:33:28Z",
        "request_mode": "unregistered_fallback",
        "raw_snapshot_path": "data/raw/bls/cpi/2026-05/retrieved.json",
        "metrics": {
            "headline_mom": metric("0.5%", "0.5", "0.6%", "0.6"),
            "headline_yoy": metric("4.2%", "4.2", "3.8%", "3.8"),
            "core_mom": metric("0.2%", "0.2", "0.4%", "0.4"),
            "core_yoy": metric("2.9%", "2.9", "2.8%", "2.8"),
        },
    }


def metric(actual_display, actual_raw, previous_display, previous_raw):
    return {
        "actual_current_raw": actual_raw,
        "actual_current_display": actual_display,
        "actual_as_released": None,
        "previous_current_raw": previous_raw,
        "previous_current_display": previous_display,
        "previous_as_released": None,
        "as_released_status": "not_captured",
        "previous_as_released_status": "not_captured",
        "unit": "%",
    }


def sample_calendar(expected=False):
    metrics = {
        "headline_mom": {"expected": None, "unit": "%"},
        "headline_yoy": {"expected": None, "unit": "%"},
        "core_mom": {"expected": None, "unit": "%"},
        "core_yoy": {"expected": None, "unit": "%"},
    }
    if expected:
        metrics = {
            "headline_mom": {"expected": "0.4%", "unit": "%"},
            "headline_yoy": {"expected": "4.5%", "unit": "%"},
            "core_mom": {"expected": "0.2%", "unit": "%"},
            "core_yoy": {"expected": {"value": "2.0%"}, "unit": "%"},
        }
    return {
        "events": [
            {
                "event_id": "US_CPI_2026_05",
                "indicator_type": "CPI",
                "country": "US",
                "reference_period": "2026-05",
                "release_datetime_utc": "2026-06-10T12:30:00Z",
                "metrics": metrics,
                "consensus_source": None,
                "consensus_status": "not_entered",
                "entered_at_utc": None,
            }
        ]
    }


def sample_profiles():
    return {
        "CPI": {
            "display_name": "미국 소비자물가지수",
            "country": "US",
        }
    }


def build(calendar=None, processed=None):
    return build_cpi_canonical.build_canonical_payload(
        processed or sample_processed(),
        calendar if calendar is not None else sample_calendar(),
        sample_profiles(),
    )


class BuildCpiCanonicalTests(unittest.TestCase):
    def test_bls_metrics_map_to_canonical_positions(self):
        canonical = build()
        self.assertEqual(canonical["event"]["headline"]["mom"]["actual_current_display"], "0.5%")
        self.assertEqual(canonical["event"]["headline"]["yoy"]["actual_current_display"], "4.2%")
        self.assertEqual(canonical["event"]["core"]["mom"]["actual_current_display"], "0.2%")
        self.assertEqual(canonical["event"]["core"]["yoy"]["actual_current_display"], "2.9%")

    def test_current_and_previous_are_not_swapped(self):
        canonical = build()
        headline_mom = canonical["event"]["headline"]["mom"]
        core_yoy = canonical["event"]["core"]["yoy"]
        self.assertEqual(headline_mom["actual_current_display"], "0.5%")
        self.assertEqual(headline_mom["previous_current_display"], "0.6%")
        self.assertEqual(core_yoy["actual_current_display"], "2.9%")
        self.assertEqual(core_yoy["previous_current_display"], "2.8%")

    def test_expected_null_makes_surprise_null(self):
        canonical = build()
        self.assertIsNone(canonical["event"]["headline"]["mom"]["expected"])
        self.assertIsNone(canonical["event"]["headline"]["mom"]["surprise"])

    def test_expected_values_calculate_surprise(self):
        canonical = build(sample_calendar(expected=True))
        surprise = canonical["event"]["headline"]["mom"]["surprise"]
        self.assertEqual(surprise["surprise_raw"], "0.1")
        self.assertEqual(surprise["surprise_display"], "0.1%")

    def test_surprise_direction_above_below_and_inline(self):
        canonical = build(sample_calendar(expected=True))
        self.assertEqual(
            canonical["event"]["headline"]["mom"]["surprise"]["direction"],
            "above_expected",
        )
        self.assertEqual(
            canonical["event"]["headline"]["yoy"]["surprise"]["direction"],
            "below_expected",
        )
        self.assertEqual(
            canonical["event"]["core"]["mom"]["surprise"]["direction"],
            "in_line",
        )

    def test_missing_calendar_event_sets_expected_null_and_missing_event(self):
        canonical = build({"events": []})
        self.assertEqual(canonical["event"]["consensus"]["status"], "missing_event")
        self.assertIsNone(canonical["event"]["headline"]["mom"]["expected"])
        self.assertIsNone(canonical["event"]["headline"]["mom"]["surprise"])

    def test_duplicate_calendar_events_fail(self):
        calendar = sample_calendar()
        calendar["events"].append(dict(calendar["events"][0], event_id="duplicate"))
        with self.assertRaises(build_cpi_canonical.CanonicalBuildError):
            build(calendar)

    def test_release_datetime_converts_to_asia_seoul(self):
        canonical = build()
        self.assertEqual(canonical["meta"]["release_datetime_utc"], "2026-06-10T12:30:00Z")
        self.assertEqual(canonical["meta"]["release_datetime_kst"], "2026-06-10T21:30:00+09:00")

    def test_is_sample_false(self):
        self.assertFalse(build()["meta"]["is_sample"])

    def test_data_origin_live_bls(self):
        self.assertEqual(build()["meta"]["data_origin"], "live_bls")

    def test_analysis_status_pending(self):
        canonical = build()
        self.assertEqual(canonical["meta"]["analysis_status"], "pending")
        self.assertEqual(canonical["analysis"]["status"], "pending")

    def test_sample_ai_text_is_not_included(self):
        canonical = build()
        serialized = json.dumps(canonical, ensure_ascii=False)
        self.assertIsNone(canonical["analysis"]["summary_html"])
        self.assertEqual(canonical["analysis"]["key_points"], [])
        self.assertNotIn("샘플 AI", serialized)
        self.assertNotIn("시장 해석", serialized)


if __name__ == "__main__":
    unittest.main()
