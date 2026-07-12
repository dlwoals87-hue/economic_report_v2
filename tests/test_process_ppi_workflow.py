from __future__ import annotations
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ProcessPpiWorkflowTests(unittest.TestCase):
 def test_contract(self):
  text=(ROOT/'.github/workflows/process-ppi-release.yml').read_text()
  for item in ('name: Process PPI Release','workflow_dispatch:','workflow_run:','Capture PPI Release','conclusion == \'success\'','ref: main','run_pending_ppi_processing.py','contents: write','concurrency:','actions/upload-artifact@v4'):self.assertIn(item,text)
  for item in ('git add .','git add -A','git push --force','--force'):self.assertNotIn(item,text)
