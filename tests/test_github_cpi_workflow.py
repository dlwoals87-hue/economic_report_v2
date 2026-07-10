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
        self.assertIn("STAGED_PATHS_FILE", self.text)
        self.assertLess(
            self.text.index("git add --"),
            self.text.index("git diff --cached --name-only"),
        )

    def test_staged_recheck_runs_before_commit(self):
        self.assertLess(
            self.text.index("git diff --cached --name-only"),
            self.text.index("git commit -m"),
        )

    def test_staged_files_must_match_commit_paths(self):
        self.assertIn("set(staged) != set(expected)", self.text)
        self.assertIn("unexpected staged files", self.text)
        self.assertIn("expected paths not staged", self.text)

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
