import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.pipelines import apply_ppi_consensus_observation as apply
from scripts.pipelines import capture_ppi_consensus_observation as capture
from scripts.providers import trading_economics_calendar as provider


RELEASE = "2026-07-15T12:30:00Z"


class AutoApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.events = self.root / "data" / "calendar" / "events.json"
        self.events.parent.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "data" / "calendar" / "events.json"
        self.events.write_bytes(source.read_bytes())
        self.observations = self.root / "data" / "consensus" / "ppi"
        self.now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)

    def tearDown(self): self.temporary.cleanup()

    def fixture(self, timestamp, value="0.2", metrics=capture.PPI_METRICS):
        rows = [{"Country":"United States","Unit":"%","Metric":metric,"ReferencePeriod":"2026-06","ReleaseDate":RELEASE,"ForecastValue":value} for metric in metrics]
        normalized = provider.normalize(rows,event_id="US_PPI_2026_06",reference_period="2026-06",release_datetime_utc=RELEASE,retrieved_at_utc=timestamp)
        return {"status":{"complete":"PPI_CONSENSUS_COLLECTED","partial":"PPI_CONSENSUS_PARTIAL","unavailable":"PPI_CONSENSUS_UNAVAILABLE"}[normalized["status"]],"normalized_status":normalized["status"],"normalized":normalized,"source_field":"ForecastValue","warnings":[],"provider_event_ids":{},"provider_tickers":{},"external_api_called":False}

    def capture(self, fixture, now=None):
        return capture.capture_observation("US_PPI_2026_06",root=self.root,events_path=self.events,output_root=self.observations,now_utc=now or self.now,collector=lambda *_args,**_kwargs:fixture)

    def apply_pipeline(self, **kwargs):
        return apply.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.observations,now_utc=self.now,**kwargs)

    def expected(self):
        event=next(item for item in json.loads(self.events.read_text(encoding="utf-8"))["events"] if item["event_id"]=="US_PPI_2026_06")
        return {metric:event["metrics"][metric]["expected"] for metric in capture.PPI_METRICS}

    def test_latest_complete_is_selected_and_preview_does_not_change_calendar(self):
        self.capture(self.fixture("2026-07-12T10:00:00Z","0.1"),datetime(2026,7,12,10,tzinfo=timezone.utc))
        self.capture(self.fixture("2026-07-12T12:00:00Z","0.2"))
        before=self.events.read_bytes(); result=self.apply_pipeline()
        self.assertEqual(result["status"],"PPI_CONSENSUS_AUTO_APPLY_PREVIEW_READY")
        self.assertEqual(result["retrieved_at_utc"],"2026-07-12T12:00:00Z")
        self.assertEqual(set(result["changed_metrics"]),set(capture.PPI_METRICS))
        self.assertEqual(before,self.events.read_bytes())

    def test_partial_unavailable_and_other_event_are_not_selected(self):
        self.capture(self.fixture("2026-07-12T10:00:00Z","0.1",capture.PPI_METRICS[:2]),datetime(2026,7,12,10,tzinfo=timezone.utc))
        self.capture(self.fixture("2026-07-12T12:00:00Z","0.2",()),self.now)
        result=self.apply_pipeline()
        self.assertEqual(result["status"],"PPI_CONSENSUS_NO_ELIGIBLE_OBSERVATION")
        self.assertEqual(self.expected(),{metric:None for metric in capture.PPI_METRICS})

    def test_apply_sets_all_expected_values_and_preserves_other_events(self):
        self.capture(self.fixture("2026-07-12T12:00:00Z","0.2"))
        before=json.loads(self.events.read_text(encoding="utf-8")); result=self.apply_pipeline(apply=True); after=json.loads(self.events.read_text(encoding="utf-8"))
        self.assertEqual(result["status"],"PPI_CONSENSUS_EXPECTED_APPLIED")
        self.assertTrue(result["calendar_changed"])
        self.assertEqual(self.expected(),{metric:"0.2" for metric in capture.PPI_METRICS})
        self.assertEqual(before["events"][:2],after["events"][:2])
        self.assertFalse((self.observations/"US_PPI_2026_06"/"consensus_snapshot.json").exists())

    def test_same_apply_is_idempotent_and_different_expected_is_conflict(self):
        self.capture(self.fixture("2026-07-12T12:00:00Z","0.2")); self.apply_pipeline(apply=True)
        before=self.events.read_bytes(); mtime=self.events.stat().st_mtime_ns
        same=self.apply_pipeline(apply=True)
        self.assertEqual(same["status"],"PPI_CONSENSUS_EXPECTED_ALREADY_APPLIED")
        self.assertEqual(before,self.events.read_bytes()); self.assertEqual(mtime,self.events.stat().st_mtime_ns)
        path=self.observations/"US_PPI_2026_06"/"provider_observations"/"20260712T120000Z.json"
        data=json.loads(path.read_text(encoding="utf-8")); data["metrics"]["headline_mom"]["expected"]="0.3"; data["integrity"]["sha256"]=capture._observation_sha(data); path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
        conflict=self.apply_pipeline()
        self.assertEqual(conflict["status"],"PPI_CONSENSUS_EXPECTED_CONFLICT")
        self.assertEqual(before,self.events.read_bytes())

    def test_invalid_observation_and_release_window_are_blocked(self):
        captured=self.capture(self.fixture("2026-07-12T12:00:00Z")); path=self.root/captured["observation_path"]
        path.write_text("{}",encoding="utf-8")
        self.assertEqual(self.apply_pipeline()["status"],"PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
        before=self.events.read_bytes()
        expired=apply.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.observations,now_utc=datetime(2026,7,15,12,30,tzinfo=timezone.utc))
        self.assertEqual(expired["status"],"PPI_CONSENSUS_AUTO_APPLY_WINDOW_EXPIRED")
        self.assertEqual(before,self.events.read_bytes())

    def test_atomic_write_failure_keeps_calendar_and_no_temp_file(self):
        self.capture(self.fixture("2026-07-12T12:00:00Z")); before=self.events.read_bytes()
        with mock.patch.object(apply.os,"replace",side_effect=OSError("fail")):
            result=self.apply_pipeline(apply=True)
        self.assertEqual(result["status"],"PPI_CONSENSUS_AUTO_APPLY_WRITE_ERROR")
        self.assertEqual(before,self.events.read_bytes())
        self.assertFalse(list(self.events.parent.glob(".events.json.*.tmp")))

    def test_unsafe_paths_and_symlinks_are_blocked(self):
        result=apply.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.root/"data"/"releases",now_utc=self.now)
        self.assertEqual(result["status"],"PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")
        target=self.root/"target"; target.mkdir(); self.observations.parent.mkdir(parents=True,exist_ok=True)
        try: self.observations.symlink_to(target,target_is_directory=True)
        except OSError: self.skipTest("symlinks unavailable")
        result=self.apply_pipeline(); self.assertEqual(result["status"],"PPI_CONSENSUS_AUTO_APPLY_INPUT_INVALID")

    def test_cli_contract_has_no_force_and_result_has_no_secrets(self):
        source=Path(apply.__file__).read_text(encoding="utf-8")
        self.assertNotIn("--force",source)
        result=self.apply_pipeline(); text=json.dumps(result)
        for forbidden in ("TRADING_ECONOMICS_API_KEY","?c=",'"raw_payload"',"secret"):
            self.assertNotIn(forbidden,text)
        self.assertFalse(result["external_api_called"]); self.assertFalse(result["external_ai_api_called"]); self.assertEqual(result["cost"],"free")


if __name__=="__main__": unittest.main()
