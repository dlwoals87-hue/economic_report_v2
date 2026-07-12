from __future__ import annotations
import unittest
from datetime import datetime, timezone
from scripts.pipelines import capture_ppi_release as capture
from scripts.pipelines import build_ppi_release_canonical as canonical
from tests.test_capture_ppi_release import event,response

class PpiLiveCanonicalTests(unittest.TestCase):
 def test_live_release_maps_actual_and_null_consensus(self):
  e=event(); series,_=capture.bls_ppi.parse_bls_response(response()); metrics=capture.bls_ppi.build_metrics(series,"2026-05"); release=capture.build_payload(e,metrics,datetime(2026,6,11,12,31,tzinfo=timezone.utc)); value=canonical.build_canonical(release,"US_PPI_2026_05")
  self.assertEqual(value['metrics']['headline_mom']['actual_display'],'1.0%'); self.assertIsNone(value['metrics']['headline_mom']['expected_raw']); self.assertFalse(value['provenance']['not_as_released'])
