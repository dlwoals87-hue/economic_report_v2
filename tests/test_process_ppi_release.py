from __future__ import annotations
import json, shutil, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.pipelines import capture_ppi_release as capture
from scripts.automation import process_ppi_release as process
from tests.test_capture_ppi_release import event,response
ROOT=Path(__file__).resolve().parents[1]
class ProcessPpiTests(unittest.TestCase):
 def test_process_index_and_resume(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t); (root/'data/releases/ppi/US_PPI_2026_05').mkdir(parents=True); (root/'docs').mkdir(); shutil.copy2(ROOT/'docs/index.html',root/'docs/index.html')
   series,_=capture.bls_ppi.parse_bls_response(response()); payload=capture.build_payload(event(),capture.bls_ppi.build_metrics(series,'2026-05'),datetime(2026,6,11,12,31,tzinfo=timezone.utc)); (root/'data/releases/ppi/US_PPI_2026_05/as_released.json').write_text(json.dumps(payload),encoding='utf-8')
   first=process.process(root,'US_PPI_2026_05'); self.assertEqual(first['status'],'PROCESSED_AND_INDEXED'); self.assertIn('US_PPI_2026_05',(root/'docs/index.html').read_text(encoding='utf-8'))
   self.assertEqual(process.process(root,'US_PPI_2026_05')['status'],'ALREADY_PROCESSED')
   index=root/'docs/index.html'; index.write_text((ROOT/'docs/index.html').read_text(encoding='utf-8'),encoding='utf-8')
   resumed=process.process(root,'US_PPI_2026_05'); self.assertEqual(resumed['status'],'INDEX_ONLY_RESUMED'); self.assertEqual(resumed['commit_paths'],['docs/index.html'])
