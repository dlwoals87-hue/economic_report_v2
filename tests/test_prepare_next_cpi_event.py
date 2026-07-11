from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import prepare_next_cpi_event as prepare


NOW = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def existing(period: str, event_id: str) -> dict:
    return {"event_id": event_id, "indicator_type": "CPI", "country": "US", "reference_period": period, "release_datetime_utc": "2026-07-14T12:30:00Z", "metrics": {key: {"expected": None, "unit": "%"} for key in prepare.METRICS}, "consensus_source": None, "consensus_status": "not_entered", "entered_at_utc": None}


class PrepareNextCpiEventTests(unittest.TestCase):
    def root(self):
        temp = tempfile.TemporaryDirectory(); root = Path(temp.name); path = root / "data/calendar/events.json"; path.parent.mkdir(parents=True); path.write_text(json.dumps({"events": [existing("2026-06", "US_CPI_2026_06")]}), encoding="utf-8"); return temp, root
    def call(self, root, **kwargs):
        values = {"event_id": "US_CPI_2026_07", "reference_period": "2026-07", "release_datetime_utc": "2026-08-12T12:30:00Z", "source": "Official schedule", "source_checked_at_utc": "2026-06-20T11:00:00Z", "output": root / "candidate.json", "now": NOW}; values.update(kwargs); return prepare.prepare(root, **values)
    def test_candidate_creation_and_fields(self):
        temp, root = self.root()
        with temp:
            result = self.call(root); data = json.loads((root / "candidate.json").read_text())
            self.assertEqual(result.status, "CPI_EVENT_CANDIDATE_CREATED"); self.assertEqual(data["event"]["release_datetime_kst"], "2026-08-12T21:30:00+09:00"); self.assertEqual(data["event"]["consensus_status"], "not_entered"); self.assertTrue(all(item["expected"] is None for item in data["event"]["metrics"].values()))
    def test_sha_and_source_are_saved(self):
        temp, root = self.root()
        with temp:
            self.call(root); data = json.loads((root / "candidate.json").read_text()); self.assertEqual(data["integrity"]["sha256"], prepare.stable_sha256(data)); self.assertEqual(data["schedule_source"]["name"], "Official schedule")
    def test_identical_and_conflict(self):
        temp, root = self.root()
        with temp:
            self.call(root); self.assertEqual(self.call(root).status, "CPI_EVENT_CANDIDATE_ALREADY_EXISTS")
            with self.assertRaises(prepare.CandidateError): self.call(root, source="Different")
    def test_duplicate_event_and_reference_are_rejected(self):
        temp, root = self.root()
        with temp:
            with self.assertRaises(prepare.CandidateError): self.call(root, event_id="US_CPI_2026_06", reference_period="2026-06")
    def test_sequence_gap_and_previous_are_rejected(self):
        temp, root = self.root()
        with temp:
            for period, event_id in (("2026-08", "US_CPI_2026_08"), ("2026-05", "US_CPI_2026_05")):
                with self.assertRaises(prepare.CandidateError): self.call(root, reference_period=period, event_id=event_id)
    def test_time_and_source_validation(self):
        temp, root = self.root()
        with temp:
            for changes in ({"release_datetime_utc": "2026-08-12T12:30:00"}, {"release_datetime_utc": "2026-06-01T12:30:00Z"}, {"source": ""}, {"source": "https://x/?token=x"}, {"source_checked_at_utc": "2026-08-12T12:30:00Z"}):
                with self.assertRaises(prepare.CandidateError): self.call(root, **changes)
    def test_real_calendar_is_not_modified(self):
        real = Path(__file__).resolve().parents[1] / "data/calendar/events.json"; before = real.read_bytes(); temp, root = self.root()
        with temp: self.call(root)
        self.assertEqual(before, real.read_bytes())


if __name__ == "__main__": unittest.main()
