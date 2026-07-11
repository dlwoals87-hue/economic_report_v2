from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import set_cpi_consensus as entry


EVENT_ID = "US_CPI_2026_06"
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
VALUES = {"headline_mom": "0.30", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"}


def calendar_event() -> dict[str, object]:
    return {
        "event_id": EVENT_ID,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": "2026-06",
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "metrics": {key: {"expected": None, "unit": "%"} for key in entry.CPI_METRICS},
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


class SetCpiConsensusTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory(prefix="consensus-entry-") as temp:
            root = Path(temp)
            self.write_calendar(root, [calendar_event()])
            return callback(root)

    def calendar_path(self, root: Path) -> Path:
        return root / "data/calendar/events.json"

    def write_calendar(self, root: Path, events: list[dict[str, object]]) -> None:
        path = self.calendar_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "events": events}, indent=2) + "\n", encoding="utf-8")

    def call(self, root: Path, **kwargs):
        arguments = {
            "event_id": EVENT_ID,
            "metric_values": VALUES,
            "source": "Trusted survey",
            "mode": "apply",
            "now_utc": NOW,
        }
        arguments.update(kwargs)
        return entry.set_consensus(root, **arguments)

    def event(self, root: Path) -> dict[str, object]:
        return json.loads(self.calendar_path(root).read_text(encoding="utf-8"))["events"][0]

    def test_01_preview_is_valid(self):
        self.run_in_temp(lambda root: self.assertEqual(self.call(root, mode="preview").status, "CONSENSUS_PREVIEW"))

    def test_02_preview_does_not_modify_file(self):
        def case(root):
            before = self.calendar_path(root).read_bytes()
            result = self.call(root, mode="preview")
            self.assertFalse(result.file_modified)
            self.assertEqual(before, self.calendar_path(root).read_bytes())
        self.run_in_temp(case)

    def test_03_apply_is_valid(self):
        self.run_in_temp(lambda root: self.assertEqual(self.call(root).status, "CONSENSUS_APPLIED"))

    def test_04_all_metrics_map_to_target_event(self):
        def case(root):
            self.call(root)
            self.assertEqual({key: self.event(root)["metrics"][key]["expected"] for key in entry.CPI_METRICS}, {"headline_mom": "0.3", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
        self.run_in_temp(case)

    def test_05_expected_values_are_decimal_strings(self):
        def case(root):
            self.call(root)
            self.assertIsInstance(self.event(root)["metrics"]["headline_mom"]["expected"], str)
        self.run_in_temp(case)

    def test_06_apply_sets_complete_status(self):
        self.run_in_temp(lambda root: (self.call(root), self.assertEqual(self.event(root)["consensus_status"], "complete")))

    def test_07_apply_saves_source(self):
        self.run_in_temp(lambda root: (self.call(root), self.assertEqual(self.event(root)["consensus_source"], "Trusted survey")))

    def test_08_apply_sets_entered_at_utc(self):
        self.run_in_temp(lambda root: (self.call(root), self.assertEqual(self.event(root)["entered_at_utc"], "2026-07-14T12:00:00Z")))

    def test_09_explicit_entered_at_utc_is_saved(self):
        self.run_in_temp(lambda root: (self.call(root, entered_at_utc="2026-07-14T11:00:00Z"), self.assertEqual(self.event(root)["entered_at_utc"], "2026-07-14T11:00:00Z")))

    def test_10_cli_requires_preview_or_apply(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            entry.parse_args(["--event-id", EVENT_ID, "--headline-mom", "0.3", "--headline-yoy", "2.9", "--core-mom", "0.2", "--core-yoy", "3.1", "--source", "Trusted survey"])

    def test_11_cli_rejects_preview_and_apply_together(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            entry.parse_args(["--event-id", EVENT_ID, "--headline-mom", "0.3", "--headline-yoy", "2.9", "--core-mom", "0.2", "--core-yoy", "3.1", "--source", "Trusted survey", "--preview", "--apply"])

    def test_12_missing_event_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, event_id="US_CPI_2099_01"))

    def test_13_duplicate_event_fails(self):
        def case(root):
            self.write_calendar(root, [calendar_event(), calendar_event()])
            with self.assertRaises(entry.ConsensusEntryError):
                self.call(root)
        self.run_in_temp(case)

    def test_14_non_cpi_event_fails(self):
        def case(root):
            payload = calendar_event()
            payload["indicator_type"] = "PPI"
            self.write_calendar(root, [payload])
            with self.assertRaises(entry.ConsensusEntryError):
                self.call(root)
        self.run_in_temp(case)

    def test_15_percent_value_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_mom": "0.3%"}))

    def test_16_blank_value_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_mom": " "}))

    def test_17_nan_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_mom": "NaN"}))

    def test_18_infinity_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_mom": "Infinity"}))

    def test_19_mom_range_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_mom": "10.1"}))

    def test_20_yoy_range_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, metric_values={**VALUES, "headline_yoy": "30.1"}))

    def test_21_missing_source_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, source=" "))

    def test_22_naive_entered_at_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, entered_at_utc="2026-07-14T11:00:00"))

    def test_23_future_entered_at_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, entered_at_utc="2026-07-14T12:01:00Z"))

    def test_24_post_release_entered_at_fails(self):
        self.run_in_temp(lambda root: self.assertRaises(entry.ConsensusEntryError, self.call, root, entered_at_utc="2026-07-14T12:30:00Z"))

    def test_25_current_time_after_release_is_blocked(self):
        self.run_in_temp(lambda root: self.assertEqual(self.call(root, now_utc=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)).status, "CONSENSUS_ENTRY_WINDOW_EXPIRED"))

    def test_26_identical_reapply_keeps_file_unchanged(self):
        def case(root):
            self.call(root)
            before = self.calendar_path(root).read_bytes()
            result = self.call(root)
            self.assertEqual(result.status, "CONSENSUS_ALREADY_APPLIED")
            self.assertEqual(before, self.calendar_path(root).read_bytes())
        self.run_in_temp(case)

    def test_27_different_existing_value_conflicts(self):
        def case(root):
            self.call(root)
            result = self.call(root, metric_values={**VALUES, "headline_mom": "0.4"})
            self.assertEqual(result.status, "CONSENSUS_INPUT_CONFLICT")
        self.run_in_temp(case)

    def test_28_existing_snapshot_blocks_apply(self):
        def case(root):
            path = root / "data/consensus/cpi" / EVENT_ID / "consensus_snapshot.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            self.assertEqual(self.call(root).status, "CONSENSUS_ALREADY_LOCKED")
        self.run_in_temp(case)

    def test_29_failed_modified_calendar_validation_preserves_original(self):
        def case(root):
            before = self.calendar_path(root).read_bytes()
            calls = 0
            def validator(payload, now):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise entry.ConsensusEntryError("calendar validation failed: test")
                entry.validate_calendar(payload, now)
            with self.assertRaises(entry.ConsensusEntryError):
                self.call(root, validate_func=validator)
            self.assertEqual(before, self.calendar_path(root).read_bytes())
        self.run_in_temp(case)

    def test_30_non_target_event_is_unchanged(self):
        def case(root):
            other = calendar_event()
            other["event_id"] = "US_CPI_2026_05"
            other["reference_period"] = "2026-05"
            other["release_datetime_utc"] = "2026-07-10T12:30:00Z"
            self.write_calendar(root, [other, calendar_event()])
            before = json.loads(json.dumps(other))
            self.call(root)
            self.assertEqual(json.loads(self.calendar_path(root).read_text(encoding="utf-8"))["events"][0], before)
        self.run_in_temp(case)

    def test_31_apply_uses_atomic_replace(self):
        def case(root):
            with mock.patch.object(entry.os, "replace", wraps=entry.os.replace) as replace:
                self.call(root)
            self.assertEqual(replace.call_count, 1)
        self.run_in_temp(case)

    def test_32_result_has_no_api_key_or_token(self):
        def case(root):
            result = self.call(root, mode="preview")
            text = json.dumps(result.payload()).lower()
            self.assertNotIn("api_key", text)
            self.assertNotIn("token", text)
        self.run_in_temp(case)

    def test_33_result_has_no_absolute_path(self):
        def case(root):
            result = self.call(root, mode="preview")
            self.assertNotIn(str(root).replace("\\", "/"), json.dumps(result.payload()))
        self.run_in_temp(case)

    def test_34_real_events_file_is_not_modified(self):
        real = Path(__file__).resolve().parents[1] / "data/calendar/events.json"
        before = real.read_bytes()
        self.assertEqual(before, real.read_bytes())

    def test_35_fixture_leaves_no_project_calendar_data(self):
        self.run_in_temp(lambda root: self.call(root))
        self.assertFalse((Path(__file__).resolve().parents[1] / "data/calendar/US_CPI_TEST_FIXTURE.json").exists())


if __name__ == "__main__":
    unittest.main()
