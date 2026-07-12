import copy
import errno
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.pipelines import capture_ppi_consensus_observation as observation
from scripts.providers import trading_economics_calendar as provider


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
RELEASE = "2026-07-15T12:30:00Z"


class ObservationCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.events = self.root / "data" / "calendar" / "events.json"
        self.events.parent.mkdir(parents=True)
        self.events.write_text(json.dumps({"events": [self.event()]}), encoding="utf-8")
        self.output = self.root / "data" / "consensus" / "ppi"

    def tearDown(self):
        self.temporary.cleanup()

    def event(self):
        return {
            "event_id": "US_PPI_2026_06", "indicator_type": "PPI", "country": "US",
            "reference_period": "2026-06", "release_datetime_utc": RELEASE,
            "metrics": {metric: {"expected": None, "unit": "%"} for metric in observation.PPI_METRICS},
        }

    def rows(self, metrics=observation.PPI_METRICS):
        return [{
            "Country": "United States", "Unit": "%", "Metric": metric,
            "ReferencePeriod": "2026-06", "ReleaseDate": RELEASE, "ForecastValue": "0.2",
        } for metric in metrics]

    def fixture_result(self, metrics=observation.PPI_METRICS, *, source="ForecastValue"):
        normalized = provider.normalize(
            self.rows(metrics), event_id="US_PPI_2026_06", reference_period="2026-06",
            release_datetime_utc=RELEASE, retrieved_at_utc="2026-07-12T12:00:00Z",
        )
        return {
            "status": {"complete": "PPI_CONSENSUS_COLLECTED", "partial": "PPI_CONSENSUS_PARTIAL", "unavailable": "PPI_CONSENSUS_UNAVAILABLE"}[normalized["status"]],
            "normalized_status": normalized["status"], "normalized": normalized,
            "raw_payload_sha256": normalized["raw_payload_sha256"], "external_api_called": False,
            "source_field": source, "warnings": [], "provider_event_ids": {"event": "fixture"},
            "provider_tickers": {"headline_mom": "PPI"},
        }

    def capture(self, result, **kwargs):
        return observation.capture_observation(
            "US_PPI_2026_06", root=self.root, events_path=self.events, output_root=self.output,
            now_utc=NOW, collector=lambda *_args, **_kwargs: result, **kwargs,
        )

    def read_observation(self, result):
        return json.loads((self.root / result["observation_path"]).read_text(encoding="utf-8"))

    def test_complete_observation_is_immutable_and_eligible(self):
        result = self.capture(self.fixture_result())
        saved = self.read_observation(result)
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_CAPTURED")
        self.assertTrue(result["observation_created"])
        self.assertTrue(saved["eligible_for_apply"])
        self.assertTrue(saved["immutable"])
        self.assertEqual(set(saved["metrics"]), set(observation.PPI_METRICS))
        self.assertEqual(saved["provenance"]["observation_type"], "pre_release_market_consensus")
        self.assertEqual(saved["integrity"]["sha256"], observation._observation_sha(saved))

    def test_partial_and_unavailable_observations_are_not_eligible(self):
        for metrics, status, missing in [
            (observation.PPI_METRICS[:2], "partial", ["core_mom", "core_yoy"]),
            ((), "unavailable", list(observation.PPI_METRICS)),
        ]:
            with self.subTest(status=status):
                result = self.capture(self.fixture_result(metrics))
                saved = self.read_observation(result)
                self.assertEqual(saved["normalized_status"], status)
                self.assertFalse(saved["eligible_for_apply"])
                self.assertEqual(saved["missing_metrics"], missing)
                self.temporary.cleanup()
                self.setUp()

    def test_observation_excludes_raw_and_prohibited_fields(self):
        result = self.capture(self.fixture_result())
        text = (self.root / result["observation_path"]).read_text(encoding="utf-8")
        for forbidden in ("Actual", "Previous", "TEForecast", "TEForecastValue", "api_key", '"raw_payload"', "secret"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(self.read_observation(result)["source_field"], "ForecastValue")

    def test_same_content_rerun_preserves_file_and_reports_already_exists(self):
        first = self.capture(self.fixture_result())
        path = self.root / first["observation_path"]
        before, modified = path.read_bytes(), path.stat().st_mtime_ns
        second = self.capture(self.fixture_result())
        self.assertEqual(second["status"], "PPI_CONSENSUS_OBSERVATION_ALREADY_EXISTS")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_same_path_different_content_is_a_conflict(self):
        self.capture(self.fixture_result(source="ForecastValue"))
        result = self.capture(self.fixture_result(source="Forecast"))
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_CONFLICT")

    def test_tampered_observation_is_integrity_error(self):
        first = self.capture(self.fixture_result())
        path = self.root / first["observation_path"]
        path.write_text("{}", encoding="utf-8")
        result = self.capture(self.fixture_result())
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")

    def test_key_missing_and_expired_do_not_create_observations(self):
        missing = self.capture({"status": "CONSENSUS_PROVIDER_KEY_MISSING", "external_api_called": False})
        self.assertEqual(missing["status"], "CONSENSUS_PROVIDER_KEY_MISSING")
        self.assertFalse(self.output.exists())
        calls = []
        expired = observation.capture_observation(
            "US_PPI_2026_06", root=self.root, events_path=self.events, output_root=self.output,
            now_utc=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc),
            collector=lambda *_args, **_kwargs: calls.append(True),
        )
        self.assertEqual(expired["status"], "PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED")
        self.assertEqual(calls, [])
        self.assertFalse(self.output.exists())

    def test_calendar_expected_and_snapshot_are_untouched(self):
        before = self.events.read_bytes()
        self.capture(self.fixture_result())
        event = json.loads(self.events.read_text(encoding="utf-8"))["events"][0]
        self.assertEqual(self.events.read_bytes(), before)
        self.assertTrue(all(event["metrics"][metric]["expected"] is None for metric in observation.PPI_METRICS))
        self.assertFalse((self.output / "US_PPI_2026_06" / "consensus_snapshot.json").exists())

    def test_output_paths_and_event_injection_are_rejected(self):
        calls = []
        result = observation.capture_observation(
            "US_PPI_2026_06/evil", root=self.root, events_path=self.events,
            output_root=self.root / "data" / "releases", now_utc=NOW,
            collector=lambda *_args, **_kwargs: calls.append(True),
        )
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
        self.assertEqual(calls, [])
        result = observation.capture_observation(
            "US_PPI_2026_06", root=self.root, events_path=self.events,
            output_root=self.root / "data" / "calendar", now_utc=NOW,
            collector=lambda *_args, **_kwargs: calls.append(True),
        )
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
        self.assertEqual(calls, [])

    def test_symlink_output_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        self.output.parent.mkdir(parents=True)
        try:
            self.output.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = self.capture(self.fixture_result())
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")

    def test_hard_link_fallback_is_exclusive_and_permission_error_is_not_fallback(self):
        with mock.patch.object(observation.os, "link", side_effect=OSError(errno.ENOTSUP, "unsupported")):
            result = self.capture(self.fixture_result())
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_CAPTURED")
        self.temporary.cleanup()
        self.setUp()
        with mock.patch.object(observation.os, "link", side_effect=OSError(errno.EACCES, "denied")):
            result = self.capture(self.fixture_result())
        self.assertEqual(result["status"], "PPI_CONSENSUS_OBSERVATION_WRITE_ERROR")
        self.assertFalse(list(self.root.rglob("*.json"))[1:])

    def test_help_has_required_options_and_no_force(self):
        source = Path(observation.__file__).read_text(encoding="utf-8")
        for option in ("--event-id", "--events", "--output-root", "--now-utc", "--result-json"):
            self.assertIn(option, source)
        self.assertNotIn("--force", source)


if __name__ == "__main__":
    unittest.main()
