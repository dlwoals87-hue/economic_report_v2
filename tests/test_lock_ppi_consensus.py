from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import lock_ppi_consensus as lock


EVENT_ID = "US_PPI_2026_06"
NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)


def event(complete: bool = True, indicator: str = "PPI") -> dict:
    values = {"headline_mom": "0.2", "headline_yoy": "2.4", "core_mom": "0.1", "core_yoy": "2.7"}
    return {"event_id": EVENT_ID, "indicator_type": indicator, "country": "US", "reference_period": "2026-06", "release_datetime_utc": "2026-07-15T12:30:00Z", "metrics": {key: {"expected": value if complete else None, "unit": "%"} for key, value in values.items()}, "consensus_status": "complete" if complete else "not_entered", "consensus_source": "Reuters" if complete else None, "entered_at_utc": "2026-07-13T11:00:00Z" if complete else None, "source_observed_at_utc": "2026-07-13T11:00:00Z"}


class LockPpiConsensusTests(unittest.TestCase):
    def setup(self, payload=None):
        temporary = tempfile.TemporaryDirectory(); root = Path(temporary.name); path = root / "data/calendar/events.json"; path.parent.mkdir(parents=True); path.write_text(json.dumps({"events": [payload or event()]}), encoding="utf-8"); return temporary, root, path

    def call(self, root, path, **changes):
        values = {"event_id": EVENT_ID, "events_path": path, "output_root": root / "data/consensus/ppi", "locked_at_utc": "2026-07-13T11:30:00Z", "now_utc": NOW}; values.update(changes); return lock.lock_consensus(root, **values)

    def test_create_snapshot_and_preserve_calendar(self):
        temporary, root, path = self.setup()
        with temporary:
            before = path.read_bytes(); result = self.call(root, path); snapshot = root / "data/consensus/ppi" / EVENT_ID / "consensus_snapshot.json"; data = json.loads(snapshot.read_text())
            self.assertEqual(result.status, "PPI_CONSENSUS_SNAPSHOT_CREATED"); self.assertEqual(data["indicator_type"], "PPI"); self.assertEqual(data["metrics"]["headline_mom"]["expected_raw"], "0.2"); self.assertEqual(data["source_calendar_sha256"], lock.sha256_bytes(before)); self.assertTrue(data["integrity"]["immutable"]); self.assertEqual(data["integrity"]["sha256"], lock.stable_sha256(data)); self.assertEqual(before, path.read_bytes())

    def test_idempotency_conflict_and_integrity_error(self):
        temporary, root, path = self.setup()
        with temporary:
            self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_SNAPSHOT_CREATED"); self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_SNAPSHOT_ALREADY_EXISTS")
            snapshot = root / "data/consensus/ppi" / EVENT_ID / "consensus_snapshot.json"; before = snapshot.read_bytes(); data = json.loads(before); data["integrity"]["sha256"] = "bad"; snapshot.write_text(json.dumps(data), encoding="utf-8"); self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_SNAPSHOT_INTEGRITY_ERROR"); self.assertNotEqual(before, snapshot.read_bytes())

    def test_not_ready_expired_and_non_ppi_are_blocked(self):
        temporary, root, path = self.setup(event(complete=False))
        with temporary: self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_NOT_READY_TO_LOCK")
        temporary, root, path = self.setup()
        with temporary: self.assertEqual(self.call(root, path, now_utc=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)).status, "PPI_CONSENSUS_LOCK_WINDOW_EXPIRED")
        temporary, root, path = self.setup(event(indicator="CPI"))
        with temporary:
            with self.assertRaises(lock.PpiConsensusLockError): self.call(root, path)

    def test_hard_link_fallback_and_permission_error(self):
        temporary, root, path = self.setup()
        with temporary, mock.patch.object(lock.os, "link", side_effect=OSError(0, "unsupported", None, 1)):
            self.assertEqual(self.call(root, path).status, "PPI_CONSENSUS_SNAPSHOT_CREATED")
        temporary, root, path = self.setup()
        with temporary, mock.patch.object(lock.os, "link", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError): self.call(root, path)

    def test_no_force_and_real_snapshot_is_not_created(self):
        self.assertNotIn("--force", Path(lock.__file__).read_text(encoding="utf-8"))
        self.assertFalse((Path(__file__).resolve().parents[1] / "data/consensus/ppi/US_PPI_2026_06/consensus_snapshot.json").exists())

