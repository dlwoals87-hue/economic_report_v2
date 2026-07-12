from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.automation import prepare_next_ppi_event as prepare


NOW = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)


def registered_ppi(
    event_id: str = "US_PPI_2026_06",
    reference_period: str = "2026-06",
    release_datetime_utc: str = "2026-07-14T12:30:00Z",
) -> dict:
    return {
        "event_id": event_id,
        "indicator_type": "PPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": release_datetime_utc,
    }


class PrepareNextPpiEventTests(unittest.TestCase):
    def root(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        calendar = root / "data" / "calendar" / "events.json"
        calendar.parent.mkdir(parents=True)
        calendar.write_text(json.dumps({"events": []}), encoding="utf-8")
        return temporary, root

    def call(self, root: Path, **changes):
        values = {
            "event_id": None,
            "reference_period": "2026-07",
            "release_datetime_utc": "2026-08-13T12:30:00Z",
            "source_url": "https://www.bls.gov/schedule/news_release/ppi.htm",
            "source_checked_at_utc": "2026-07-12T11:00:00Z",
            "output_root": root / "candidates",
            "now": NOW,
        }
        values.update(changes)
        return prepare.prepare(root, **values)

    def test_candidate_creation_has_ppi_contract_and_integrity(self):
        temporary, root = self.root()
        with temporary:
            result = self.call(root)
            path = root / "candidates" / "US_PPI_2026_07.json"
            candidate = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result.status, "PPI_EVENT_CANDIDATE_CREATED")
            self.assertEqual(result.event_id, "US_PPI_2026_07")
            self.assertEqual(candidate["indicator_type"], "PPI")
            self.assertEqual(candidate["country"], "US")
            self.assertEqual(candidate["release_datetime_kst"], "2026-08-13T21:30:00+09:00")
            self.assertEqual(candidate["approval"], {"status": "candidate", "approved_by": None, "approved_at_utc": None})
            self.assertEqual(candidate["consensus_status"], "not_entered")
            self.assertTrue(all(value["expected"] is None for value in candidate["metrics"].values()))
            self.assertEqual(candidate["integrity"]["sha256"], prepare.stable_sha256(candidate))
            self.assertFalse(result.calendar_modified)
            self.assertEqual(result.created_paths, ("candidates/US_PPI_2026_07.json",))

    def test_event_id_is_generated_or_validated(self):
        temporary, root = self.root()
        with temporary:
            self.assertEqual(self.call(root).event_id, "US_PPI_2026_07")
            other = self.call(root, event_id="US_PPI_2026_07")
            self.assertEqual(other.status, "PPI_EVENT_CANDIDATE_ALREADY_EXISTS")
            with self.assertRaises(prepare.PpiEventCandidateError):
                self.call(root, event_id="US_PPI_2026_08")

    def test_invalid_identity_and_schedule_inputs_are_rejected(self):
        temporary, root = self.root()
        with temporary:
            invalid = (
                {"event_id": "US_CPI_2026_07"},
                {"event_id": "US_PPI_2026_08"},
                {"reference_period": "2026-13"},
                {"release_datetime_utc": "2026-08-13T12:30:00"},
                {"source_checked_at_utc": "2026-07-12T11:00:00"},
                {"release_datetime_utc": "2026-07-01T12:30:00Z"},
                {"source_checked_at_utc": "2026-08-13T12:30:00Z"},
                {"source_url": ""},
                {"source_url": "ftp://example.test/ppi"},
            )
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(prepare.PpiEventCandidateError):
                    self.call(root, **changes)

    def test_candidate_is_idempotent_and_conflicts_do_not_overwrite(self):
        temporary, root = self.root()
        with temporary:
            first = self.call(root)
            candidate = root / "candidates" / "US_PPI_2026_07.json"
            before = candidate.read_bytes()
            self.assertEqual(first.status, "PPI_EVENT_CANDIDATE_CREATED")
            self.assertEqual(self.call(root).status, "PPI_EVENT_CANDIDATE_ALREADY_EXISTS")
            self.assertEqual(
                self.call(root, source_url="https://www.bls.gov/another-schedule").status,
                "PPI_EVENT_CANDIDATE_CONFLICT",
            )
            self.assertEqual(before, candidate.read_bytes())

    def test_hard_link_unsupported_uses_exclusive_create_fallback(self):
        temporary, root = self.root()
        unsupported = OSError(0, "unsupported", None, 1)
        with temporary, patch.object(prepare.os, "link", side_effect=unsupported):
            result = self.call(root)
            self.assertEqual(result.status, "PPI_EVENT_CANDIDATE_CREATED")
            self.assertTrue((root / "candidates" / "US_PPI_2026_07.json").is_file())

    def test_hard_link_permission_error_is_not_hidden_by_fallback(self):
        temporary, root = self.root()
        with temporary, patch.object(prepare.os, "link", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.call(root)
            self.assertFalse((root / "candidates" / "US_PPI_2026_07.json").exists())

    def test_registered_ppi_duplicates_are_blocked(self):
        cases = (
            registered_ppi(event_id="US_PPI_2026_07"),
            registered_ppi(event_id="OTHER", reference_period="2026-07"),
            registered_ppi(event_id="OTHER", release_datetime_utc="2026-08-13T12:30:00Z"),
        )
        for event in cases:
            temporary, root = self.root()
            with temporary:
                calendar = root / "data" / "calendar" / "events.json"
                calendar.write_text(json.dumps({"events": [event]}), encoding="utf-8")
                result = self.call(root)
                self.assertEqual(result.status, "PPI_EVENT_ALREADY_REGISTERED")
                self.assertFalse((root / "candidates").exists())

    def test_cpi_calendar_event_does_not_conflict(self):
        temporary, root = self.root()
        with temporary:
            calendar = root / "data" / "calendar" / "events.json"
            calendar.write_text(
                json.dumps({"events": [{**registered_ppi(), "event_id": "US_CPI_2026_07", "indicator_type": "CPI"}]}),
                encoding="utf-8",
            )
            self.assertEqual(self.call(root).status, "PPI_EVENT_CANDIDATE_CREATED")

    def test_candidate_has_no_release_values_or_auto_approval(self):
        temporary, root = self.root()
        with temporary:
            self.call(root)
            candidate = json.loads((root / "candidates" / "US_PPI_2026_07.json").read_text(encoding="utf-8"))
            serialized = json.dumps(candidate, sort_keys=True)
            for forbidden in ("actual", "previous", "surprise", "--force"):
                self.assertNotIn(forbidden, serialized)
            self.assertEqual(candidate["approval"]["status"], "candidate")
            self.assertIsNone(candidate["approval"]["approved_by"])
            self.assertIsNone(candidate["approval"]["approved_at_utc"])

    def test_cli_without_schedule_input_is_safe(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = prepare.main([])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue().strip(), "PPI_EVENT_INPUT_REQUIRED")

    def test_real_calendar_is_not_modified(self):
        real = Path(__file__).resolve().parents[1] / "data" / "calendar" / "events.json"
        before = real.read_bytes()
        temporary, root = self.root()
        with temporary:
            self.call(root)
        self.assertEqual(before, real.read_bytes())


if __name__ == "__main__":
    unittest.main()
