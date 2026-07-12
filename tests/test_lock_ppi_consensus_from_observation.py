import json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.pipelines import apply_ppi_consensus_observation as apply
from scripts.pipelines import capture_ppi_consensus_observation as capture
from scripts.pipelines import lock_ppi_consensus_from_observation as auto_lock
from scripts.providers import trading_economics_calendar as provider

NOW=datetime(2026,7,12,12,tzinfo=timezone.utc); RELEASE="2026-07-15T12:30:00Z"

class AutoLockTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.events=self.root/"data/calendar/events.json"; self.events.parent.mkdir(parents=True)
  self.events.write_bytes((Path(__file__).resolve().parents[1]/"data/calendar/events.json").read_bytes()); self.consensus=self.root/"data/consensus/ppi"
 def tearDown(self): self.tmp.cleanup()
 def fixture(self,value="0.2"):
  rows=[{"Country":"United States","Unit":"%","Metric":m,"ReferencePeriod":"2026-06","ReleaseDate":RELEASE,"ForecastValue":value} for m in capture.PPI_METRICS]
  normal=provider.normalize(rows,event_id="US_PPI_2026_06",reference_period="2026-06",release_datetime_utc=RELEASE,retrieved_at_utc="2026-07-12T12:00:00Z")
  return {"status":"PPI_CONSENSUS_COLLECTED","normalized_status":"complete","normalized":normal,"source_field":"ForecastValue","warnings":[],"provider_event_ids":{},"provider_tickers":{}}
 def prepare(self):
  capture.capture_observation("US_PPI_2026_06",root=self.root,events_path=self.events,output_root=self.consensus,now_utc=NOW,collector=lambda *_a,**_k:self.fixture())
  self.assertEqual(apply.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.consensus,now_utc=NOW,apply=True)["status"],"PPI_CONSENSUS_EXPECTED_APPLIED")
 def lock_pipeline(self,lock_requested=False): return auto_lock.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.consensus,snapshot_root=self.consensus,now_utc=NOW,lock_requested=lock_requested)
 def test_preview_lock_schema_and_idempotency(self):
  self.prepare(); before=self.events.read_bytes(); preview=self.lock_pipeline(); self.assertEqual(preview["status"],"PPI_CONSENSUS_AUTO_LOCK_PREVIEW_READY"); self.assertEqual(before,self.events.read_bytes())
  locked=self.lock_pipeline(True); path=self.root/locked["snapshot_path"]; data=json.loads(path.read_text(encoding="utf-8")); self.assertEqual(locked["status"],"PPI_CONSENSUS_SNAPSHOT_LOCKED"); self.assertTrue(data["integrity"]["immutable"]); self.assertEqual(data["observation_provenance"]["provider"],"trading_economics")
  raw,mtime=path.read_bytes(),path.stat().st_mtime_ns; again=self.lock_pipeline(True); self.assertEqual(again["status"],"PPI_CONSENSUS_SNAPSHOT_ALREADY_LOCKED"); self.assertEqual(raw,path.read_bytes()); self.assertEqual(mtime,path.stat().st_mtime_ns)
 def test_expected_not_ready_and_mismatch_do_not_create_snapshot(self):
  result=self.lock_pipeline(); self.assertEqual(result["status"],"PPI_CONSENSUS_EXPECTED_NOT_READY"); self.assertFalse((self.consensus/"US_PPI_2026_06/consensus_snapshot.json").exists())
  self.prepare(); data=json.loads(self.events.read_text(encoding="utf-8")); target=next(e for e in data["events"] if e["event_id"]=="US_PPI_2026_06"); target["metrics"]["headline_mom"]["expected"]="0.3"; self.events.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
  self.assertEqual(self.lock_pipeline()["status"],"PPI_CONSENSUS_EXPECTED_OBSERVATION_MISMATCH")
 def test_window_and_force_contract(self):
  self.prepare(); before=self.events.read_bytes(); expired=auto_lock.run("US_PPI_2026_06",root=self.root,events_path=self.events,observations_root=self.consensus,snapshot_root=self.consensus,now_utc=datetime(2026,7,15,12,30,tzinfo=timezone.utc)); self.assertEqual(expired["status"],"PPI_CONSENSUS_AUTO_LOCK_WINDOW_EXPIRED"); self.assertEqual(before,self.events.read_bytes()); self.assertNotIn("--force",Path(auto_lock.__file__).read_text(encoding="utf-8"))
 def test_result_has_no_secrets_or_external_calls(self):
  value=self.lock_pipeline(); text=json.dumps(value)
  for bad in ("TRADING_ECONOMICS_API_KEY","?c=",'"raw_payload"',"secret"): self.assertNotIn(bad,text)
  self.assertFalse(value["external_api_called"]); self.assertFalse(value["external_ai_api_called"]); self.assertEqual(value["cost"],"free")
if __name__=="__main__": unittest.main()
