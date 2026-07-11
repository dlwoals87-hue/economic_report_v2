from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import lock_cpi_consensus as consensus


EVENT_ID = "US_CPI_2026_06"
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def event(values: dict[str, object] | None = None) -> dict[str, object]:
    expected = values or {key: None for key in consensus.CPI_METRICS}
    complete = all(value is not None for value in expected.values())
    return {
        "event_id": EVENT_ID,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": "2026-06",
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "metrics": {key: {"expected": value, "unit": "%"} for key, value in expected.items()},
        "consensus_source": "Trusted survey" if complete else None,
        "consensus_status": "complete" if complete else "not_entered",
        "entered_at_utc": "2026-07-14T11:00:00Z" if complete else None,
    }


class LockCpiConsensusTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory(prefix="consensus-lock-") as temp:
            root = Path(temp)
            self.write_event(root, event())
            return callback(root)

    def write_event(self, root: Path, payload: dict[str, object]) -> None:
        path = root / "data/calendar/events.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "events": [payload]}, indent=2) + "\n", encoding="utf-8")

    def lock(self, root: Path, now: datetime = NOW):
        return consensus.lock_consensus(root, EVENT_ID, now)

    def complete_values(self) -> dict[str, str]:
        return {"headline_mom": "0.25", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"}

    def snapshot(self, root: Path) -> Path:
        return consensus.snapshot_path(root, EVENT_ID)

    def test_01_all_null_is_not_ready(self):
        self.run_in_temp(lambda root: self.assertEqual(self.lock(root).status, "CONSENSUS_NOT_READY"))

    def test_02_all_null_creates_no_snapshot(self):
        self.run_in_temp(lambda root: (self.lock(root), self.assertFalse(self.snapshot(root).exists())))

    def test_03_partial_values_are_not_locked(self):
        def case(root):
            self.write_event(root, event({"headline_mom": "0.2", "headline_yoy": None, "core_mom": None, "core_yoy": None}))
            self.assertEqual(self.lock(root).status, "CONSENSUS_PARTIAL")
        self.run_in_temp(case)

    def test_04_complete_values_create_snapshot(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            result = self.lock(root)
            self.assertEqual(result.status, "CONSENSUS_LOCKED")
            self.assertTrue(result.snapshot_created)
            self.assertTrue(self.snapshot(root).is_file())
        self.run_in_temp(case)

    def test_05_complete_status_is_required(self):
        def case(root):
            payload = event(self.complete_values())
            payload["consensus_status"] = "partial"
            self.write_event(root, payload)
            with self.assertRaises(consensus.ConsensusLockError):
                self.lock(root)
        self.run_in_temp(case)

    def test_06_source_is_required(self):
        def case(root):
            payload = event(self.complete_values())
            payload["consensus_source"] = None
            self.write_event(root, payload)
            with self.assertRaises(consensus.ConsensusLockError):
                self.lock(root)
        self.run_in_temp(case)

    def test_07_entered_at_is_required(self):
        def case(root):
            payload = event(self.complete_values())
            payload["entered_at_utc"] = None
            self.write_event(root, payload)
            with self.assertRaises(consensus.ConsensusLockError):
                self.lock(root)
        self.run_in_temp(case)

    def test_08_timezone_naive_entered_at_is_rejected(self):
        def case(root):
            payload = event(self.complete_values())
            payload["entered_at_utc"] = "2026-07-14T11:00:00"
            self.write_event(root, payload)
            with self.assertRaises(consensus.ConsensusLockError):
                self.lock(root)
        self.run_in_temp(case)

    def test_09_entered_at_after_release_is_rejected(self):
        def case(root):
            payload = event(self.complete_values())
            payload["entered_at_utc"] = "2026-07-14T12:31:00Z"
            self.write_event(root, payload)
            with self.assertRaises(consensus.ConsensusLockError):
                self.lock(root)
        self.run_in_temp(case)

    def test_10_release_window_expired(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.assertEqual(self.lock(root, datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)).status, "CONSENSUS_LOCK_WINDOW_EXPIRED")
            self.assertFalse(self.snapshot(root).exists())
        self.run_in_temp(case)

    def test_11_lock_immediately_before_release_is_allowed(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            result = self.lock(root, datetime(2026, 7, 14, 12, 29, 59, tzinfo=timezone.utc))
            self.assertEqual(result.status, "CONSENSUS_LOCKED")
        self.run_in_temp(case)

    def test_12_all_metrics_are_mapped(self):
        def case(root):
            values = self.complete_values()
            self.write_event(root, event(values))
            self.lock(root)
            payload = consensus.read_json(self.snapshot(root))
            self.assertEqual({key: value["expected_raw"] for key, value in payload["metrics"].items()}, values)
        self.run_in_temp(case)

    def test_13_display_uses_round_half_up(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            self.assertEqual(consensus.read_json(self.snapshot(root))["metrics"]["headline_mom"]["expected_display"], "0.3%")
        self.run_in_temp(case)

    def test_14_snapshot_is_marked_immutable(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            self.assertTrue(consensus.read_json(self.snapshot(root))["integrity"]["immutable"])
        self.run_in_temp(case)

    def test_15_sha256_is_reproducible(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            payload = consensus.read_json(self.snapshot(root))
            self.assertEqual(payload["integrity"]["sha256"], consensus.stable_sha256(payload))
        self.run_in_temp(case)

    def test_16_second_identical_run_is_already_locked(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            self.assertEqual(self.lock(root, NOW.replace(minute=1)).status, "CONSENSUS_ALREADY_LOCKED")
        self.run_in_temp(case)

    def test_17_changed_value_is_lock_conflict(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            values = self.complete_values()
            values["headline_mom"] = "0.3"
            self.write_event(root, event(values))
            self.assertEqual(self.lock(root, NOW.replace(minute=1)).status, "CONSENSUS_LOCK_CONFLICT")
        self.run_in_temp(case)

    def test_18_existing_snapshot_is_not_modified(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            before = self.snapshot(root).read_bytes()
            self.lock(root, NOW.replace(minute=1))
            self.assertEqual(before, self.snapshot(root).read_bytes())
        self.run_in_temp(case)

    def test_19_snapshot_never_contains_key_or_token(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            text = self.snapshot(root).read_text(encoding="utf-8").lower()
            self.assertNotIn("api_key", text)
            self.assertNotIn("token", text)
        self.run_in_temp(case)

    def test_20_snapshot_never_contains_absolute_path(self):
        def case(root):
            self.write_event(root, event(self.complete_values()))
            self.lock(root)
            self.assertNotIn(str(root).replace("\\", "/"), self.snapshot(root).read_text(encoding="utf-8"))
        self.run_in_temp(case)

    def test_21_fixture_does_not_write_to_project_consensus_directory(self):
        self.run_in_temp(lambda root: (self.write_event(root, event(self.complete_values())), self.lock(root)))
        self.assertFalse((Path(__file__).resolve().parents[1] / "data/consensus/cpi/US_CPI_2026_06").exists())


if __name__ == "__main__":
    unittest.main()
