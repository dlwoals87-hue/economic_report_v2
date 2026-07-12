from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.diagnostics import check_ppi_release_readiness as readiness


EVENT_ID = "US_PPI_2026_06"
NOW = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)


def event(complete=False):
    return {"event_id": EVENT_ID, "indicator_type": "PPI", "country": "US", "reference_period": "2026-06", "release_datetime_utc": "2026-07-15T12:30:00Z", "metrics": {key: {"expected": "0.2" if complete else None, "unit": "%"} for key in readiness.PPI_METRICS}, "consensus_status": "complete" if complete else "not_entered", "consensus_source": "Reuters" if complete else None, "entered_at_utc": "2026-07-12T11:00:00Z" if complete else None, "schedule_source": {"url": "https://www.bls.gov/schedule/news_release/ppi.htm", "checked_at_utc": "2026-07-12T07:52:03Z"}, "approval": {"status": "approved", "approved_by": "reviewer", "approved_at_utc": "2026-07-12T08:09:20Z"}}


class PpiReadinessTests(unittest.TestCase):
    def setup(self, complete=False):
        temporary = tempfile.TemporaryDirectory(); root = Path(temporary.name); (root / "data/calendar").mkdir(parents=True); (root / "data/calendar/events.json").write_text(json.dumps({"events":[event(complete)]}),encoding="utf-8"); return temporary, root
    def test_not_entered_is_warning_and_overall_pass(self):
        temporary, root = self.setup()
        with temporary:
            result = readiness.check_readiness(root, EVENT_ID, now_utc=NOW, static_checks=lambda *_: [])
            self.assertEqual(result.status,"READINESS_PASS"); self.assertEqual(result.capture_readiness,"READY"); self.assertEqual(result.consensus_readiness,"CONSENSUS_NOT_READY"); self.assertFalse(result.blocking_errors); self.assertIn("expected values", " ".join(result.warnings))
    def test_complete_unlocked_and_locked_states(self):
        temporary, root = self.setup(complete=True)
        with temporary:
            result=readiness.check_readiness(root,EVENT_ID,now_utc=NOW,static_checks=lambda *_:[]); self.assertEqual(result.consensus_readiness,"CONSENSUS_COMPLETE_UNLOCKED")
            snapshot=root/"data/consensus/ppi"/EVENT_ID/"consensus_snapshot.json"; snapshot.parent.mkdir(parents=True); snapshot.write_text(json.dumps(readiness.snapshot_for_test(event(True))),encoding="utf-8")
            self.assertEqual(readiness.check_readiness(root,EVENT_ID,now_utc=NOW,static_checks=lambda *_:[]).consensus_readiness,"CONSENSUS_LOCKED")
    def test_invalid_snapshot_and_expired_missing_release_are_blocking(self):
        temporary, root = self.setup(complete=True)
        with temporary:
            snapshot=root/"data/consensus/ppi"/EVENT_ID/"consensus_snapshot.json"; snapshot.parent.mkdir(parents=True); snapshot.write_text("{}",encoding="utf-8")
            self.assertEqual(readiness.check_readiness(root,EVENT_ID,now_utc=NOW,static_checks=lambda *_:[]).status,"READINESS_FAIL")
            snapshot.unlink(); result=readiness.check_readiness(root,EVENT_ID,now_utc=datetime(2026,7,16,13,tzinfo=timezone.utc),static_checks=lambda *_:[]); self.assertEqual(result.time_state,"CAPTURE_WINDOW_EXPIRED"); self.assertEqual(result.status,"READINESS_FAIL")
    def test_static_errors_are_blocking_and_diagnostic_does_not_write(self):
        temporary, root = self.setup()
        with temporary:
            before=(root/"data/calendar/events.json").read_bytes(); result=readiness.check_readiness(root,EVENT_ID,now_utc=NOW,static_checks=lambda *_:["collector missing"]); self.assertEqual(result.status,"READINESS_FAIL"); self.assertEqual(before,(root/"data/calendar/events.json").read_bytes()); self.assertFalse(result.external_api_called); self.assertFalse(result.external_ai_api_called)

