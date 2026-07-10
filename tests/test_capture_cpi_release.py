from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pipelines" / "capture_cpi_release.py"
SPEC = importlib.util.spec_from_file_location("capture_cpi_release", MODULE_PATH)
capture_cpi_release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["capture_cpi_release"] = capture_cpi_release
SPEC.loader.exec_module(capture_cpi_release)


@dataclass
class FakeFetchResult:
    request_count: int = 1


def base_event(event_id="US_CPI_2026_06", reference_period="2026-06"):
    return {
        "event_id": event_id,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "metrics": {
            "headline_mom": {"expected": None, "unit": "%"},
            "headline_yoy": {"expected": None, "unit": "%"},
            "core_mom": {"expected": None, "unit": "%"},
            "core_yoy": {"expected": None, "unit": "%"},
        },
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def may_event():
    event = base_event("US_CPI_2026_05", "2026-05")
    event["release_datetime_utc"] = "2026-06-10T12:30:00Z"
    return event


def write_calendar(root: Path, events):
    path = root / "data" / "calendar" / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "events": events}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def metric(actual_raw, actual_display, previous_raw, previous_display):
    return {
        "actual_current_raw": actual_raw,
        "actual_current_display": actual_display,
        "previous_current_raw": previous_raw,
        "previous_current_display": previous_display,
    }


def collect_result(root: Path, reference_period="2026-06"):
    raw_path = root / "data" / "raw" / "bls" / "cpi" / reference_period / "retrieved.json"
    return {
        "reference_period": reference_period,
        "raw_snapshot_path": raw_path,
        "processed_path": root / "data" / "processed" / "bls" / "cpi_latest.json",
        "processed_payload": {
            "reference_period": reference_period,
            "retrieved_at_utc": "2026-07-14T12:31:00Z",
            "request_mode": "unregistered_fallback",
            "metrics": {
                "headline_mom": metric("0.3", "0.3%", "0.5", "0.5%"),
                "headline_yoy": metric("2.9", "2.9%", "3.0", "3.0%"),
                "core_mom": metric("0.2", "0.2%", "0.3", "0.3%"),
                "core_yoy": metric("3.1", "3.1%", "3.2", "3.2%"),
            },
        },
        "fetch_result": FakeFetchResult(1),
    }


class CaptureCpiReleaseTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_calendar(root, [may_event(), base_event()])
            return callback(root)

    def test_waiting_before_release(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 29, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "WAITING_FOR_RELEASE")
        self.run_in_temp(case)

    def test_waiting_before_release_has_zero_bls_calls(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 10, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.api_call_count, 0)
        self.run_in_temp(case)

    def test_stale_bls_reference_returns_data_not_available(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-05"),
            )
            self.assertEqual(result.status, "DATA_NOT_AVAILABLE_YET")
            self.assertEqual(result.latest_reference_period, "2026-05")
        self.run_in_temp(case)

    def test_stale_bls_data_does_not_create_as_released(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-05"),
            )
            self.assertEqual(result.status, "DATA_NOT_AVAILABLE_YET")
            self.assertFalse(capture_cpi_release.release_path(root, "US_CPI_2026_06").exists())
        self.run_in_temp(case)

    def test_matching_reference_creates_as_released_file(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            self.assertEqual(result.status, "CAPTURED")
            self.assertTrue(capture_cpi_release.release_path(root, "US_CPI_2026_06").exists())
        self.run_in_temp(case)

    def test_actual_current_copies_to_actual_as_released(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertEqual(payload["metrics"]["headline_mom"]["actual_as_released_raw"], "0.3")
            self.assertEqual(payload["metrics"]["headline_mom"]["actual_as_released_display"], "0.3%")
        self.run_in_temp(case)

    def test_previous_current_copies_to_previous_as_released(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertEqual(payload["metrics"]["core_yoy"]["previous_as_released_raw"], "3.2")
            self.assertEqual(payload["metrics"]["core_yoy"]["previous_as_released_display"], "3.2%")
        self.run_in_temp(case)

    def test_all_four_metrics_are_saved(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertEqual(set(payload["metrics"].keys()), set(capture_cpi_release.CPI_METRICS))
        self.run_in_temp(case)

    def test_second_run_does_not_overwrite(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            path = capture_cpi_release.release_path(root, "US_CPI_2026_06")
            before = path.read_bytes()
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 32, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(result.api_call_count, 0)
        self.run_in_temp(case)

    def test_second_run_status_already_captured(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 32, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "ALREADY_CAPTURED")
        self.run_in_temp(case)

    def test_missing_event_fails(self):
        def case(root):
            with self.assertRaises(capture_cpi_release.CaptureError):
                capture_cpi_release.capture_release(root, "NOPE")
        self.run_in_temp(case)

    def test_duplicate_event_id_fails(self):
        def case(root):
            write_calendar(root, [base_event(), base_event()])
            with self.assertRaises(capture_cpi_release.CaptureError):
                capture_cpi_release.capture_release(root, "US_CPI_2026_06")
        self.run_in_temp(case)

    def test_timezone_naive_release_time_fails(self):
        def case(root):
            event = base_event()
            event["release_datetime_utc"] = "2026-07-14T12:30:00"
            write_calendar(root, [event])
            with self.assertRaises(capture_cpi_release.CaptureError):
                capture_cpi_release.capture_release(root, "US_CPI_2026_06")
        self.run_in_temp(case)

    def test_non_cpi_event_fails(self):
        def case(root):
            event = base_event()
            event["indicator_type"] = "PPI"
            write_calendar(root, [event])
            with self.assertRaises(capture_cpi_release.CaptureError):
                capture_cpi_release.capture_release(root, "US_CPI_2026_06")
        self.run_in_temp(case)

    def test_api_key_not_written_to_result_file(self):
        def case(root):
            os.environ["BLS_API_KEY"] = "SECRET_TEST_KEY"
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            text = capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text(encoding="utf-8")
            self.assertNotIn("SECRET_TEST_KEY", text)
        self.run_in_temp(case)

    def test_sha256_is_reproducible(self):
        def case(root):
            event = base_event()
            result = collect_result(root, "2026-06")
            first = capture_cpi_release.build_release_payload(
                event,
                result["processed_payload"],
                "data/raw/bls/cpi/2026-06/retrieved.json",
                datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
            )
            second = capture_cpi_release.build_release_payload(
                event,
                result["processed_payload"],
                "data/raw/bls/cpi/2026-06/retrieved.json",
                datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
            )
            self.assertEqual(first["integrity"]["sha256"], second["integrity"]["sha256"])
        self.run_in_temp(case)

    def test_no_temp_or_partial_file_remains(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            release_dir = capture_cpi_release.release_path(root, "US_CPI_2026_06").parent
            self.assertEqual(list(release_dir.glob("*.tmp")), [])
            self.assertEqual([p.name for p in release_dir.iterdir()], ["as_released.json"])
        self.run_in_temp(case)

    def test_existing_may_event_is_preserved_when_adding_june_event(self):
        calendar = {"events": [may_event()]}
        added = capture_cpi_release.ensure_june_cpi_event(calendar)
        self.assertTrue(added)
        self.assertTrue(any(event["event_id"] == "US_CPI_2026_05" for event in calendar["events"]))
        self.assertTrue(any(event["event_id"] == "US_CPI_2026_06" for event in calendar["events"]))

    def test_june_event_is_not_added_twice(self):
        calendar = {"events": [may_event(), base_event()]}
        added = capture_cpi_release.ensure_june_cpi_event(calendar)
        self.assertFalse(added)
        june_count = sum(1 for event in calendar["events"] if event["event_id"] == "US_CPI_2026_06")
        self.assertEqual(june_count, 1)

    def test_instant_before_release_is_waiting(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 29, 59, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "WAITING_FOR_RELEASE")
        self.run_in_temp(case)

    def test_exact_release_time_allows_capture(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            self.assertEqual(result.status, "CAPTURED")
        self.run_in_temp(case)

    def test_23_hours_59_minutes_after_release_allows_capture(self):
        def case(root):
            now = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc) + timedelta(hours=23, minutes=59)
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=now,
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            self.assertEqual(result.status, "CAPTURED")
        self.run_in_temp(case)

    def test_exactly_24_hours_after_release_allows_capture(self):
        def case(root):
            now = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc) + timedelta(hours=24)
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=now,
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            self.assertEqual(result.status, "CAPTURED")
        self.run_in_temp(case)

    def test_24_hours_and_one_second_after_release_expires(self):
        def case(root):
            now = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc) + timedelta(hours=24, seconds=1)
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=now,
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "CAPTURE_WINDOW_EXPIRED")
        self.run_in_temp(case)

    def test_expired_window_has_zero_bls_calls(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 15, 12, 30, 1, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.api_call_count, 0)
        self.run_in_temp(case)

    def test_expired_window_does_not_create_raw_file(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 15, 12, 30, 1, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "CAPTURE_WINDOW_EXPIRED")
            self.assertFalse((root / "data" / "raw").exists())
        self.run_in_temp(case)

    def test_expired_window_does_not_create_as_released(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 15, 12, 30, 1, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertFalse(capture_cpi_release.release_path(root, "US_CPI_2026_06").exists())
        self.run_in_temp(case)

    def test_may_2026_event_at_current_period_is_expired(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_05",
                now_utc=datetime(2026, 7, 10, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "CAPTURE_WINDOW_EXPIRED")
        self.run_in_temp(case)

    def test_june_2026_event_before_release_is_waiting(self):
        def case(root):
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 10, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "WAITING_FOR_RELEASE")
        self.run_in_temp(case)

    def test_capture_file_records_capture_window_hours(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertEqual(payload["capture_window_hours"], 24)
        self.run_in_temp(case)

    def test_capture_delay_seconds_is_exact(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, 5, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertEqual(payload["capture_delay_seconds"], 65)
        self.run_in_temp(case)

    def test_capture_delay_seconds_is_in_allowed_range(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            payload = json.loads(capture_cpi_release.release_path(root, "US_CPI_2026_06").read_text())
            self.assertGreaterEqual(payload["capture_delay_seconds"], 0)
            self.assertLessEqual(payload["capture_delay_seconds"], 86400)
        self.run_in_temp(case)

    def test_existing_file_still_already_captured_after_window_expired(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            result = capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 16, 12, 31, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(result.status, "ALREADY_CAPTURED")
        self.run_in_temp(case)

    def test_existing_file_not_modified_after_window_expired(self):
        def case(root):
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc),
                collector=lambda r, _now: collect_result(r, "2026-06"),
            )
            path = capture_cpi_release.release_path(root, "US_CPI_2026_06")
            before = path.read_bytes()
            capture_cpi_release.capture_release(
                root,
                "US_CPI_2026_06",
                now_utc=datetime(2026, 7, 16, 12, 31, tzinfo=timezone.utc),
                collector=lambda _root, _now: self.fail("collector should not run"),
            )
            self.assertEqual(before, path.read_bytes())
        self.run_in_temp(case)

    def test_sha256_reproducibility_with_window_metadata(self):
        def case(root):
            event = base_event()
            result = collect_result(root, "2026-06")
            captured_at = datetime(2026, 7, 14, 12, 31, tzinfo=timezone.utc)
            first = capture_cpi_release.build_release_payload(
                event,
                result["processed_payload"],
                "data/raw/bls/cpi/2026-06/retrieved.json",
                captured_at,
            )
            second = capture_cpi_release.build_release_payload(
                event,
                result["processed_payload"],
                "data/raw/bls/cpi/2026-06/retrieved.json",
                captured_at,
            )
            self.assertEqual(first["integrity"]["sha256"], second["integrity"]["sha256"])
        self.run_in_temp(case)


if __name__ == "__main__":
    unittest.main()
