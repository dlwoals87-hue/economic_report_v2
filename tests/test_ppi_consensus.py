import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.collectors import ppi_consensus


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
RELEASE = "2026-07-15T12:30:00Z"


class PpiConsensusCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.events = self.root / "data" / "calendar" / "events.json"
        self.events.parent.mkdir(parents=True)
        self.calendar = {"version": 1, "events": [self.event()]}
        self.write_calendar()
        self.old_key = os.environ.pop("TRADING_ECONOMICS_API_KEY", None)

    def tearDown(self):
        if self.old_key is not None:
            os.environ["TRADING_ECONOMICS_API_KEY"] = self.old_key
        self.temporary.cleanup()

    def event(self):
        return {
            "event_id": "US_PPI_2026_06",
            "indicator_type": "PPI",
            "country": "US",
            "reference_period": "2026-06",
            "release_datetime_utc": RELEASE,
            "metrics": {metric: {"expected": None, "unit": "%"} for metric in ppi_consensus.PPI_METRICS},
            "consensus_status": "not_entered",
        }

    def write_calendar(self):
        self.events.write_text(json.dumps(self.calendar), encoding="utf-8")

    def rows(self, metrics=ppi_consensus.PPI_METRICS, **extra):
        return [
            {
                "Country": "United States",
                "Unit": "%",
                "Metric": metric,
                "ReferencePeriod": "2026-06",
                "ReleaseDate": RELEASE,
                "ForecastValue": "0.2",
                **extra,
            }
            for metric in metrics
        ]

    def collect(self, **kwargs):
        now_utc = kwargs.pop("now_utc", NOW)
        return ppi_consensus.collect("US_PPI_2026_06", root=self.root, events_path=self.events, now_utc=now_utc, **kwargs)

    def test_cli_options_create_key_missing_result_json(self):
        result_path = self.root / "result.json"
        code = ppi_consensus.main([
            "--event-id", "US_PPI_2026_06", "--events", str(self.events),
            "--now-utc", "2026-07-12T12:00:00Z", "--result-json", str(result_path),
        ])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "CONSENSUS_PROVIDER_KEY_MISSING")
        self.assertFalse(result["external_api_called"])
        self.assertFalse(result["external_ai_api_called"])
        self.assertEqual(result["cost"], "free")

    def test_key_missing_does_not_call_provider_or_expose_key(self):
        calls = []
        result = self.collect(provider_fetcher=lambda _key: calls.append(True))
        self.assertEqual(result["status"], "CONSENSUS_PROVIDER_KEY_MISSING")
        self.assertEqual(calls, [])
        self.assertNotIn("TRADING_ECONOMICS_API_KEY", json.dumps(result))
        self.assertNotIn("raw_payload", result)

    def test_result_json_is_stable_and_uses_atomic_replace(self):
        path = self.root / "result.json"
        result = self.collect()
        with mock.patch.object(ppi_consensus.os, "replace", wraps=os.replace) as replace:
            ppi_consensus.write_result(path, self.root, result)
        first = path.read_bytes()
        ppi_consensus.write_result(path, self.root, result)
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(path.read_bytes(), first)
        self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_atomic_write_failure_preserves_previous_result(self):
        path = self.root / "result.json"
        path.write_bytes(b"previous-result")
        with mock.patch.object(ppi_consensus.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                ppi_consensus.write_result(path, self.root, self.collect())
        self.assertEqual(path.read_bytes(), b"previous-result")
        self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_explicit_external_operations_result_folder_is_allowed(self):
        operations = self.root.parent / "economic_report_v2_ppi_ops"
        operations.mkdir(exist_ok=True)
        self.assertTrue(ppi_consensus.safe_result_path(operations / "result.json", self.root))

    def test_result_path_rejects_traversal_and_operational_data(self):
        result = self.collect()
        unsafe = [
            self.root / ".." / "outside.json",
            self.events,
            self.root / "data" / "consensus" / "ppi" / "output.json",
            self.root / "data" / "releases" / "ppi" / "output.json",
        ]
        for path in unsafe:
            with self.subTest(path=path):
                with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
                    ppi_consensus.write_result(path, self.root, result)

    def test_result_path_rejects_symlink_file_and_parent(self):
        target = self.root / "target.json"
        target.write_text("{}", encoding="utf-8")
        link = self.root / "linked.json"
        parent_target = self.root / "parent-target"
        parent_target.mkdir()
        parent_link = self.root / "linked-parent"
        try:
            link.symlink_to(target)
            parent_link.symlink_to(parent_target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = self.collect()
        for path in (link, parent_link / "result.json"):
            with self.subTest(path=path):
                with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
                    ppi_consensus.write_result(path, self.root, result)

    def test_complete_partial_and_unavailable_statuses(self):
        cases = [
            (self.rows(), "PPI_CONSENSUS_COLLECTED", "complete"),
            (self.rows(ppi_consensus.PPI_METRICS[:2]), "PPI_CONSENSUS_PARTIAL", "partial"),
            ([], "PPI_CONSENSUS_UNAVAILABLE", "unavailable"),
        ]
        for rows, status, normalized_status in cases:
            with self.subTest(status=status):
                result = self.collect(api_key="test-key", provider_fetcher=lambda _key, rows=rows: rows)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["normalized_status"], normalized_status)

    def test_complete_result_preserves_one_response_and_integrity(self):
        calls = []
        response = self.rows()

        def fetcher(key):
            calls.append(key)
            return response

        result = self.collect(api_key="test-key", provider_fetcher=fetcher)
        self.assertEqual(calls, ["test-key"])
        self.assertEqual(set(result["metrics"]), set(ppi_consensus.PPI_METRICS))
        self.assertEqual(result["retrieved_at_utc"], "2026-07-12T12:00:00Z")
        self.assertEqual(len(result["raw_payload_sha256"]), 64)
        self.assertEqual(len(result["normalized_sha256"]), 64)
        self.assertEqual(result["provider_data_type"], "market_consensus")

    def test_actual_previous_and_teforecast_never_supply_expected(self):
        actual_rows = self.rows(ForecastValue=None, Actual="0.2", Previous="0.1")
        actual = self.collect(api_key="test-key", provider_fetcher=lambda _key: actual_rows)
        self.assertEqual(actual["status"], "PPI_CONSENSUS_UNAVAILABLE")
        te_rows = self.rows(ForecastValue=None, TEForecast="0.2")
        te_result = self.collect(api_key="test-key", provider_fetcher=lambda _key: te_rows)
        self.assertEqual(te_result["status"], "PPI_CONSENSUS_PROHIBITED_TEFORECAST")

    def test_release_window_and_naive_time_block_provider(self):
        calls = []
        expired = ppi_consensus.collect(
            "US_PPI_2026_06", root=self.root, events_path=self.events,
            now_utc=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc),
            api_key="test-key", provider_fetcher=lambda _key: calls.append(True),
        )
        self.assertEqual(expired["status"], "PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED")
        self.assertEqual(calls, [])
        with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
            self.collect(now_utc=datetime(2026, 7, 12, 12, 0))

    def test_invalid_missing_duplicate_and_cpi_events_are_blocked(self):
        with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
            ppi_consensus.collect("invalid", root=self.root, events_path=self.events, now_utc=NOW)
        self.calendar["events"].append(copy.deepcopy(self.calendar["events"][0]))
        self.write_calendar()
        with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
            self.collect()
        self.calendar["events"] = [self.event()]
        self.calendar["events"][0]["indicator_type"] = "CPI"
        self.write_calendar()
        with self.assertRaises(ppi_consensus.PpiConsensusCollectorError):
            self.collect()

    def test_calendar_bytes_expected_and_snapshots_remain_unchanged(self):
        before = self.events.read_bytes()
        result = self.collect()
        after = self.events.read_bytes()
        event = json.loads(after)["events"][0]
        self.assertEqual(result["status"], "CONSENSUS_PROVIDER_KEY_MISSING")
        self.assertEqual(before, after)
        self.assertTrue(all(event["metrics"][metric]["expected"] is None for metric in ppi_consensus.PPI_METRICS))
        self.assertFalse((self.root / "data" / "consensus" / "ppi" / "US_PPI_2026_06").exists())


if __name__ == "__main__":
    unittest.main()
