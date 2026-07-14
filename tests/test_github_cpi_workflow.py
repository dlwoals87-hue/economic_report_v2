from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "capture-cpi-release.yml"


class GitHubCpiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def step_block(self, name):
        marker = f"- name: {name}"
        start = self.text.index(marker)
        next_step = re.search(r"\n\s+- name: ", self.text[start + len(marker):])
        if next_step is None:
            return self.text[start:]
        end = start + len(marker) + next_step.start()
        return self.text[start:end]

    def test_workflow_file_exists(self):
        self.assertTrue(WORKFLOW.exists())

    def test_workflow_physical_lines_are_not_collapsed(self):
        self.assertGreaterEqual(len(self.lines), 100)
        first_non_empty = next(line for line in self.lines if line.strip())
        self.assertEqual(first_non_empty, "name: Capture CPI Release")
        self.assertNotIn("name: Capture CPI Release on:", self.text)

    def test_top_level_keys_are_separate_unindented_lines(self):
        for key in ("on:", "permissions:", "concurrency:", "jobs:"):
            with self.subTest(key=key):
                self.assertIn(key, self.lines)

    def test_workflow_dispatch_and_schedule_are_under_on(self):
        on_index = self.lines.index("on:")
        permissions_index = self.lines.index("permissions:")
        workflow_dispatch_index = self.lines.index("  workflow_dispatch:")
        schedule_index = self.lines.index("  schedule:")

        self.assertGreater(workflow_dispatch_index, on_index)
        self.assertLess(workflow_dispatch_index, permissions_index)
        self.assertGreater(schedule_index, on_index)
        self.assertLess(schedule_index, permissions_index)

    def test_jobs_capture_hierarchy_is_separate(self):
        jobs_index = self.lines.index("jobs:")
        capture_index = self.lines.index("  capture:")
        runs_on_index = self.lines.index("    runs-on: ubuntu-latest")

        self.assertGreater(capture_index, jobs_index)
        self.assertGreater(runs_on_index, capture_index)

    def test_run_blocks_keep_real_newlines(self):
        offline_block = self.step_block("Run offline tests")
        capture_block = self.step_block("Capture due CPI release")
        result_block = self.step_block("Validate capture result")
        commit_block = self.step_block("Commit captured release")

        self.assertRegex(
            offline_block,
            r"run: \|\n\s+python -B -m unittest \\\n\s+tests/test_bls_cpi.py",
        )
        self.assertRegex(
            capture_block,
            r"run: \|\n\s+if \[ -n \"\$\{MANUAL_EVENT_ID:-\}\" \]; then\n"
            r"\s+python scripts/automation/run_due_cpi_capture.py \\",
        )
        self.assertRegex(
            result_block,
            r"run: \|\n\s+python - <<'PY'\n\s+import fnmatch\n",
        )
        self.assertRegex(
            commit_block,
            r"run: \|\n\s+git config user.name "
            r"\"github-actions\[bot\]\"\n",
        )
        self.assertRegex(
            commit_block,
            r"git commit -m \"data: capture \$\{EVENT_ID\} release\"\n"
            r"\s+git push origin HEAD:main",
        )

    def test_python_heredocs_start_and_end_on_own_lines(self):
        self.assertEqual(self.lines.count("          python - <<'PY'"), 2)
        self.assertEqual(self.lines.count("          PY"), 2)

    def test_commit_condition_and_allowed_path_validation_remain(self):
        self.assertIn(
            "        if: steps.result.outputs.should_commit == 'true' && github.ref_name == 'main'",
            self.lines,
        )
        self.assertIn('              "data/releases/cpi/*/as_released.json",', self.lines)
        self.assertIn('              "data/raw/bls/cpi/*/retrieved_*.json",', self.lines)
        self.assertIn('              "data/processed/bls/cpi_latest.json",', self.lines)

    def test_workflow_dispatch_exists(self):
        self.assertIn("workflow_dispatch:", self.text)

    def test_schedule_exists(self):
        self.assertIn("schedule:", self.text)

    def test_america_new_york_timezone_exists(self):
        self.assertIn('timezone: "America/New_York"', self.text)

    def test_morning_836_to_856_retry_exists(self):
        self.assertIn('cron: "36-56/5 8 * * 1-5"', self.text)

    def test_9am_retries_exist(self):
        self.assertIn('cron: "6,21,41 9 * * 1-5"', self.text)

    def test_10am_and_noon_retries_exist(self):
        self.assertIn('cron: "11 10,12 * * 1-5"', self.text)

    def test_permissions_contents_write_exists(self):
        self.assertRegex(self.text, r"permissions:\s*\n\s+contents: write")

    def test_concurrency_exists(self):
        self.assertIn("concurrency:", self.text)

    def test_cancel_in_progress_false(self):
        self.assertIn("cancel-in-progress: false", self.text)

    def test_ubuntu_latest(self):
        self.assertIn("runs-on: ubuntu-latest", self.text)

    def test_timeout_minutes_10(self):
        self.assertIn("timeout-minutes: 10", self.text)

    def test_checkout_v6(self):
        self.assertIn("actions/checkout@v6", self.text)

    def test_setup_python_v6(self):
        self.assertIn("actions/setup-python@v6", self.text)

    def test_python_312(self):
        self.assertIn('python-version: "3.12"', self.text)

    def test_scheduled_runs_do_not_run_full_tests(self):
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.run_tests", self.text)

    def test_calendar_validator_runs(self):
        self.assertIn("scripts/validators/validate_calendar_events.py", self.text)

    def test_calendar_validator_runs_before_capture(self):
        self.assertLess(
            self.text.index("- name: Validate calendar"),
            self.text.index("- name: Capture due CPI release"),
        )

    def test_calendar_validator_failure_is_not_ignored(self):
        block = self.step_block("Validate calendar")
        self.assertNotIn("continue-on-error: true", block)
        self.assertNotIn("|| true", block)
        self.assertNotIn("set +e", block)

    def test_capture_and_commit_do_not_force_run_after_validator_failure(self):
        capture_block = self.step_block("Capture due CPI release")
        commit_block = self.step_block("Commit captured release")
        self.assertNotIn("always()", capture_block)
        self.assertNotIn("always()", commit_block)
        self.assertLess(
            self.text.index("- name: Validate calendar"),
            self.text.index("- name: Commit captured release"),
        )

    def test_run_due_script_runs(self):
        self.assertIn("scripts/automation/run_due_cpi_capture.py", self.text)

    def test_result_json_used(self):
        self.assertIn("cpi_capture_result.json", self.text)

    def test_commit_only_when_captured(self):
        self.assertIn("status == 'CAPTURED'", self.text)
        self.assertIn("steps.result.outputs.should_commit == 'true'", self.text)

    def test_captured_result_requires_commit_paths(self):
        self.assertIn("captured result must include commit paths", self.text)

    def test_invalid_commit_path_fails_before_commit_paths_file_is_written(self):
        self.assertLess(
            self.text.index("path not allowed"),
            self.text.index("paths_file.write_text"),
        )

    def test_invalid_commit_path_validation_runs_before_git_add(self):
        self.assertLess(
            self.text.index("- name: Validate capture result"),
            self.text.index("git add --"),
        )

    def test_staged_files_are_rechecked_after_git_add(self):
        self.assertIn("git diff --cached --name-only", self.text)
        self.assertIn("git diff --cached --name-status", self.text)
        self.assertIn("STAGED_PATHS_FILE", self.text)
        self.assertIn("STAGED_STATUS_FILE", self.text)
        self.assertLess(
            self.text.index("git add --"),
            self.text.index("git diff --cached --name-only"),
        )

    def test_staged_recheck_runs_before_commit(self):
        self.assertLess(
            self.text.index("git diff --cached --name-only"),
            self.text.index("git commit -m"),
        )

    def test_staged_files_must_be_safe_candidate_subset(self):
        self.assertIn("set(staged).issubset(set(expected))", self.text)
        self.assertIn("unexpected staged files", self.text)
        self.assertIn("CPI_IMMUTABLE_RELEASE_NOT_STAGED", self.text)
        self.assertIn("CPI_RAW_SNAPSHOT_NOT_STAGED", self.text)
        self.assertIn('status_code not in {"A", "M"}', self.text)
        self.assertIn("immutable capture artifact must be added", self.text)

    def test_staged_file_count_is_limited(self):
        self.assertIn("too many staged paths", self.text)

    def test_no_git_add_dot(self):
        self.assertNotRegex(self.text, r"git add\s+\.")

    def test_no_git_add_all(self):
        self.assertNotIn("git add -A", self.text)

    def test_no_force_push(self):
        self.assertNotIn("--force", self.text)
        self.assertNotIn("push --force", self.text)

    def test_no_personal_access_token(self):
        self.assertNotIn("PERSONAL_ACCESS_TOKEN", self.text)
        self.assertNotIn("GH_PAT", self.text)
        self.assertNotIn("secrets.PAT", self.text)

    def test_no_hardcoded_bls_key(self):
        self.assertIn("${{ secrets.BLS_API_KEY }}", self.text)
        self.assertNotRegex(self.text, r"BLS_API_KEY:\s*['\"][A-Za-z0-9_\-]{8,}['\"]")

    def test_no_pull_request_or_push_triggers(self):
        self.assertNotRegex(self.text, r"(?m)^\s+pull_request:")
        self.assertNotRegex(self.text, r"(?m)^  push:")

    def test_no_automatic_commit_for_site_paths(self):
        allowed_block = re.search(r"allowed = \((.*?)\)", self.text, flags=re.S)
        self.assertIsNotNone(allowed_block)
        block = allowed_block.group(1)
        self.assertNotIn("docs/", block)
        self.assertNotIn("templates/", block)


if __name__ == "__main__":
    unittest.main()
