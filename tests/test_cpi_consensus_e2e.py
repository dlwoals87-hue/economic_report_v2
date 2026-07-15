from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import process_cpi_release
from scripts.consensus import apply_cpi_consensus_snapshot as apply
from scripts.consensus import cpi_contract as contract
from scripts.pipelines import build_cpi_release_report
from tests.test_build_cpi_release_canonical import EVENT_ID, default_output, read_canonical, write_base_inputs, write_release
from tests.test_build_cpi_release_report import report_output
from tests.test_cpi_consensus_contract import observation


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


class CpiConsensusE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        write_base_inputs(self.root); write_release(self.root)
        events = self.root / "data/calendar/events.json"
        calendar = json.loads(events.read_text(encoding="utf-8")); event = calendar["events"][0]
        evidence = observation()
        evidence["event_id"] = event["event_id"]
        evidence["reference_period"] = event["reference_period"]
        evidence["release_datetime_utc"] = event["release_datetime_utc"]
        evidence["retrieved_at_utc"] = "2026-07-14T11:59:00Z"
        evidence["observed_at_utc"] = "2026-07-14T11:58:00Z"
        evidence["integrity"]["sha256"] = contract.stable_sha256(evidence)
        snapshot = contract.build_snapshot(evidence, event, NOW)
        self.snapshot = contract.snapshot_path(self.root, EVENT_ID); self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        result = apply.run(EVENT_ID, root=self.root, events_path=events, snapshot_path=self.snapshot, now_utc=NOW, apply=True)
        self.assertEqual(result["status"], "CONSENSUS_APPLIED")
    def tearDown(self): self.temp.cleanup()
    def test_01_snapshot_expected_reaches_canonical_and_surprise(self):
        result = process_cpi_release.process_release(self.root, EVENT_ID, now=NOW); self.assertEqual(result.status, "PROCESSED")
        canonical = read_canonical(self.root)
        self.assertEqual(canonical["event"]["headline"]["mom"]["expected"], "0.2")
        self.assertEqual(canonical["event"]["headline"]["mom"]["surprise"]["raw"], "0.1")
        self.assertEqual(canonical["event"]["headline"]["mom"]["actual_as_released_raw"], "0.3")
        self.assertEqual(canonical["event"]["headline"]["mom"]["previous_as_released_raw"], "0.5")
        self.assertEqual(canonical["source"]["consensus_snapshot_sha256"], contract.read_json(self.snapshot)["integrity"]["sha256"])
    def test_02_positive_analysis_uses_validated_consensus_only(self):
        process_cpi_release.process_release(self.root, EVENT_ID, now=NOW)
        analysis = json.loads((self.root / "data/analysis/cpi" / EVENT_ID / "cpi-analysis-v1.json").read_text(encoding="utf-8"))
        self.assertTrue(analysis["facts"]["consensus_available"])
        self.assertNotIn("Bullish", json.dumps(analysis, ensure_ascii=False))
    def test_03_renderer_shows_actual_expected_previous_and_difference(self):
        process_cpi_release.process_release(self.root, EVENT_ID, now=NOW)
        result = build_cpi_release_report.build_report(self.root, EVENT_ID); self.assertEqual(result.status, "REPORT_CREATED")
        document = report_output(self.root).read_text(encoding="utf-8")
        self.assertIn('data-metric="headline_mom"', document)
        for value in ("0.3%", "0.2%", "0.5%", "0.1%p"): self.assertIn(value, document)
    def test_04_actual_project_data_is_not_touched(self):
        actual = Path(__file__).resolve().parents[1] / "data/calendar/events.json"
        before = actual.read_bytes(); self.assertEqual(before, actual.read_bytes())


if __name__ == "__main__": unittest.main()
