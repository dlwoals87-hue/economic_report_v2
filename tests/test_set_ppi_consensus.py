from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import set_ppi_consensus as entry


EVENT_ID = "US_PPI_2026_06"
NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
VALUES = {"headline_mom": "0.2", "headline_yoy": "2.4", "core_mom": "0.1", "core_yoy": "2.7"}


def ppi_event(event_id: str = EVENT_ID, indicator_type: str = "PPI") -> dict:
    return {
        "event_id": event_id,
        "indicator_type": indicator_type,
        "country": "US",
        "reference_period": "2026-06",
        "release_datetime_utc": "2026-07-15T12:30:00Z",
        "metrics": {key: {"expected": None, "unit": "%"} for key in entry.PPI_METRICS},
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
        "approval": {"status": "approved", "approved_by": "reviewer", "approved_at_utc": "2026-07-12T08:09:20Z"},
    }


class SetPpiConsensusTests(unittest.TestCase):
    def setup(self, events: list[dict] | None = None):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        path = root / "data" / "calendar" / "events.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 1, "events": events or [ppi_event()]}, indent=2) + "\n", encoding="utf-8")
        return temporary, root, path

    def call(self, root: Path, events_path: Path, **changes):
        values = {
            "event_id": EVENT_ID,
            "metric_values": VALUES,
            "source": "Reuters",
            "source_observed_at_utc": "2026-07-13T11:00:00Z",
            "mode": "apply",
            "now_utc": NOW,
            "events_path": events_path,
        }
        values.update(changes)
        return entry.set_consensus(root, **values)

    def read_event(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))["events"][0]

    def test_preview_returns_complete_values_without_writing(self):
        temporary, root, path = self.setup()
        with temporary:
            before = path.read_bytes()
            result = self.call(root, path, mode="preview")
            self.assertEqual(result.status, "PPI_CONSENSUS_PREVIEW")
            self.assertFalse(result.file_modified)
            self.assertEqual(result.before_sha256, entry.sha256_bytes(before))
            self.assertIsNone(result.after_sha256)
            self.assertEqual(result.metrics["headline_mom"]["expected"], "0.2")
            self.assertEqual(before, path.read_bytes())

    def test_apply_updates_only_expected_consensus_and_source_fields(self):
        temporary, root, path = self.setup()
        with temporary:
            original = self.read_event(path)
            result = self.call(root, path)
            event = self.read_event(path)
            self.assertEqual(result.status, "PPI_CONSENSUS_APPLIED")
            self.assertTrue(result.file_modified)
            self.assertEqual(event["consensus_status"], "complete")
            self.assertEqual(event["consensus_source"], "Reuters")
            self.assertEqual(event["entered_at_utc"], "2026-07-13T11:00:00Z")
            self.assertEqual({key: event["metrics"][key]["expected"] for key in entry.PPI_METRICS}, VALUES)
            self.assertEqual(event["approval"], original["approval"])
            self.assertEqual(event["release_datetime_utc"], original["release_datetime_utc"])
            self.assertEqual(result.next_action, "5.3F-2")

    def test_idempotency_conflict_and_snapshot_lock_do_not_write(self):
        temporary, root, path = self.setup()
        with temporary:
            self.call(root, path)
            before = path.read_bytes()
            self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_ALREADY_APPLIED")
            self.assertEqual(self.call(root, path, metric_values={**VALUES, "core_yoy": "2.8"}).status, "PPI_CONSENSUS_CONFLICT")
            self.assertEqual(before, path.read_bytes())

        temporary, root, path = self.setup()
        with temporary:
            snapshot = root / "data" / "consensus" / "ppi" / EVENT_ID / "consensus_snapshot.json"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("{}", encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_LOCKED")
            self.assertEqual(before, path.read_bytes())

    def test_expired_and_non_ppi_events_are_blocked(self):
        temporary, root, path = self.setup()
        with temporary:
            self.assertEqual(self.call(root, path, now_utc=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)).status, "PPI_CONSENSUS_ENTRY_WINDOW_EXPIRED")

        temporary, root, path = self.setup([ppi_event(indicator_type="CPI")])
        with temporary:
            with self.assertRaises(entry.PpiConsensusError):
                self.call(root, path)

    def test_metric_source_and_time_validation(self):
        invalid_values = (
            {**VALUES, "headline_mom": "0.2%"},
            {**VALUES, "headline_mom": "1,2"},
            {**VALUES, "headline_mom": "NaN"},
            {**VALUES, "headline_mom": "Infinity"},
            {**VALUES, "headline_mom": "11"},
            {"headline_mom": "0.2"},
        )
        for metric_values in invalid_values:
            temporary, root, path = self.setup()
            with temporary, self.subTest(metric_values=metric_values), self.assertRaises(entry.PpiConsensusError):
                self.call(root, path, metric_values=metric_values)

        for changes in (
            {"source": ""},
            {"source": "https://example.test"},
            {"source": "api_key=secret"},
            {"source_observed_at_utc": "2026-07-13T11:00:00"},
            {"source_observed_at_utc": "2026-07-13T13:00:00Z"},
            {"source_observed_at_utc": "2026-07-15T12:30:00Z"},
        ):
            temporary, root, path = self.setup()
            with temporary, self.subTest(changes=changes), self.assertRaises(entry.PpiConsensusError):
                self.call(root, path, **changes)

    def test_atomic_failure_preserves_original_bytes(self):
        temporary, root, path = self.setup()
        with temporary:
            before = path.read_bytes()
            with mock.patch.object(entry.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    self.call(root, path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(list(path.parent.glob(".events.json.*.tmp")), [])

    def test_no_force_or_real_calendar_write(self):
        self.assertNotIn("--force", Path(entry.__file__).read_text(encoding="utf-8"))
        real = Path(__file__).resolve().parents[1] / "data" / "calendar" / "events.json"
        before = real.read_bytes()
        temporary, root, path = self.setup()
        with temporary:
            self.call(root, path, mode="preview")
        self.assertEqual(before, real.read_bytes())


if __name__ == "__main__":
    unittest.main()
