from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import run_due_ppi_capture as due


class DuePpiTests(unittest.TestCase):
    def test_no_due_and_multiple_due(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/"data/calendar").mkdir(parents=True); path=root/"data/calendar/events.json"
            path.write_text(json.dumps({"events":[]}),encoding="utf-8")
            self.assertEqual(due.run_due_capture(root,now_utc=datetime(2026,1,1,tzinfo=timezone.utc))[0]["status"],"NO_DUE_PPI_EVENT")
            events=[{"event_id":f"US_PPI_2026_0{i}","indicator_type":"PPI","release_datetime_utc":"2026-01-01T00:00:00Z"} for i in (1,2)]
            path.write_text(json.dumps({"events":events}),encoding="utf-8")
            self.assertEqual(due.run_due_capture(root,now_utc=datetime(2026,1,1,tzinfo=timezone.utc))[0]["status"],"MULTIPLE_DUE_PPI_EVENTS")

    def test_due_requires_opt_in_and_forwards_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/"data/calendar").mkdir(parents=True); path=root/"data/calendar/events.json"
            event={"event_id":"US_PPI_2026_01","indicator_type":"PPI","country":"US","reference_period":"2026-01","release_datetime_utc":"2026-01-01T00:00:00Z"}
            path.write_text(json.dumps({"events":[event]}),encoding="utf-8")
            disabled,_=due.run_due_capture(root,now_utc=datetime(2026,1,1,tzinfo=timezone.utc))
            self.assertEqual(disabled["status"],"PPI_LIVE_BLS_NOT_ENABLED"); self.assertFalse(disabled["api_called"]); self.assertFalse(disabled["commit_paths"])
            calls=[]
            class Result:
                def payload(self): return {"status":"DATA_NOT_AVAILABLE_YET","event_id":event["event_id"],"api_called":False}
            def fake(*args, **kwargs): calls.append(kwargs); return Result()
            enabled,_=due.run_due_capture(root,now_utc=datetime(2026,1,1,tzinfo=timezone.utc),enable_live_bls=True,capture_func=fake)
            self.assertEqual(enabled["status"],"DATA_NOT_AVAILABLE_YET"); self.assertEqual(calls,[{"now_utc":datetime(2026,1,1,tzinfo=timezone.utc),"use_live_bls":True}])
