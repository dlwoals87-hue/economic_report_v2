import json, os, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.automation import probe_ppi_consensus_provider as probe

class ProbeTests(unittest.TestCase):
 def setUp(self): self.old=os.environ.pop("TRADING_ECONOMICS_API_KEY",None)
 def tearDown(self):
  if self.old is not None: os.environ["TRADING_ECONOMICS_API_KEY"]=self.old
 def test_key_missing_is_safe(self):
  value=probe.probe("US_PPI_2026_06",now_utc=datetime(2026,7,12,12,tzinfo=timezone.utc))
  self.assertEqual(value["status"],"CONSENSUS_PROVIDER_KEY_MISSING")
  self.assertFalse(value["external_api_called"]); self.assertFalse(value["safe_to_enable_automation"])
 def test_status_mapping_and_secret_free_result(self):
  normal={"status":"PPI_CONSENSUS_COLLECTED","normalized_status":"complete","normalized":{"metrics":{m:{"expected":"0.2"} for m in probe.METRICS},"retrieved_at_utc":"2026-07-12T12:00:00Z"},"reference_period":"2026-06","release_datetime_utc":"2026-07-15T12:30:00Z","raw_payload_sha256":"a"*64}
  value=probe.probe("US_PPI_2026_06",collector=lambda *_a,**_k:normal); self.assertEqual(value["status"],"PPI_CONSENSUS_PROVIDER_PROBE_COMPLETE"); self.assertTrue(value["safe_to_enable_automation"]); self.assertEqual(value["integrity"]["sha256"],probe.stable_sha({**value,"integrity":{}})); self.assertNotIn("raw_payload",json.dumps(value).replace("raw_payload_sha256",""))
 def test_workflow_is_manual_read_only_and_artifact_only(self):
  text=(Path(__file__).resolve().parents[1]/".github/workflows/probe-ppi-consensus-provider.yml").read_text(encoding="utf-8")
  for token in ("name: Probe PPI Consensus Provider","workflow_dispatch:","contents: read","ppi-consensus-provider-probe","retention-days: 7","actions/upload-artifact@v4"): self.assertIn(token,text)
  for token in ("schedule:","workflow_run:","push:","contents: write","git commit","git push","issues: write","pages: write","--apply","--lock"): self.assertNotIn(token,text)
if __name__=="__main__":unittest.main()
