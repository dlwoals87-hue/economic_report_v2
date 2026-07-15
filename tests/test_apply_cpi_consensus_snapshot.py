from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.consensus import apply_cpi_consensus_snapshot as apply
from scripts.consensus import cpi_contract as contract
from tests.test_cpi_consensus_contract import EVENT_ID, NOW, event, observation


class ApplyCpiConsensusSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.events = self.root / "data/calendar/events.json"; self.events.parent.mkdir(parents=True)
        self.events.write_text(json.dumps({"version": 1, "events": [event()]}, indent=2) + "\n", encoding="utf-8")
        self.snapshot = contract.snapshot_path(self.root, EVENT_ID); self.snapshot.parent.mkdir(parents=True)
        value = contract.build_snapshot(observation(), event(), NOW); self.snapshot.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    def tearDown(self): self.temp.cleanup()
    def invoke(self, **kwargs): return apply.run(EVENT_ID, root=self.root, events_path=self.events, snapshot_path=self.snapshot, now_utc=NOW, **kwargs)
    def calendar_event(self): return json.loads(self.events.read_text(encoding="utf-8"))["events"][0]
    def test_01_preview_is_ready(self): self.assertEqual(self.invoke()["status"], "CONSENSUS_APPLY_READY")
    def test_02_preview_does_not_modify_calendar(self): before=self.events.read_bytes(); self.invoke(); self.assertEqual(before,self.events.read_bytes())
    def test_03_apply_projects_all_expected(self):
        self.assertEqual(self.invoke(apply=True)["status"], "CONSENSUS_APPLIED"); self.assertEqual({key:self.calendar_event()["metrics"][key]["expected"] for key in contract.CPI_METRICS},{key:"0.2" for key in contract.CPI_METRICS})
    def test_04_apply_records_snapshot_provenance(self):
        self.invoke(apply=True); value=self.calendar_event(); self.assertEqual(value["consensus_snapshot_path"], f"data/consensus/cpi/{EVENT_ID}/consensus_snapshot.json"); self.assertEqual(value["consensus_snapshot_sha256"], contract.read_json(self.snapshot)["integrity"]["sha256"])
    def test_05_apply_is_idempotent(self): self.invoke(apply=True); self.assertEqual(self.invoke(apply=True)["status"], "CONSENSUS_ALREADY_APPLIED")
    def test_06_noop_does_not_rewrite_calendar(self): self.invoke(apply=True); before=self.events.read_bytes(); self.invoke(apply=True); self.assertEqual(before,self.events.read_bytes())
    def test_07_existing_expected_is_conflict(self):
        value=self.calendar_event(); value["metrics"]["headline_mom"]["expected"]="0.1"; value["consensus_status"]="partial"; self.events.write_text(json.dumps({"version":1,"events":[value]},indent=2),encoding="utf-8")
        self.assertEqual(self.invoke()["status"],"CONSENSUS_APPLY_CONFLICT")
    def test_08_invalid_snapshot_is_invalid_input(self): self.snapshot.write_text("{}",encoding="utf-8"); self.assertEqual(self.invoke()["status"],"INVALID_INPUT")
    def test_09_after_release_is_not_applied(self): self.assertEqual(apply.run(EVENT_ID,root=self.root,events_path=self.events,snapshot_path=self.snapshot,now_utc=datetime(2026,9,11,12,30,tzinfo=timezone.utc),apply=True)["status"],"CONSENSUS_AFTER_RELEASE")
    def test_10_unsafe_snapshot_path_is_invalid(self): self.assertEqual(apply.run(EVENT_ID,root=self.root,events_path=self.events,snapshot_path=Path("..")/"bad.json",now_utc=NOW)["status"],"INVALID_INPUT")
    def test_11_partial_snapshot_is_invalid_input(self):
        value=contract.read_json(self.snapshot); value["metrics"]["core_yoy"]["expected_raw"]=None; value["metrics"]["core_yoy"]["expected_display"]=None; value["integrity"]["sha256"]=contract.stable_sha256(value); self.snapshot.write_text(json.dumps(value),encoding="utf-8")
        self.assertEqual(self.invoke()["status"],"INVALID_INPUT")
    def test_12_result_has_no_external_calls(self): result=self.invoke(); self.assertFalse(result["external_api_called"]); self.assertFalse(result["external_ai_api_called"]); self.assertEqual(result["cost"],"free")
    def test_13_cli_has_no_force(self): self.assertNotIn("--force",Path(apply.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__": unittest.main()
