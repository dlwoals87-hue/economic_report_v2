from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import approve_cpi_event_candidate as approve
from scripts.automation import prepare_next_cpi_event as prepare
from tests.test_prepare_next_cpi_event import NOW, existing


class ApproveCpiEventCandidateTests(unittest.TestCase):
    def setup(self):
        temp = tempfile.TemporaryDirectory(); root = Path(temp.name); calendar = root / "data/calendar/events.json"; calendar.parent.mkdir(parents=True); calendar.write_text(json.dumps({"events": [existing("2026-06", "US_CPI_2026_06")]}), encoding="utf-8"); candidate = root / "candidate.json"; prepare.prepare(root, event_id="US_CPI_2026_07", reference_period="2026-07", release_datetime_utc="2026-08-12T12:30:00Z", source="Official schedule", source_checked_at_utc="2026-06-20T11:00:00Z", output=candidate, now=NOW); return temp, root, candidate
    def test_preview_does_not_modify_calendar(self):
        temp, root, candidate = self.setup()
        with temp:
            before = (root / "data/calendar/events.json").read_bytes(); result = approve.approve(root, candidate, mode="preview", now=NOW); self.assertEqual(result.status, "CPI_EVENT_APPROVAL_PREVIEW"); self.assertEqual(before, (root / "data/calendar/events.json").read_bytes())
    def test_apply_registers_candidate_and_is_idempotent(self):
        temp, root, candidate = self.setup()
        with temp:
            result = approve.approve(root, candidate, mode="apply", now=NOW); data = json.loads((root / "data/calendar/events.json").read_text()); self.assertEqual(result.status, "CPI_EVENT_APPROVED"); self.assertEqual(data["events"][-1]["event_id"], "US_CPI_2026_07"); self.assertEqual(approve.approve(root, candidate, mode="apply", now=NOW).status, "CPI_EVENT_ALREADY_REGISTERED")
    def test_candidate_integrity_and_status_are_required(self):
        temp, root, candidate = self.setup()
        with temp:
            data = json.loads(candidate.read_text()); data["integrity"]["sha256"] = "bad"; candidate.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(prepare.CandidateError): approve.approve(root, candidate, mode="preview", now=NOW)
    def test_conflict_and_existing_event_unchanged(self):
        temp, root, candidate = self.setup()
        with temp:
            data = json.loads((root / "data/calendar/events.json").read_text()); data["events"].append({**existing("2026-07", "OTHER")}); (root / "data/calendar/events.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(prepare.CandidateError): approve.approve(root, candidate, mode="apply", now=NOW)
    def test_real_calendar_is_not_touched(self):
        real = Path(__file__).resolve().parents[1] / "data/calendar/events.json"; before = real.read_bytes(); temp, root, candidate = self.setup()
        with temp: approve.approve(root, candidate, mode="preview", now=NOW)
        self.assertEqual(before, real.read_bytes())


if __name__ == "__main__": unittest.main()
