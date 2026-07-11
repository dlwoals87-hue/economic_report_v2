from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "collectors" / "bls_ppi.py"
SPEC = importlib.util.spec_from_file_location("bls_ppi", MODULE_PATH)
bls_ppi = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["bls_ppi"] = bls_ppi
SPEC.loader.exec_module(bls_ppi)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
REFERENCE_PERIOD = "2026-05"


def response(values: dict[str, dict[str, str]] | None = None) -> dict[str, object]:
    values = values or {
        "WPSFD4": {"2026-05": "101.25", "2026-04": "100", "2025-05": "99"},
        "WPUFD4": {"2026-05": "105.05", "2026-04": "103", "2025-05": "100"},
        "WPSFD49116": {"2026-05": "100.05", "2026-04": "100", "2025-05": "98"},
        "WPUFD49116": {"2026-05": "102.25", "2026-04": "101", "2025-05": "100"},
    }
    series = []
    for series_id, periods in values.items():
        data = []
        for key, value in periods.items():
            year, month = key.split("-")
            data.append({"year": year, "period": f"M{month}", "value": value})
        series.append({"seriesID": series_id, "data": data})
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}


def copied(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(payload))


class BlsPpiTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory(prefix="bls-ppi-") as temporary:
            base = Path(temporary)
            callback(base / "project", base / "preview")

    def collect(self, root: Path, output: Path, payload=None):
        return bls_ppi.collect_ppi(
            REFERENCE_PERIOD,
            output,
            root=root,
            response=payload or response(),
            now=NOW,
        )

    def assert_code(self, callback, code: str):
        with self.assertRaises(bls_ppi.PpiError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_01_official_series_mapping_is_exact(self):
        self.assertEqual(bls_ppi.SOURCE_SERIES, {
            "headline_mom": "WPSFD4",
            "headline_yoy": "WPUFD4",
            "core_mom": "WPSFD49116",
            "core_yoy": "WPUFD49116",
        })

    def test_02_headline_core_and_adjustment_contracts_do_not_mix(self):
        definitions = bls_ppi.METRIC_DEFINITIONS
        self.assertEqual(definitions["headline_mom"]["seasonal_adjustment"], "seasonally_adjusted")
        self.assertEqual(definitions["headline_yoy"]["seasonal_adjustment"], "not_seasonally_adjusted")
        self.assertIn("trade services", definitions["core_mom"]["meaning"])
        parsed, _ = bls_ppi.parse_bls_response(response())
        metrics = bls_ppi.build_metrics(parsed, REFERENCE_PERIOD)
        self.assertEqual(metrics["headline_mom"]["series_id"], "WPSFD4")
        self.assertEqual(metrics["core_yoy"]["series_id"], "WPUFD49116")

    def test_03_reference_period_and_comparison_periods_are_explicit(self):
        parsed, _ = bls_ppi.parse_bls_response(response())
        metrics = bls_ppi.build_metrics(parsed, REFERENCE_PERIOD)
        self.assertEqual(metrics["headline_mom"]["reference_period"], "2026-05")
        self.assertEqual(metrics["headline_mom"]["comparison_period"], "2026-04")
        self.assertEqual(metrics["headline_yoy"]["comparison_period"], "2025-05")

    def test_04_decimal_mom_yoy_and_round_half_up(self):
        parsed, _ = bls_ppi.parse_bls_response(response())
        metrics = bls_ppi.build_metrics(parsed, REFERENCE_PERIOD)
        self.assertEqual(metrics["headline_mom"]["value_raw"], "1.25")
        self.assertEqual(metrics["headline_yoy"]["value_raw"], "5.05")
        self.assertEqual(metrics["headline_mom"]["value_display"], "1.3%")
        self.assertEqual(metrics["headline_yoy"]["value_display"], "5.1%")
        self.assertEqual(bls_ppi.format_percent_display(Decimal("0.25")), "0.3%")

    def test_05_missing_target_month_is_blocked(self):
        payload = response()
        payload["Results"]["series"][0]["data"] = [
            item for item in payload["Results"]["series"][0]["data"] if item["period"] != "M05"
        ]
        parsed, _ = bls_ppi.parse_bls_response(payload)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_REFERENCE_PERIOD_NOT_FOUND")

    def test_06_missing_previous_month_is_blocked(self):
        payload = response()
        payload["Results"]["series"][0]["data"] = [
            item for item in payload["Results"]["series"][0]["data"] if item["period"] != "M04"
        ]
        parsed, _ = bls_ppi.parse_bls_response(payload)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_PREVIOUS_MONTH_NOT_FOUND")

    def test_07_missing_previous_year_month_is_blocked(self):
        payload = response()
        payload["Results"]["series"][1]["data"] = [
            item for item in payload["Results"]["series"][1]["data"] if item["year"] != "2025"
        ]
        parsed, _ = bls_ppi.parse_bls_response(payload)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_PREVIOUS_YEAR_MONTH_NOT_FOUND")

    def test_08_missing_series_is_partial_and_creates_no_output(self):
        payload = response()
        payload["Results"]["series"].pop()

        def case(root, output):
            self.assert_code(lambda: self.collect(root, output, payload), "PPI_PARTIAL_SERIES")
            self.assertFalse(output.exists())
        self.run_in_temp(case)

    def test_09_duplicate_period_is_blocked(self):
        payload = response()
        payload["Results"]["series"][0]["data"].append({"year": "2026", "period": "M05", "value": "101.25"})
        self.assert_code(lambda: bls_ppi.parse_bls_response(payload), "PPI_DUPLICATE_PERIOD")

    def test_10_zero_and_non_numeric_index_are_blocked(self):
        zero = response()
        zero["Results"]["series"][0]["data"][1]["value"] = "0"
        parsed, _ = bls_ppi.parse_bls_response(zero)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_INVALID_INDEX_VALUE")
        invalid = response()
        invalid["Results"]["series"][0]["data"][0]["value"] = "-"
        self.assert_code(lambda: bls_ppi.parse_bls_response(invalid), "PPI_INVALID_INDEX_VALUE")

    def test_11_latest_available_month_is_not_substituted(self):
        payload = response()
        first_data = payload["Results"]["series"][0]["data"]
        first_data[:] = [item for item in first_data if item["period"] != "M05"]
        first_data.append({"year": "2026", "period": "M06", "value": "102"})
        parsed, _ = bls_ppi.parse_bls_response(payload)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_REFERENCE_PERIOD_NOT_FOUND")

    def test_12_calculation_field_mismatch_is_not_silenced(self):
        payload = response()
        payload["Results"]["series"][0]["data"][0]["calculations"] = {"pct_changes": {"1": "8.0"}}
        parsed, _ = bls_ppi.parse_bls_response(payload)
        self.assert_code(lambda: bls_ppi.build_metrics(parsed, REFERENCE_PERIOD), "PPI_CALCULATION_MISMATCH")

    def test_13_raw_is_redacted_and_processed_has_provenance(self):
        payload = response()
        payload["message"] = ["key=VISIBLE_TEST_KEY"]

        def case(root, output):
            self.collect(root, output, payload)
            raw_text = (output / "raw_bls_ppi.json").read_text(encoding="utf-8")
            processed = json.loads((output / "processed_ppi.json").read_text(encoding="utf-8"))
            self.assertNotIn("VISIBLE_TEST_KEY", raw_text)
            self.assertEqual(processed["source"]["data_origin"], "historical_lookup")
            self.assertEqual(processed["source"]["vintage_status"], "current_api_snapshot")
            self.assertTrue(processed["source"]["not_as_released"])
            self.assertTrue(bls_ppi.validate_integrity(processed))
        self.run_in_temp(case)

    def test_14_sha_is_reproducible(self):
        parsed, _ = bls_ppi.parse_bls_response(response())
        metrics = bls_ppi.build_metrics(parsed, REFERENCE_PERIOD)
        self.assertEqual(
            bls_ppi.collection_fingerprint(REFERENCE_PERIOD, response(), metrics, None),
            bls_ppi.collection_fingerprint(REFERENCE_PERIOD, copied(response()), copied(metrics), None),
        )

    def test_15_transport_response_time_does_not_change_the_data_fingerprint(self):
        parsed, _ = bls_ppi.parse_bls_response(response())
        metrics = bls_ppi.build_metrics(parsed, REFERENCE_PERIOD)
        first = response()
        second = response()
        first["responseTime"] = 10
        second["responseTime"] = 999
        self.assertEqual(
            bls_ppi.collection_fingerprint(REFERENCE_PERIOD, first, metrics, None),
            bls_ppi.collection_fingerprint(REFERENCE_PERIOD, second, metrics, None),
        )

    def test_16_same_data_is_idempotent_without_timestamp_change(self):
        def case(root, output):
            first = self.collect(root, output)
            raw = output / "raw_bls_ppi.json"
            before = raw.stat().st_mtime_ns
            second = self.collect(root, output)
            self.assertEqual(first["status"], "PPI_COLLECTION_COMPLETED")
            self.assertEqual(second["status"], "PPI_COLLECTION_ALREADY_COMPLETE")
            self.assertEqual(before, raw.stat().st_mtime_ns)
        self.run_in_temp(case)

    def test_17_changed_data_conflicts_without_overwrite(self):
        def case(root, output):
            self.collect(root, output)
            before = (output / "processed_ppi.json").read_bytes()
            changed = response()
            changed["Results"]["series"][0]["data"][0]["value"] = "102.25"
            self.assert_code(lambda: self.collect(root, output, changed), "PPI_COLLECTION_CONFLICT")
            self.assertEqual(before, (output / "processed_ppi.json").read_bytes())
        self.run_in_temp(case)

    def test_18_project_internal_and_dotdot_output_are_blocked(self):
        with tempfile.TemporaryDirectory(prefix="bls-ppi-output-") as temporary:
            root = Path(temporary) / "project"
            self.assert_code(lambda: self.collect(root, root / "preview"), "PPI_UNSAFE_OUTPUT_ROOT")
            outside_with_dotdot = Path(temporary) / "preview" / ".." / "other-preview"
            self.assert_code(lambda: self.collect(root, outside_with_dotdot), "PPI_UNSAFE_OUTPUT_ROOT")

    def test_19_symlink_output_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="bls-ppi-link-") as temporary:
            base = Path(temporary)
            root = base / "project"
            target = base / "target"
            target.mkdir()
            link = base / "preview-link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (NotImplementedError, OSError):
                link.mkdir()
                with patch.object(Path, "is_symlink", lambda path: path == link):
                    self.assert_code(lambda: self.collect(root, link), "PPI_UNSAFE_OUTPUT_ROOT")
            else:
                self.assert_code(lambda: self.collect(root, link), "PPI_UNSAFE_OUTPUT_ROOT")

    def test_20_fixture_mode_never_calls_bls(self):
        def case(root, output):
            with patch.object(bls_ppi, "post_bls_payload") as post:
                result = self.collect(root, output)
            post.assert_not_called()
            self.assertFalse(result["data_api_called"])
            self.assertFalse(result["ai_api_called"])
            self.assertEqual(result["cost"], "free")
        self.run_in_temp(case)

    def test_21_registered_key_falls_back_without_exposing_it(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {"status": "REQUEST_NOT_PROCESSED", "message": ["invalid key"]}
            return response()

        with patch.object(bls_ppi, "post_bls_payload", side_effect=fake_post):
            result = bls_ppi.fetch_bls_response("PRIVATE_KEY", REFERENCE_PERIOD, logger=None)
        self.assertEqual(result.request_mode, "unregistered_fallback")
        self.assertIn("registrationKey", calls[0])
        self.assertNotIn("registrationKey", calls[1])

    def test_22_cpi_collector_source_is_unchanged(self):
        cpi_source = (ROOT / "scripts" / "collectors" / "bls_cpi.py").read_text(encoding="utf-8")
        self.assertIn('"headline_mom": "CUSR0000SA0"', cpi_source)
        self.assertIn('"core_yoy": "CUUR0000SA0L1E"', cpi_source)


if __name__ == "__main__":
    unittest.main()
