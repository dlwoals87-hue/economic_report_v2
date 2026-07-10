from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import process_cpi_release
from tests.test_build_cpi_release_canonical import (
    EVENT_ID,
    build_cpi_release_canonical,
    calendar_event,
    default_output as canonical_output,
    release_payload,
    write_base_inputs,
    write_json,
    write_release,
)


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def analysis_output(root: Path) -> Path:
    return root / "data" / "analysis" / "cpi" / EVENT_ID / "cpi-analysis-v1.json"


def result_output(root: Path) -> Path:
    return root / "process-result.json"


def complete_calendar_event():
    event = calendar_event(
        expected_values={
            "headline_mom": "0.1",
            "headline_yoy": "3.1",
            "core_mom": "0.2",
            "core_yoy": "3.1",
        }
    )
    event["consensus_source"] = "manual test source"
    event["consensus_status"] = "complete"
    event["entered_at_utc"] = "2026-07-01T12:00:00Z"
    return event


class ProcessCpiReleaseTests(unittest.TestCase):
    def run_temp(self, callback, *, release=False, event=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_inputs(root, event=event)
            if release:
                write_release(root)
            return callback(root)

    def process(self, root, **kwargs):
        return process_cpi_release.process_release(root, EVENT_ID, now=NOW, **kwargs)

    def read_analysis(self, root):
        return json.loads(analysis_output(root).read_text(encoding="utf-8"))

    def test_release_missing_returns_release_not_captured(self):
        def case(root):
            result = self.process(root)
            self.assertEqual(result.status, "RELEASE_NOT_CAPTURED")

        self.run_temp(case)

    def test_release_missing_creates_no_canonical(self):
        def case(root):
            self.process(root)
            self.assertFalse(canonical_output(root).exists())

        self.run_temp(case)

    def test_release_missing_creates_no_analysis(self):
        def case(root):
            self.process(root)
            self.assertFalse(analysis_output(root).exists())

        self.run_temp(case)

    def test_release_missing_calls_no_external_api(self):
        def case(root):
            result = self.process(root)
            self.assertFalse(result.external_api_called)
            self.assertEqual(result.usage, process_cpi_release.ZERO_USAGE)

        self.run_temp(case)

    def test_release_missing_result_has_null_paths_and_empty_commit_lists(self):
        def case(root):
            result = self.process(root, result_json="process-result.json")
            payload = json.loads(result_output(root).read_text(encoding="utf-8"))
            self.assertIsNone(payload["canonical"]["path"])
            self.assertIsNone(payload["analysis"]["path"])
            self.assertEqual(payload["created_paths"], [])
            self.assertEqual(payload["commit_paths"], [])
            self.assertEqual(result.status, "RELEASE_NOT_CAPTURED")

        self.run_temp(case)

    def test_valid_release_creates_canonical(self):
        def case(root):
            self.process(root)
            self.assertTrue(canonical_output(root).exists())

        self.run_temp(case, release=True)

    def test_valid_canonical_creates_rule_based_analysis(self):
        def case(root):
            self.process(root)
            self.assertTrue(analysis_output(root).exists())
            self.assertEqual(self.read_analysis(root)["provider"]["name"], "rule_based")

        self.run_temp(case, release=True)

    def test_full_success_returns_processed(self):
        def case(root):
            result = self.process(root)
            self.assertEqual(result.status, "PROCESSED")
            self.assertEqual(len(result.created_paths), 2)

        self.run_temp(case, release=True)

    def test_success_external_api_called_is_false(self):
        def case(root):
            result = self.process(root)
            self.assertFalse(result.external_api_called)
            self.assertFalse(self.read_analysis(root)["provider"]["external_api_called"])

        self.run_temp(case, release=True)

    def test_success_token_usage_is_zero(self):
        def case(root):
            result = self.process(root)
            self.assertEqual(result.usage, process_cpi_release.ZERO_USAGE)
            self.assertEqual(self.read_analysis(root)["usage"], process_cpi_release.ZERO_USAGE)

        self.run_temp(case, release=True)

    def test_success_does_not_check_api_keys_or_tokens(self):
        def case(root):
            with mock.patch.object(
                process_cpi_release.os.environ,
                "get",
                side_effect=AssertionError("environment secrets must not be checked"),
            ):
                result = self.process(root)
            self.assertEqual(result.status, "PROCESSED")

        self.run_temp(case, release=True)

    def test_actual_as_released_maps_to_analysis_facts(self):
        def case(root):
            self.process(root)
            facts = self.read_analysis(root)["facts"]["metrics"]
            self.assertEqual(facts["headline_mom"]["actual"], "0.3")
            self.assertEqual(facts["core_yoy"]["actual_display"], "3.1%")

        self.run_temp(case, release=True)

    def test_previous_as_released_maps_to_analysis_facts(self):
        def case(root):
            self.process(root)
            facts = self.read_analysis(root)["facts"]["metrics"]
            self.assertEqual(facts["headline_mom"]["previous"], "0.5")
            self.assertEqual(facts["core_yoy"]["previous_display"], "3.2%")

        self.run_temp(case, release=True)

    def test_expected_null_is_preserved(self):
        def case(root):
            self.process(root)
            facts = self.read_analysis(root)["facts"]["metrics"]
            self.assertIsNone(facts["headline_mom"]["expected"])
            self.assertFalse(self.read_analysis(root)["facts"]["consensus_available"])

        self.run_temp(case, release=True)

    def test_surprise_null_is_preserved(self):
        def case(root):
            self.process(root)
            facts = self.read_analysis(root)["facts"]["metrics"]
            self.assertIsNone(facts["headline_mom"]["surprise"])

        self.run_temp(case, release=True)

    def test_expected_surprise_is_connected_when_consensus_exists(self):
        def case(root):
            self.process(root)
            metric = self.read_analysis(root)["facts"]["metrics"]["headline_mom"]
            self.assertEqual(metric["expected"], "0.1")
            self.assertEqual(metric["surprise"]["raw"], "0.2")
            self.assertEqual(metric["surprise"]["direction"], "above_expected")

        self.run_temp(case, release=True, event=complete_calendar_event())

    def test_canonical_sha_matches_analysis_input(self):
        def case(root):
            self.process(root)
            expected = hashlib.sha256(canonical_output(root).read_bytes()).hexdigest()
            self.assertEqual(self.read_analysis(root)["input"]["canonical_sha256"], expected)

        self.run_temp(case, release=True)

    def test_release_sha_matches_canonical_source(self):
        def case(root):
            release_file = root / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json"
            self.process(root)
            release = json.loads(release_file.read_text(encoding="utf-8"))
            canonical = json.loads(canonical_output(root).read_text(encoding="utf-8"))
            self.assertEqual(
                canonical["source"]["release_capture_sha256"],
                release["integrity"]["sha256"],
            )

        self.run_temp(case, release=True)

    def test_canonical_only_state_creates_analysis_only(self):
        def case(root):
            build_cpi_release_canonical.build_from_files(root, EVENT_ID)
            before = canonical_output(root).read_bytes()
            result = self.process(root)
            self.assertEqual(result.status, "CANONICAL_ONLY_RESUMED")
            self.assertEqual(result.created_paths, (f"data/analysis/cpi/{EVENT_ID}/cpi-analysis-v1.json",))
            self.assertEqual(canonical_output(root).read_bytes(), before)
            self.assertTrue(analysis_output(root).exists())

        self.run_temp(case, release=True)

    def test_existing_canonical_and_analysis_returns_already_processed(self):
        def case(root):
            self.process(root)
            second = self.process(root)
            self.assertEqual(second.status, "ALREADY_PROCESSED")
            self.assertEqual(second.created_paths, ())
            self.assertEqual(second.commit_paths, ())

        self.run_temp(case, release=True)

    def test_second_run_does_not_modify_derived_files(self):
        def case(root):
            self.process(root)
            canonical_before = (canonical_output(root).read_bytes(), canonical_output(root).stat().st_mtime_ns)
            analysis_before = (analysis_output(root).read_bytes(), analysis_output(root).stat().st_mtime_ns)
            self.process(root)
            self.assertEqual(
                canonical_before,
                (canonical_output(root).read_bytes(), canonical_output(root).stat().st_mtime_ns),
            )
            self.assertEqual(
                analysis_before,
                (analysis_output(root).read_bytes(), analysis_output(root).stat().st_mtime_ns),
            )

        self.run_temp(case, release=True)

    def test_analysis_without_canonical_is_inconsistent(self):
        def case(root):
            write_json(analysis_output(root), {"orphan": True})
            result = self.process(root)
            self.assertEqual(result.status, "INCONSISTENT_DERIVED_STATE")
            self.assertFalse(canonical_output(root).exists())
            self.assertEqual(json.loads(analysis_output(root).read_text(encoding="utf-8")), {"orphan": True})

        self.run_temp(case, release=True)

    def test_release_sha_mismatch_stops_before_canonical(self):
        def case(root):
            payload = release_payload()
            payload["integrity"]["sha256"] = "tampered"
            write_release(root, payload)
            result = self.process(root)
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertFalse(canonical_output(root).exists())
            self.assertFalse(analysis_output(root).exists())

        self.run_temp(case)

    def test_existing_canonical_mismatch_is_not_overwritten(self):
        def case(root):
            build_cpi_release_canonical.build_from_files(root, EVENT_ID)
            payload = json.loads(canonical_output(root).read_text(encoding="utf-8"))
            payload["meta"]["indicator_name"] = "tampered"
            write_json(canonical_output(root), payload)
            before = canonical_output(root).read_bytes()
            result = self.process(root)
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertEqual(canonical_output(root).read_bytes(), before)
            self.assertFalse(analysis_output(root).exists())

        self.run_temp(case, release=True)

    def test_existing_analysis_mismatch_is_not_overwritten(self):
        def case(root):
            self.process(root)
            payload = self.read_analysis(root)
            payload["input"]["canonical_sha256"] = "tampered"
            write_json(analysis_output(root), payload)
            before = analysis_output(root).read_bytes()
            result = self.process(root)
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertEqual(analysis_output(root).read_bytes(), before)

        self.run_temp(case, release=True)

    def test_valid_but_changed_rule_based_text_is_not_accepted_or_overwritten(self):
        def case(root):
            self.process(root)
            payload = self.read_analysis(root)
            payload["analysis"]["executive_summary"]["one_line"] = "입력 facts와 다른 임의 해석이다."
            write_json(analysis_output(root), payload)
            before = analysis_output(root).read_bytes()
            result = self.process(root)
            self.assertEqual(result.status, "ANALYSIS_FAILED")
            self.assertEqual(analysis_output(root).read_bytes(), before)

        self.run_temp(case, release=True)

    def test_calendar_invalid_stops_all_later_processing(self):
        event = calendar_event()
        del event["metrics"]["core_yoy"]

        def case(root):
            canonical_builder = mock.Mock()
            analysis_runner = mock.Mock()
            result = self.process(
                root,
                canonical_builder=canonical_builder,
                analysis_runner=analysis_runner,
            )
            self.assertEqual(result.status, "CALENDAR_INVALID")
            canonical_builder.assert_not_called()
            analysis_runner.assert_not_called()
            self.assertFalse(canonical_output(root).exists())
            self.assertFalse(analysis_output(root).exists())

        self.run_temp(case, release=True, event=event)

    def test_commit_paths_have_at_most_two_allowed_paths(self):
        def case(root):
            result = self.process(root)
            self.assertLessEqual(len(result.commit_paths), 2)
            process_cpi_release.validate_commit_paths(result.commit_paths, EVENT_ID)

        self.run_temp(case, release=True)

    def test_unapproved_commit_path_is_rejected(self):
        with self.assertRaises(process_cpi_release.ProcessCpiError) as caught:
            process_cpi_release.validate_commit_paths(["data/releases/secret.json"], EVENT_ID)
        self.assertEqual(caught.exception.code, "INVALID_COMMIT_PATH")

    def test_absolute_result_path_is_rejected(self):
        def case(root):
            with self.assertRaises(process_cpi_release.ProcessCpiError) as caught:
                self.process(root, result_json=str(root / "result.json"))
            self.assertEqual(caught.exception.code, "INVALID_RESULT_PATH")

        self.run_temp(case)

    def test_parent_traversal_result_path_is_rejected(self):
        def case(root):
            with self.assertRaises(process_cpi_release.ProcessCpiError) as caught:
                self.process(root, result_json="../result.json")
            self.assertEqual(caught.exception.code, "INVALID_RESULT_PATH")

        self.run_temp(case)

    def test_keys_and_tokens_are_not_in_result_json(self):
        def case(root):
            secrets = {
                "OPENAI_API_KEY": "SECRET_OPENAI_RESULT",
                "GITHUB_TOKEN": "SECRET_GITHUB_RESULT",
            }
            with mock.patch.dict(os.environ, secrets, clear=False):
                self.process(root, result_json="process-result.json")
            text = result_output(root).read_text(encoding="utf-8")
            self.assertNotIn("SECRET_OPENAI_RESULT", text)
            self.assertNotIn("SECRET_GITHUB_RESULT", text)

        self.run_temp(case, release=True)

    def test_windows_absolute_path_is_not_in_result_json(self):
        def case(root):
            self.process(root, result_json="process-result.json")
            text = result_output(root).read_text(encoding="utf-8")
            self.assertNotIn(str(root), text)
            self.assertNotIn("D:\\", text)

        self.run_temp(case, release=True)

    def test_fixture_is_not_left_in_real_project_data(self):
        fixture_event = "US_CPI_PROCESS_FIXTURE_3_8"

        def case(root):
            self.process(root)
            self.assertFalse(
                (process_cpi_release.PROJECT_ROOT / "data" / "releases" / "cpi" / fixture_event).exists()
            )
            self.assertFalse(
                (process_cpi_release.PROJECT_ROOT / "data" / "generated" / "cpi" / fixture_event).exists()
            )
            self.assertFalse(
                (process_cpi_release.PROJECT_ROOT / "data" / "analysis" / "cpi" / fixture_event).exists()
            )

        self.run_temp(case)

    def test_external_provider_is_blocked_before_any_call(self):
        def case(root):
            with self.assertRaises(process_cpi_release.ProcessCpiError) as caught:
                self.process(root, provider="openai")
            self.assertEqual(caught.exception.code, "EXTERNAL_PROVIDER_DISABLED")
            self.assertFalse(canonical_output(root).exists())
            self.assertFalse(analysis_output(root).exists())

        self.run_temp(case, release=True)


if __name__ == "__main__":
    unittest.main()
