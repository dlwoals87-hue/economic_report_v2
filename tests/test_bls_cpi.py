from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "collectors" / "bls_cpi.py"
SPEC = importlib.util.spec_from_file_location("bls_cpi", MODULE_PATH)
bls_cpi = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["bls_cpi"] = bls_cpi
SPEC.loader.exec_module(bls_cpi)


def sample_response(series_periods):
    series_items = []
    for series_id, periods in series_periods.items():
        data = []
        for period_key, value in periods.items():
            year, month = period_key.split("-")
            data.append(
                {
                    "year": year,
                    "period": f"M{int(month):02d}",
                    "periodName": month,
                    "value": str(value),
                    "footnotes": [{}],
                }
            )
        series_items.append({"seriesID": series_id, "data": data})
    return {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": series_items},
    }


def complete_success_response():
    return sample_response(
        {
            "CUSR0000SA0": {
                "2026-05": "100.3",
                "2026-04": "100",
                "2026-03": "99.6",
                "2025-05": "98",
            },
            "CUUR0000SA0": {
                "2026-05": "102.8",
                "2026-04": "102",
                "2025-05": "100",
                "2025-04": "100.5",
            },
            "CUSR0000SA0L1E": {
                "2026-05": "100.2",
                "2026-04": "100",
                "2026-03": "99.8",
                "2025-05": "99",
            },
            "CUUR0000SA0L1E": {
                "2026-05": "103.1",
                "2026-04": "102.7",
                "2025-05": "100",
                "2025-04": "100.1",
            },
        }
    )


def previous_calculation_response():
    return sample_response(
        {
            "CUSR0000SA0": {
                "2026-05": "101.0",
                "2026-04": "100.0",
                "2026-03": "99.4",
                "2025-05": "98.0",
            },
            "CUUR0000SA0": {
                "2026-05": "104.2",
                "2026-04": "103.8",
                "2025-05": "100.0",
                "2025-04": "100.0",
            },
            "CUSR0000SA0L1E": {
                "2026-05": "100.2",
                "2026-04": "100.0",
                "2026-03": "99.6",
                "2025-05": "98.0",
            },
            "CUUR0000SA0L1E": {
                "2026-05": "102.9",
                "2026-04": "102.8",
                "2025-05": "100.0",
                "2025-04": "100.0",
            },
        }
    )


