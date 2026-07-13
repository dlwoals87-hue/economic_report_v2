from __future__ import annotations
import hashlib
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PpiWorkflowTests(unittest.TestCase):
 def test_capture_workflow_contract(self):
  text=(ROOT/'.github/workflows/capture-ppi-release.yml').read_text(encoding='utf-8')
  for value in ('name: Capture PPI Release','workflow_dispatch:','schedule:','run_due_ppi_capture.py --enable-live-bls','contents: write','concurrency:','actions/checkout@v6','actions/setup-python@v6','actions/upload-artifact@v4','data/releases/ppi/{event_id}/as_released.json') : self.assertIn(value,text)
  for value in ('git add .','git add -A','--force','git push --force'): self.assertNotIn(value,text)
 def test_cpi_workflow_is_present(self):
  self.assertTrue((ROOT/'.github/workflows/capture-cpi-release.yml').is_file())
