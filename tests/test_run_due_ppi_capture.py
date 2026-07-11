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
