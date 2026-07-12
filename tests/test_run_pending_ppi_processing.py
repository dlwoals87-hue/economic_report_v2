from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from scripts.automation import run_pending_ppi_processing as pending
class PendingPpiTests(unittest.TestCase):
 def test_empty_is_no_pending(self):
  with tempfile.TemporaryDirectory() as t:self.assertEqual(pending.run_pending(Path(t))['status'],'NO_PENDING_PPI_EVENT')
