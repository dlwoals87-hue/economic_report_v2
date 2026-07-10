from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validators" / "validate_calendar_events.py"
SPEC = importlib.util.spec_from_file_location("validate_calendar_events", MODULE_PATH)
validate_calendar_events = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["validate_calendar_events"] = validate_calendar_events
SPEC.loader.exec_module(validate_calendar_events)


NOW = datetime(2026, 6, 10, 11, 30, tzinfo=timezone.utc)


def cpi_event(expected_values=None, status="not_entered", source=None, entered_at=None):
    expected_values = expected_values or {
        "headline_mom": None,
        "headline_yoy": None,
        "core_mom": None,
        "core_yoy": None,
    }
    return {
        "event_id": "US_CPI_2026_05",
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": "2026-05",
        "release_datetime_utc": "2026-06-10T12:30:00Z",
        "metrics": {
            key: {
                "expected": value,
                "unit": "%",
            }
            for key, value in expected_values.items()
        },
        "consensus_source": source,
        "consensus_status": status,
        "entered_at_utc": entered_at,
    }


def payload(event):
    return {"events": [event]}


def validate(event_or_payload):
    data = event_or_payload if "events" in event_or_payload else payload(event_or_payload)
    return validate_calendar_events.validate_events_payload(data, now=NOW)


class ValidateCalendarEventsTests(unittest.TestCase):
    def test_all_expected_null_valid_not_entered(self):
        result = validate(cpi_event())
        self.assertTrue(result.valid)
        self.assertEqual(result.not_entered, 1)

    def test_all_expected_numeric_valid_complete(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": "2.9",
                "core_mom": 0.2,
                "core_yoy": "3.1",
            },
            status="complete",
            source="manual source",
            entered_at="2026-06-10T11:00:00Z",
        )
        result = validate(event)
        self.assertTrue(result.valid)
        self.assertEqual(result.complete, 1)

    def test_some_expected_numeric_valid_partial(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at="2026-06-10T11:00:00Z",
        )
        result = validate(event)
        self.assertTrue(result.valid)
        self.assertEqual(result.partial, 1)

    def test_duplicate_event_id_fails(self):
        first = cpi_event()
        second = cpi_event()
        result = validate({"events": [first, second]})
        self.assertFalse(result.valid)
        self.assertTrue(any("duplicate event_id" in error for error in result.errors))

    def test_reference_period_format_error_fails(self):
        event = cpi_event()
        event["reference_period"] = "2026/05"
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("reference_period" in error for error in result.errors))

    def test_expected_with_percent_sign_fails(self):
        event = cpi_event(
            expected_values={
                "headline_mom": "0.3%",
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at="2026-06-10T11:00:00Z",
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("percent sign" in error for error in result.errors))

    def test_expected_empty_string_fails(self):
        event = cpi_event(
            expected_values={
                "headline_mom": "",
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at="2026-06-10T11:00:00Z",
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("invalid numeric value" in error for error in result.errors))

    def test_expected_requires_consensus_source(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="",
            entered_at="2026-06-10T11:00:00Z",
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("consensus_source" in error for error in result.errors))

    def test_expected_requires_entered_at_utc(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at=None,
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("entered_at_utc" in error for error in result.errors))

    def test_entered_at_timezone_naive_fails(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at="2026-06-10T11:00:00",
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("timezone offset required" in error for error in result.errors))

    def test_entered_at_after_release_fails(self):
        event = cpi_event(
            expected_values={
                "headline_mom": 0.3,
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            },
            status="partial",
            source="manual source",
            entered_at="2026-06-10T12:30:00Z",
        )
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("before release_datetime_utc" in error for error in result.errors))

    def test_consensus_status_mismatch_fails(self):
        event = cpi_event(status="complete")
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("expected not_entered" in error for error in result.errors))

    def test_missing_cpi_metric_fails(self):
        event = cpi_event()
        del event["metrics"]["core_yoy"]
        result = validate(event)
        self.assertFalse(result.valid)
        self.assertTrue(any("metrics.core_yoy" in error for error in result.errors))

    def test_expected_null_is_not_an_error(self):
        result = validate(cpi_event())
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
