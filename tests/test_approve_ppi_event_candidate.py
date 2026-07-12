from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import approve_ppi_event_candidate as approve
from scripts.automation import prepare_next_ppi_event as prepare


NOW = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
APPROVED_AT = "2026-07-12T11:30:00Z"


class ApprovePpiEventCandidateTests(unittest.TestCase):
    def setup(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        events = root / "data" / "calendar" / "events.json"
        events.parent.mkdir(parents=True)
        events.write_text(json.dumps({"events": []}), encoding="utf-8")
        candidate_root = root / "candidates"
        prepared = prepare.prepare(
            root,
            event_id="US_PPI_2026_07",
            reference_period="2026-07",
            release_datetime_utc="2026-08-13T12:30:00Z",
            source_url="https://www.bls.gov/schedule/news_release/ppi.htm",
            source_checked_at_utc="2026-07-12T11:00:00Z",
            output_root=candidate_root,
            now=NOW,
        )
        return temporary, root, candidate_root / "US_PPI_2026_07.json", events, prepared

    def call(self, candidate: Path, events: Path, **changes):
        values = {
            "approved_by": "calendar-reviewer",
            "approved_at_utc": APPROVED_AT,
            "confirm_event_id": "US_PPI_2026_07",
            "now": NOW,
        }
        values.update(changes)
        return approve.approve(candidate, events, **values)

    def rewrite_candidate(self, candidate: Path, change):
        value = json.loads(candidate.read_text(encoding="utf-8"))
        change(value)
        value["integrity"]["sha256"] = prepare.stable_sha256(value)
        candidate.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_approval_updates_only_fixture_calendar_and_preserves_metadata(self):
        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            candidate_before = candidate.read_bytes()
            result = self.call(candidate, events)
            calendar = json.loads(events.read_text(encoding="utf-8"))
            event = calendar["events"][0]
            self.assertEqual(result.status, "PPI_EVENT_APPROVED")
            self.assertTrue(result.calendar_modified)
            self.assertEqual(result.modified_paths, ("data/calendar/events.json",))
            self.assertEqual(event["indicator_type"], "PPI")
            self.assertEqual(event["consensus_status"], "not_entered")
            self.assertEqual(set(event["metrics"]), set(prepare.PPI_METRICS))
            self.assertTrue(all(metric["expected"] is None for metric in event["metrics"].values()))
            self.assertEqual(event["schedule_source"]["url"], "https://www.bls.gov/schedule/news_release/ppi.htm")
            self.assertEqual(event["approval"]["approved_by"], "calendar-reviewer")
            self.assertEqual(event["source_candidate_sha256"], result.candidate_sha256)
            self.assertEqual(candidate_before, candidate.read_bytes())
            self.assertEqual(list(events.parent.glob(".events.json.*.tmp")), [])
            self.assertFalse(result.external_api_called)
            self.assertFalse(result.external_ai_api_called)
            self.assertEqual(result.cost, "free")

    def test_candidate_validation_rejects_missing_invalid_and_tampered_inputs(self):
        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            with self.assertRaises(approve.PpiApprovalError) as missing:
                self.call(root / "missing.json", events)
            self.assertEqual(missing.exception.code, "PPI_EVENT_CANDIDATE_NOT_FOUND")

            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(approve.PpiApprovalError) as invalid:
                self.call(invalid_json, events)
            self.assertEqual(invalid.exception.code, "PPI_EVENT_CANDIDATE_INVALID")

        for change, code in (
            (lambda value: value.update({"indicator_type": "CPI"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value.update({"country": "KR"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value.update({"event_id": "US_PPI_2026_08"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value.update({"release_datetime_kst": "2026-08-13T12:30:00+09:00"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value["schedule_source"].update({"url": ""}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value["approval"].update({"status": "approved"}), "PPI_EVENT_APPROVAL_FIELDS_INVALID"),
            (lambda value: value["metrics"]["headline_mom"].update({"expected": "0.1"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value["metrics"]["headline_mom"].update({"actual": "0.1"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value["metrics"]["headline_mom"].update({"previous": "0.1"}), "PPI_EVENT_CANDIDATE_INVALID"),
            (lambda value: value["metrics"]["headline_mom"].update({"surprise": "0.1"}), "PPI_EVENT_CANDIDATE_INVALID"),
        ):
            temporary, root, candidate, events, _ = self.setup()
            with temporary:
                self.rewrite_candidate(candidate, change)
                with self.subTest(code=code), self.assertRaises(approve.PpiApprovalError) as raised:
                    self.call(candidate, events)
                self.assertEqual(raised.exception.code, code)

    def test_integrity_confirmation_and_approval_fields_are_required(self):
        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            value = json.loads(candidate.read_text(encoding="utf-8"))
            value["integrity"]["sha256"] = "bad"
            candidate.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(approve.PpiApprovalError) as bad_sha:
                self.call(candidate, events)
            self.assertEqual(bad_sha.exception.code, "PPI_EVENT_CANDIDATE_INTEGRITY_ERROR")

            self.rewrite_candidate(candidate, lambda value: None)
            for changes in (
                {"confirm_event_id": None},
                {"confirm_event_id": "US_PPI_2026_08"},
                {"approved_by": ""},
                {"approved_by": "reviewer\n"},
                {"approved_at_utc": "2026-07-12T11:30:00"},
                {"approved_at_utc": "2026-07-12T12:01:00Z"},
            ):
                with self.subTest(changes=changes), self.assertRaises(approve.PpiApprovalError):
                    self.call(candidate, events, **changes)

    def test_idempotency_conflicts_and_cpi_same_time(self):
        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            self.assertEqual(self.call(candidate, events).status, "PPI_EVENT_APPROVED")
            self.assertEqual(
                self.call(candidate, events, approved_at_utc="2026-07-12T11:45:00Z").status,
                "PPI_EVENT_ALREADY_APPROVED",
            )

            alternate = root / "alternate.json"
            altered = json.loads(candidate.read_text(encoding="utf-8"))
            altered["schedule_source"]["url"] = "https://www.bls.gov/alternate"
            altered["integrity"]["sha256"] = prepare.stable_sha256(altered)
            alternate.write_text(json.dumps(altered), encoding="utf-8")
            self.assertEqual(self.call(alternate, events).status, "PPI_EVENT_APPROVAL_CONFLICT")

        for calendar_event in (
            {"event_id": "OTHER", "indicator_type": "PPI", "country": "US", "reference_period": "2026-07", "release_datetime_utc": "2026-07-14T12:30:00Z"},
            {"event_id": "OTHER", "indicator_type": "PPI", "country": "US", "reference_period": "2026-06", "release_datetime_utc": "2026-08-13T12:30:00Z"},
        ):
            temporary, root, candidate, events, _ = self.setup()
            with temporary:
                events.write_text(json.dumps({"events": [calendar_event]}), encoding="utf-8")
                before = events.read_bytes()
                self.assertEqual(self.call(candidate, events).status, "PPI_EVENT_ALREADY_REGISTERED")
                self.assertEqual(before, events.read_bytes())

        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            events.write_text(json.dumps({"events": [{"event_id": "US_CPI_2026_07", "indicator_type": "CPI", "country": "US", "reference_period": "2026-07", "release_datetime_utc": "2026-08-13T12:30:00Z", "metrics": {key: {"expected": None, "unit": "%"} for key in prepare.PPI_METRICS}, "consensus_status": "not_entered", "consensus_source": None, "entered_at_utc": None}]}), encoding="utf-8")
            self.assertEqual(self.call(candidate, events).status, "PPI_EVENT_APPROVED")

    def test_cli_without_inputs_is_safe_and_real_calendar_is_unchanged(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = approve.main([])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue().strip(), "PPI_EVENT_APPROVAL_INPUT_REQUIRED")

        real = Path(__file__).resolve().parents[1] / "data" / "calendar" / "events.json"
        before = real.read_bytes()
        temporary, root, candidate, events, _ = self.setup()
        with temporary:
            self.call(candidate, events)
        self.assertEqual(before, real.read_bytes())


if __name__ == "__main__":
    unittest.main()