class BlsCpiTests(unittest.TestCase):
    def test_month_over_month_calculation(self):
        result = bls_cpi.percent_change(Decimal("100.3"), Decimal("100"))
        self.assertEqual(bls_cpi.format_percent_display(result), "0.3%")

    def test_year_over_year_calculation(self):
        result = bls_cpi.percent_change(Decimal("102.8"), Decimal("100"))
        self.assertEqual(bls_cpi.format_percent_display(result), "2.8%")

    def test_display_round_half_up(self):
        self.assertEqual(bls_cpi.format_percent_display(Decimal("0.25")), "0.3%")

    def test_m13_excluded(self):
        response = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": series_id,
                        "data": [
                            {"year": "2026", "period": "M13", "value": "999", "footnotes": []},
                            {"year": "2026", "period": "M02", "value": "101", "footnotes": []},
                            {"year": "2026", "period": "M01", "value": "100", "footnotes": []},
                        ],
                    }
                    for series_id in bls_cpi.SOURCE_SERIES.values()
                ]
            },
        }
        parsed, validation = bls_cpi.parse_bls_response(response)
        self.assertEqual(bls_cpi.find_common_latest_period(parsed), "2026-02")
        self.assertTrue(validation["m13_excluded"])
        self.assertEqual(validation["m13_observation_count"], 4)

    def test_non_numeric_monthly_placeholder_excluded(self):
        response = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": series_id,
                        "data": [
                            {"year": "2025", "period": "M10", "value": "-", "footnotes": []},
                            {"year": "2025", "period": "M09", "value": "101", "footnotes": []},
                            {"year": "2025", "period": "M08", "value": "100", "footnotes": []},
                        ],
                    }
                    for series_id in bls_cpi.SOURCE_SERIES.values()
                ]
            },
        }
        parsed, validation = bls_cpi.parse_bls_response(response)
        self.assertEqual(bls_cpi.find_common_latest_period(parsed), "2025-09")
        self.assertEqual(validation["non_numeric_observation_count"], 4)

    def test_common_latest_period(self):
        parsed = {
            "A": {
                "2026-03": bls_cpi.Observation(2026, 3, "M03", Decimal("100")),
                "2026-04": bls_cpi.Observation(2026, 4, "M04", Decimal("101")),
            },
            "B": {
                "2026-04": bls_cpi.Observation(2026, 4, "M04", Decimal("101")),
                "2026-05": bls_cpi.Observation(2026, 5, "M05", Decimal("102")),
            },
            "C": {
                "2026-02": bls_cpi.Observation(2026, 2, "M02", Decimal("99")),
                "2026-04": bls_cpi.Observation(2026, 4, "M04", Decimal("101")),
            },
            "D": {
                "2026-04": bls_cpi.Observation(2026, 4, "M04", Decimal("101")),
            },
        }
        self.assertEqual(bls_cpi.find_common_latest_period(parsed), "2026-04")

    def test_missing_comparison_period_fails(self):
        cases = [
            {
                "name": "missing_previous_month",
                "periods": {
                    "CUSR0000SA0": {"2026-05": "100.3"},
                    "CUUR0000SA0": {"2026-05": "102.8", "2025-05": "100"},
                    "CUSR0000SA0L1E": {"2026-05": "100.3", "2026-04": "100"},
                    "CUUR0000SA0L1E": {"2026-05": "102.8", "2025-05": "100"},
                },
            },
            {
                "name": "missing_prior_year",
                "periods": {
                    "CUSR0000SA0": {"2026-05": "100.3", "2026-04": "100"},
                    "CUUR0000SA0": {"2026-05": "102.8"},
                    "CUSR0000SA0L1E": {"2026-05": "100.3", "2026-04": "100"},
                    "CUUR0000SA0L1E": {"2026-05": "102.8", "2025-05": "100"},
                },
            },
        ]
        for case in cases:
            with self.subTest(case["name"]):
                parsed, _validation = bls_cpi.parse_bls_response(sample_response(case["periods"]))
                with self.assertRaises(bls_cpi.DataValidationError):
                    bls_cpi.build_metrics(parsed, "2026-05")

    def test_previous_metrics_calculate_expected_displays(self):
        parsed, _validation = bls_cpi.parse_bls_response(previous_calculation_response())
        metrics = bls_cpi.build_metrics(parsed, "2026-05")
        self.assertEqual(metrics["headline_mom"]["previous_current_display"], "0.6%")
        self.assertEqual(metrics["headline_yoy"]["previous_current_display"], "3.8%")
        self.assertEqual(metrics["core_mom"]["previous_current_display"], "0.4%")
        self.assertEqual(metrics["core_yoy"]["previous_current_display"], "2.8%")

    def test_latest_and_previous_reference_periods_are_correct(self):
        parsed, _validation = bls_cpi.parse_bls_response(previous_calculation_response())
        metrics = bls_cpi.build_metrics(parsed, "2026-05")
        for metric in metrics.values():
            self.assertEqual(metric["current_reference_period"], "2026-05")
            self.assertEqual(metric["previous_reference_period"], "2026-04")

    def test_previous_missing_previous_month_fails(self):
        response = previous_calculation_response()
        for series in response["Results"]["series"]:
            if series["seriesID"] == "CUSR0000SA0":
                series["data"] = [
                    item
                    for item in series["data"]
                    if not (item["year"] == "2026" and item["period"] == "M03")
                ]
        parsed, _validation = bls_cpi.parse_bls_response(response)
        with self.assertRaises(bls_cpi.DataValidationError):
            bls_cpi.build_metrics(parsed, "2026-05")

    def test_previous_yoy_missing_13_month_prior_fails(self):
        response = previous_calculation_response()
        for series in response["Results"]["series"]:
            if series["seriesID"] == "CUUR0000SA0":
                series["data"] = [
                    item
                    for item in series["data"]
                    if not (item["year"] == "2025" and item["period"] == "M04")
                ]
        parsed, _validation = bls_cpi.parse_bls_response(response)
        with self.assertRaises(bls_cpi.DataValidationError):
            bls_cpi.build_metrics(parsed, "2026-05")

    def test_current_and_previous_calculations_do_not_mix_periods(self):
        parsed, _validation = bls_cpi.parse_bls_response(previous_calculation_response())
        metrics = bls_cpi.build_metrics(parsed, "2026-05")
        headline_mom = metrics["headline_mom"]
        headline_yoy = metrics["headline_yoy"]
        self.assertEqual(headline_mom["comparison_period"], "2026-04")
        self.assertEqual(headline_mom["previous_comparison_period"], "2026-03")
        self.assertEqual(headline_mom["actual_current_display"], "1.0%")
        self.assertEqual(headline_mom["previous_current_display"], "0.6%")
        self.assertEqual(headline_yoy["comparison_period"], "2025-05")
        self.assertEqual(headline_yoy["previous_comparison_period"], "2025-04")

    def test_invalid_key_retries_unregistered_once(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "status": "REQUEST_NOT_PROCESSED",
                    "message": [
                        "The key:BADKEY provided by the User is invalid. "
                        "Please provide a proper key for the operation to be successful"
                    ],
                }
            return complete_success_response()

        with patch.object(bls_cpi, "post_bls_payload", side_effect=fake_post):
            result = bls_cpi.fetch_bls_response(
                "BADKEY",
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
                logger=None,
            )

        self.assertEqual(result.request_count, 2)
        self.assertTrue(result.registration_key_rejected)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.request_mode, "unregistered_fallback")
        self.assertEqual(result.final_request_mode, "unregistered")
        self.assertEqual(result.response["status"], "REQUEST_SUCCEEDED")

    def test_unregistered_retry_payload_omits_registration_key(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "status": "REQUEST_NOT_PROCESSED",
                    "message": ["invalid key; please provide a proper key"],
                }
            return complete_success_response()

        with patch.object(bls_cpi, "post_bls_payload", side_effect=fake_post):
            bls_cpi.fetch_bls_response(
                "BADKEY",
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
                logger=None,
            )

        self.assertIn("registrationKey", calls[0])
        self.assertNotIn("registrationKey", calls[1])
        self.assertEqual(set(calls[1].keys()), {"seriesid", "startyear", "endyear"})

    def test_network_error_does_not_fallback(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            raise bls_cpi.HttpRequestError("network failed")

        with patch.object(bls_cpi, "post_bls_payload", side_effect=fake_post):
            with self.assertRaises(bls_cpi.HttpRequestError):
                bls_cpi.fetch_bls_response(
                    "BADKEY",
                    now=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    logger=None,
                )

        self.assertEqual(len(calls), 1)
        self.assertIn("registrationKey", calls[0])

    def test_fallback_success_response_processes_normally(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "status": "REQUEST_NOT_PROCESSED",
                    "message": ["The key:BADKEY provided by the User is invalid."],
                }
            return complete_success_response()

        with patch.object(bls_cpi, "post_bls_payload", side_effect=fake_post):
            result = bls_cpi.fetch_bls_response(
                "BADKEY",
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
                logger=None,
            )

        parsed, validation = bls_cpi.parse_bls_response(result.response, api_key="BADKEY")
        reference_period = bls_cpi.find_common_latest_period(parsed)
        metrics = bls_cpi.build_metrics(parsed, reference_period)
        self.assertEqual(validation["returned_series_count"], 4)
        self.assertEqual(reference_period, "2026-05")
        self.assertEqual(set(metrics.keys()), set(bls_cpi.SOURCE_SERIES.keys()))

    def test_maximum_call_count_is_two(self):
        calls = []

        def fake_post(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "status": "REQUEST_NOT_PROCESSED",
                    "message": ["invalid key; proper key required"],
                }
            return complete_success_response()

        with patch.object(bls_cpi, "post_bls_payload", side_effect=fake_post):
            result = bls_cpi.fetch_bls_response(
                "BADKEY",
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
                logger=None,
            )

        self.assertLessEqual(len(calls), 2)
        self.assertEqual(result.request_count, 2)


if __name__ == "__main__":
    unittest.main()
