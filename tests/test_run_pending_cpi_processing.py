from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import process_cpi_release, run_pending_cpi_processing
from scripts.pipelines import build_cpi_release_report
from scripts.providers import github_models, openai_responses
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


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
SECOND_EVENT_ID = "US_CPI_2026_05"


def analysis_output(root: Path, event_id: str = EVENT_ID) -> Path:
    return root / "data" / "analysis" / "cpi" / event_id / "cpi-analysis-v1.json"


def report_output(root: Path, event_id: str = EVENT_ID) -> Path:
    return root / "docs" / "reports" / f"{event_id}.html"


def second_event() -> dict:
    event = calendar_event(event_id=SECOND_EVENT_ID, reference_period="2026-05")
    event["release_datetime_utc"] = "2026-06-10T12:30:00Z"
    return event


class RunPendingCpiProcessingTests(unittest.TestCase):
    @contextmanager
    def temp_root(self, *, release=False, events=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if events is None:
                write_base_inputs(root)
            else:
                write_json(root / "data" / "calendar" / "events.json", {"version": 1, "events": events})
                write_json(
                    root / "data" / "indicator_profiles.json",
                    {"CPI": {"display_name": "US Consumer Price Index", "country": "US"}},
                )
            if release:
                write_release(root)
            yield root

    def run_processing(self, root: Path, *, event_id=None, result_name="result.json"):
        return run_pending_cpi_processing.run_pending_processing(
            root,
            event_id=event_id,
            result_json=root / result_name,
            now=NOW,
        )

    def prepare_all(self, root: Path):
        result, exit_code = self.run_processing(root, event_id=EVENT_ID, result_name="prepared.json")
        self.assertEqual(exit_code, 0)
        self.assertEqual(result.status, "PROCESSED")
        return result

    def test_01_missing_as_released_returns_no_pending_event(self):
        with self.temp_root() as root:
            result, exit_code = self.run_processing(root)
            self.assertEqual(result.status, "NO_PENDING_EVENT")
            self.assertEqual(exit_code, 0)
            self.assertEqual(result.commit_paths, ())

    def test_02_external_api_providers_are_never_called(self):
        with self.temp_root(release=True) as root:
            with mock.patch.object(
                github_models,
                "generate_analysis",
                side_effect=AssertionError("external provider called"),
            ), mock.patch.object(
                openai_responses,
                "generate_analysis",
                side_effect=AssertionError("paid provider called"),
            ):
                result, _ = self.run_processing(root)
            self.assertEqual(result.status, "PROCESSED")
            self.assertFalse(result.external_api_called)

    def test_03_completed_event_is_excluded_from_auto_selection(self):
        with self.temp_root(release=True) as root:
            self.prepare_all(root)
            result, exit_code = self.run_processing(root, result_name="auto.json")
            self.assertEqual(result.status, "NO_PENDING_EVENT")
            self.assertEqual(exit_code, 0)
            self.assertIsNone(result.event_id)

    def test_04_one_pending_event_is_selected(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.event_id, EVENT_ID)
            self.assertEqual(result.status, "PROCESSED")

    def test_05_two_pending_events_are_rejected_without_generation(self):
        events = [calendar_event(), second_event()]
        with self.temp_root(events=events) as root:
            write_release(root)
            write_release(
                root,
                release_payload(event_id=SECOND_EVENT_ID, reference_period="2026-05"),
                event_id=SECOND_EVENT_ID,
            )
            result, exit_code = self.run_processing(root)
            self.assertEqual(result.status, "MULTIPLE_PENDING_EVENTS")
            self.assertEqual(exit_code, 1)
            self.assertEqual(set(result.pending_event_ids), {EVENT_ID, SECOND_EVENT_ID})
            self.assertEqual(result.created_paths, ())
            self.assertEqual(result.commit_paths, ())
            self.assertFalse(canonical_output(root).exists())
            self.assertFalse(canonical_output(root, SECOND_EVENT_ID).exists())

    def test_06_manual_event_id_processes_only_requested_event(self):
        events = [calendar_event(), second_event()]
        with self.temp_root(events=events) as root:
            write_release(root)
            write_release(
                root,
                release_payload(event_id=SECOND_EVENT_ID, reference_period="2026-05"),
                event_id=SECOND_EVENT_ID,
            )
            result, exit_code = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(exit_code, 0)
            self.assertEqual(result.event_id, EVENT_ID)
            self.assertTrue(canonical_output(root).exists())
            self.assertFalse(canonical_output(root, SECOND_EVENT_ID).exists())

    def test_07_valid_release_creates_canonical(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.canonical["status"], "created")
            self.assertTrue(canonical_output(root).exists())

    def test_08_canonical_creates_rule_based_analysis(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            analysis = json.loads(analysis_output(root).read_text(encoding="utf-8"))
            self.assertEqual(result.analysis["status"], "created")
            self.assertEqual(analysis["provider"]["name"], "rule_based")
            self.assertFalse(analysis["provider"]["external_api_called"])

    def test_09_analysis_creates_html_report(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.report["status"], "created")
            self.assertTrue(report_output(root).exists())
            self.assertIn("최초 발표 CPI 지표", report_output(root).read_text(encoding="utf-8"))

    def test_10_full_success_returns_processed(self):
        with self.temp_root(release=True) as root:
            result, exit_code = self.run_processing(root)
            self.assertEqual(result.status, "PROCESSED")
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(result.created_paths), 3)
            self.assertEqual(result.commit_paths, result.created_paths)

    def test_11_canonical_only_state_resumes_analysis_and_report(self):
        with self.temp_root(release=True) as root:
            build = build_cpi_release_canonical.build_from_files(root, EVENT_ID)
            self.assertEqual(build.status, "CANONICAL_CREATED")
            before = canonical_output(root).read_bytes()
            result, _ = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "CANONICAL_ONLY_RESUMED")
            self.assertEqual(canonical_output(root).read_bytes(), before)
            self.assertEqual(
                result.commit_paths,
                (
                    f"data/analysis/cpi/{EVENT_ID}/cpi-analysis-v1.json",
                    f"docs/reports/{EVENT_ID}.html",
                ),
            )

    def test_12_canonical_and_analysis_state_resumes_report_only(self):
        with self.temp_root(release=True) as root:
            processed = process_cpi_release.process_release(root, EVENT_ID, now=NOW)
            self.assertEqual(processed.status, "PROCESSED")
            result, _ = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "REPORT_ONLY_RESUMED")
            self.assertEqual(result.commit_paths, (f"docs/reports/{EVENT_ID}.html",))

    def test_13_all_existing_valid_files_return_already_processed(self):
        with self.temp_root(release=True) as root:
            self.prepare_all(root)
            files = [canonical_output(root), analysis_output(root), report_output(root)]
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
            result, _ = self.run_processing(root, event_id=EVENT_ID, result_name="again.json")
            self.assertEqual(result.status, "ALREADY_PROCESSED")
            self.assertEqual(result.commit_paths, ())
            self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in files])

    def test_14_analysis_without_canonical_is_inconsistent(self):
        with self.temp_root(release=True) as root:
            write_json(analysis_output(root), {"unexpected": True})
            before = analysis_output(root).read_bytes()
            result, exit_code = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "INCONSISTENT_DERIVED_STATE")
            self.assertEqual(exit_code, 1)
            self.assertEqual(result.commit_paths, ())
            self.assertEqual(analysis_output(root).read_bytes(), before)
            self.assertFalse(canonical_output(root).exists())

    def test_15_html_without_inputs_is_inconsistent(self):
        with self.temp_root(release=True) as root:
            report_output(root).parent.mkdir(parents=True, exist_ok=True)
            report_output(root).write_text("existing report\n", encoding="utf-8")
            before = report_output(root).read_bytes()
            result, _ = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "INCONSISTENT_DERIVED_STATE")
            self.assertEqual(result.commit_paths, ())
            self.assertEqual(report_output(root).read_bytes(), before)

    def test_16_release_sha_mismatch_is_blocked(self):
        with self.temp_root(release=True) as root:
            path = root / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["integrity"]["sha256"] = "0" * 64
            write_json(path, payload)
            result, exit_code = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertEqual(exit_code, 1)
            self.assertEqual(result.commit_paths, ())
            self.assertFalse(canonical_output(root).exists())

    def test_17_canonical_analysis_sha_mismatch_is_blocked(self):
        with self.temp_root(release=True) as root:
            processed = process_cpi_release.process_release(root, EVENT_ID, now=NOW)
            self.assertEqual(processed.status, "PROCESSED")
            payload = json.loads(analysis_output(root).read_text(encoding="utf-8"))
            payload["input"]["canonical_sha256"] = "f" * 64
            write_json(analysis_output(root), payload)
            result, _ = self.run_processing(root, event_id=EVENT_ID)
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertEqual(result.commit_paths, ())
            self.assertFalse(report_output(root).exists())

    def test_18_html_core_number_mismatch_is_blocked(self):
        with self.temp_root(release=True) as root:
            self.prepare_all(root)
            path = report_output(root)
            changed = path.read_text(encoding="utf-8").replace(
                '<td data-field="actual">0.3%</td>',
                '<td data-field="actual">9.9%</td>',
                1,
            )
            path.write_text(changed, encoding="utf-8")
            before = path.read_bytes()
            result, _ = self.run_processing(root, event_id=EVENT_ID, result_name="invalid-report.json")
            self.assertEqual(result.status, "INTEGRITY_CHECK_FAILED")
            self.assertEqual(result.commit_paths, ())
            self.assertEqual(path.read_bytes(), before)

    def test_19_commit_paths_have_at_most_three_files(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertLessEqual(len(result.commit_paths), 3)
            self.assertEqual(len(result.commit_paths), 3)

    def test_20_commit_paths_only_use_allowed_derivatives(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            run_pending_cpi_processing.validate_commit_paths(
                root,
                EVENT_ID,
                result.commit_paths,
                newly_created=set(result.created_paths),
            )
            self.assertEqual(set(result.commit_paths), run_pending_cpi_processing._allowed_paths(EVENT_ID))

    def test_21_one_forbidden_path_rejects_the_whole_list(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            forbidden = root / "docs" / "index.html"
            forbidden.parent.mkdir(parents=True, exist_ok=True)
            forbidden.write_text("index\n", encoding="utf-8")
            mixed = list(result.commit_paths) + ["docs/index.html"]
            with self.assertRaises(run_pending_cpi_processing.PendingProcessingError):
                run_pending_cpi_processing.validate_commit_paths(root, EVENT_ID, mixed)

    def test_22_absolute_commit_path_is_rejected(self):
        with self.temp_root() as root:
            with self.assertRaises(run_pending_cpi_processing.PendingProcessingError):
                run_pending_cpi_processing.validate_commit_paths(
                    root,
                    EVENT_ID,
                    [str((root / "absolute.html").resolve())],
                )

    def test_23_parent_traversal_commit_path_is_rejected(self):
        with self.temp_root() as root:
            with self.assertRaises(run_pending_cpi_processing.PendingProcessingError):
                run_pending_cpi_processing.validate_commit_paths(
                    root,
                    EVENT_ID,
                    [f"docs/reports/../{EVENT_ID}.html"],
                )

    def test_24_symlink_commit_path_is_rejected(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            target = canonical_output(root)
            original = Path.is_symlink

            def fake_is_symlink(path):
                return True if path == target else original(path)

            with mock.patch.object(Path, "is_symlink", fake_is_symlink):
                with self.assertRaises(run_pending_cpi_processing.PendingProcessingError):
                    run_pending_cpi_processing.validate_commit_paths(
                        root,
                        EVENT_ID,
                        [f"data/generated/cpi/{EVENT_ID}/canonical_release.json"],
                    )

    def test_25_result_json_contains_no_api_key_or_secret_token(self):
        with self.temp_root(release=True) as root:
            self.run_processing(root)
            text = (root / "result.json").read_text(encoding="utf-8")
            for marker in ("OPENAI_API_KEY", "BLS_API_KEY", "GITHUB_TOKEN", "sk-test-secret"):
                self.assertNotIn(marker, text)
            self.assertNotIn(str(root), text)

    def test_26_cost_mode_is_free(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.cost_mode, "free")

    def test_27_provider_is_rule_based(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.provider, "rule_based")

    def test_28_token_usage_is_zero(self):
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.usage, run_pending_cpi_processing.ZERO_USAGE)
            analysis = json.loads(analysis_output(root).read_text(encoding="utf-8"))
            self.assertEqual(analysis["usage"], run_pending_cpi_processing.ZERO_USAGE)

    def test_29_temp_fixtures_never_touch_actual_data_or_docs(self):
        actual_paths = (
            ROOT / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json",
            ROOT / "data" / "generated" / "cpi" / EVENT_ID / "canonical_release.json",
            ROOT / "data" / "analysis" / "cpi" / EVENT_ID / "cpi-analysis-v1.json",
            ROOT / "docs" / "reports" / f"{EVENT_ID}.html",
        )
        before = [path.read_bytes() if path.exists() else None for path in actual_paths]
        with self.temp_root(release=True) as root:
            result, _ = self.run_processing(root)
            self.assertEqual(result.status, "PROCESSED")
        after = [path.read_bytes() if path.exists() else None for path in actual_paths]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
