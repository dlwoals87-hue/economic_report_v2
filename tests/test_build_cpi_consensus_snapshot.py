from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.consensus import build_cpi_consensus_snapshot as build
from scripts.consensus import cpi_contract as contract
from tests.test_cpi_consensus_contract import EVENT_ID, NOW, event, observation


class BuildCpiConsensusSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.events = self.root / "data/calendar/events.json"; self.events.parent.mkdir(parents=True)
        self.events.write_text(json.dumps({"version": 1, "events": [event()]}, indent=2), encoding="utf-8")
        self.path = self.root / "fixtures/observation.json"; self.path.parent.mkdir(); self.write(observation())
    def tearDown(self): self.temp.cleanup()
    def write(self, value): self.path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    def invoke(self, **kwargs): return build.run(EVENT_ID, root=self.root, events_path=self.events, observation_path=self.path, now_utc=NOW, **kwargs)
    def target(self): return contract.snapshot_path(self.root, EVENT_ID)
    def test_01_complete_preview_is_ready(self): self.assertEqual(self.invoke()["status"], "SNAPSHOT_READY")
    def test_02_preview_creates_no_file(self): self.invoke(); self.assertFalse(self.target().exists())
    def test_03_apply_creates_snapshot(self): self.assertEqual(self.invoke(apply=True)["status"], "SNAPSHOT_CREATED")
    def test_04_apply_snapshot_is_valid(self): self.invoke(apply=True); contract.validate_snapshot(contract.read_json(self.target()), event())
    def test_05_identical_apply_is_already_exists(self): self.invoke(apply=True); self.assertEqual(self.invoke(apply=True)["status"], "SNAPSHOT_ALREADY_EXISTS")
    def test_06_existing_file_is_not_rewritten(self):
        self.invoke(apply=True); before = self.target().read_bytes(); self.invoke(apply=True); self.assertEqual(before, self.target().read_bytes())
    def test_07_different_observation_conflicts(self):
        self.invoke(apply=True); value = observation(); value["provider_name"] = "Other Fixture"; value["integrity"]["sha256"] = contract.stable_sha256(value); self.write(value)
        self.assertEqual(self.invoke(apply=True)["status"], "SNAPSHOT_CONFLICT")
    def test_08_incomplete_stops_before_snapshot(self): self.write(observation(status="INCOMPLETE")); self.assertEqual(self.invoke(apply=True)["status"], "CONSENSUS_INCOMPLETE")
    def test_09_unavailable_stops_before_snapshot(self): self.write(observation(status="UNAVAILABLE")); self.assertEqual(self.invoke(apply=True)["status"], "CONSENSUS_UNAVAILABLE")
    def test_10_after_release_stops_before_snapshot(self):
        value = observation(); value["retrieved_at_utc"] = "2026-09-11T12:30:00Z"; value["integrity"]["sha256"] = contract.stable_sha256(value); self.write(value)
        self.assertEqual(self.invoke(apply=True)["status"], "CONSENSUS_AFTER_RELEASE")
    def test_11_now_after_release_stops_before_snapshot(self):
        self.assertEqual(build.run(EVENT_ID, root=self.root, events_path=self.events, observation_path=self.path, now_utc=datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc), apply=True)["status"], "CONSENSUS_AFTER_RELEASE")
    def test_12_malformed_input_is_invalid(self): self.path.write_text("[]", encoding="utf-8"); self.assertEqual(self.invoke()["status"], "INVALID_INPUT")
    def test_13_unsafe_observation_path_is_invalid(self): self.assertEqual(build.run(EVENT_ID, root=self.root, events_path=self.events, observation_path=Path("..") / "bad.json", now_utc=NOW)["status"], "INVALID_INPUT")
    def test_14_result_has_no_external_calls_or_secrets(self):
        result = self.invoke(); text = json.dumps(result).lower(); self.assertFalse(result["external_api_called"]); self.assertFalse(result["external_ai_api_called"]); self.assertEqual(result["cost"], "free"); self.assertNotIn("api_key", text)
    def test_15_cli_has_no_force(self): self.assertNotIn("--force", Path(build.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__": unittest.main()
