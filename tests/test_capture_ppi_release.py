from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.pipelines import capture_ppi_release as capture


NOW = datetime(2026, 6, 11, 12, 31, tzinfo=timezone.utc)


def event(release="2026-06-11T12:30:00Z"):
    return {"event_id":"US_PPI_2026_05","indicator_type":"PPI","country":"US","reference_period":"2026-05","release_datetime_utc":release,"metrics":{key:{"expected":None} for key in capture.METRICS},"consensus_status":"not_entered","consensus_source":None,"entered_at_utc":None}


def response(value="101"):
    values={"WPSFD4":{"2026-05":value,"2026-04":"100"},"WPUFD4":{"2026-05":"106","2025-05":"100"},"WPSFD49116":{"2026-05":"100.5","2026-04":"100"},"WPUFD49116":{"2026-05":"105","2025-05":"100"}}
    return {"status":"REQUEST_SUCCEEDED","Results":{"series":[{"seriesID":series,"data":[{"year":period[:4],"period":"M"+period[5:],"value":value} for period,value in rows.items()]} for series,rows in values.items()]}}


class PpiCaptureTests(unittest.TestCase):
    def test_live_bls_default_is_disabled(self):
        self.assertFalse(inspect.signature(capture.capture_release).parameters["use_live_bls"].default)

    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"project"; events=root/"events.json"; events.parent.mkdir(); events.write_text(json.dumps({"events":[event()]}),encoding="utf-8")
            callback(root, events, Path(temporary)/"out")

    def test_waiting_does_not_call_or_write(self):
        def case(root, events, out):
            result=capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW-timedelta(minutes=2),response=response())
            self.assertEqual(result.status,"WAITING_FOR_RELEASE"); self.assertFalse(result.api_called); self.assertFalse(out.exists())
        self.run_in_temp(case)

    def test_capture_payload_and_idempotency(self):
        def case(root, events, out):
            first=capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW,response=response())
            second=capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW,response=response())
            payload=json.loads(Path(first.as_released_path).read_text(encoding="utf-8"))
            self.assertEqual(first.status,"CAPTURED"); self.assertEqual(second.status,"ALREADY_CAPTURED")
            self.assertEqual(set(payload["metrics"]),set(capture.METRICS)); self.assertEqual(payload["provenance"]["data_origin"],"live_release_capture"); self.assertFalse(payload["provenance"]["not_as_released"])
        self.run_in_temp(case)

    def test_expired_missing_and_conflict_are_blocked(self):
        def case(root, events, out):
            self.assertEqual(capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW+timedelta(hours=25),response=response()).status,"CAPTURE_WINDOW_EXPIRED")
            missing=response(); missing["Results"]["series"][0]["data"][0]["year"]="2026"; missing["Results"]["series"][0]["data"][0]["period"]="M06"
            self.assertEqual(capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW,response=missing).status,"DATA_NOT_AVAILABLE_YET")
            capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW,response=response())
            self.assertEqual(capture.capture_release(root,"US_PPI_2026_05",events_path=events,output_root=out,now_utc=NOW,response=response("103")).status,"CAPTURE_CONFLICT")
        self.run_in_temp(case)
