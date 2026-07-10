from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "process-cpi-release.yml"


class GitHubCpiProcessingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()
        on_start = cls.lines.index("on:")
        permissions_start = cls.lines.index("permissions:")
        cls.trigger_text = "\n".join(cls.lines[on_start:permissions_start])

    def step_block(self, name):
        marker = f"- name: {name}"
        start = self.text.index(marker)
        following = re.search(r"\n\s+- name: ", self.text[start + len(marker):])
        if following is None:
            return self.text[start:]
        end = start + len(marker) + following.start()
        return self.text[start:end]

    def test_01_workflow_file_exists(self):
        self.assertTrue(WORKFLOW.exists())

    def test_02_workflow_name_is_exact(self):
        first = next(line for line in self.lines if line.strip())
        self.assertEqual(first, "name: Process CPI Release")

    def test_03_workflow_run_trigger_exists(self):
        self.assertIn("  workflow_run:", self.lines)

    def test_04_capture_workflow_name_is_exact(self):
        self.assertIn('      - "Capture CPI Release"', self.lines)

    def test_05_completed_type_exists(self):
        self.assertRegex(
            self.trigger_text,
            r"types:\s*\n\s+- completed",
        )

    def test_06_workflow_run_is_limited_to_main(self):
        self.assertRegex(
            self.trigger_text,
            r"branches:\s*\n\s+- main",
        )

    def test_07_workflow_dispatch_exists(self):
        self.assertIn("  workflow_dispatch:", self.lines)
        self.assertIn("      event_id:", self.lines)
        self.assertIn("      run_tests:", self.lines)

    def test_08_push_trigger_is_absent(self):
        self.assertNotRegex(self.trigger_text, r"(?m)^  push:")

    def test_09_pull_request_trigger_is_absent(self):
        self.assertNotRegex(self.trigger_text, r"(?m)^  pull_request:")

    def test_10_schedule_trigger_is_absent(self):
        self.assertNotIn("schedule:", self.trigger_text)

    def test_11_workflow_run_requires_success(self):
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.text)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.text)

    def test_12_permissions_contents_write(self):
        self.assertRegex(self.text, r"permissions:\s*\n\s+contents: write")

    def test_13_concurrency_group_exists(self):
        self.assertIn("concurrency:", self.lines)
        self.assertIn("  group: cpi-release-processing", self.lines)

    def test_14_cancel_in_progress_is_false(self):
        self.assertIn("  cancel-in-progress: false", self.lines)

    def test_15_runner_is_ubuntu_latest(self):
        self.assertIn("    runs-on: ubuntu-latest", self.lines)

    def test_16_timeout_is_ten_minutes(self):
        self.assertIn("    timeout-minutes: 10", self.lines)

    def test_17_checkout_v6_is_used(self):
        self.assertIn("actions/checkout@v6", self.text)
        checkout = self.step_block("Checkout latest main")
        self.assertIn("ref: main", checkout)

    def test_18_setup_python_v6_is_used(self):
        self.assertIn("actions/setup-python@v6", self.text)

    def test_19_python_312_is_selected(self):
        self.assertIn('python-version: "3.12"', self.text)

    def test_20_calendar_validator_runs_before_processing(self):
        self.assertIn("scripts/validators/validate_calendar_events.py", self.text)
        self.assertLess(
            self.text.index("- name: Validate calendar"),
            self.text.index("- name: Process pending CPI release"),
        )

    def test_21_pending_processing_script_runs(self):
        block = self.step_block("Process pending CPI release")
        self.assertIn("scripts/automation/run_pending_cpi_processing.py", block)
        self.assertIn("--event-id", block)

    def test_22_result_json_is_used(self):
        self.assertIn("cpi_processing_result.json", self.text)
        self.assertIn("RESULT_JSON", self.text)
        self.assertIn("json.loads(result_path.read_text", self.text)

    def test_23_commit_is_limited_to_allowed_statuses(self):
        validation = self.step_block("Validate processing result")
        commit = self.step_block("Commit processed CPI report")
        for status in (
            "PROCESSED",
            "CANONICAL_ONLY_RESUMED",
            "REPORT_ONLY_RESUMED",
        ):
            self.assertIn(f'"{status}"', validation)
        self.assertIn('{"NO_PENDING_EVENT", "ALREADY_PROCESSED"}', validation)
        self.assertIn("status in commit_statuses", validation)
        self.assertIn("steps.result.outputs.should_commit == 'true'", commit)

    def test_24_git_add_dot_is_absent(self):
        self.assertNotRegex(self.text, r"git add\s+\.(?:\s|$)")

    def test_25_git_add_all_is_absent(self):
        self.assertNotIn("git add -A", self.text)

    def test_26_staged_files_are_rechecked(self):
        commit = self.step_block("Commit processed CPI report")
        self.assertIn("git diff --cached --name-only", commit)
        self.assertIn("git diff --cached --name-status", commit)
        self.assertIn("set(staged) != set(expected)", commit)
        self.assertLess(commit.index("git add --"), commit.index("git diff --cached --name-only"))
        self.assertLess(commit.index("git diff --cached --name-only"), commit.index("git commit -m"))

    def test_27_automatic_commit_is_limited_to_three_files(self):
        self.assertIn("1 <= len(commit_paths) <= 3", self.text)
        self.assertIn("1 <= len(expected) <= 3", self.text)
        self.assertIn("1 <= len(staged) <= 3", self.text)

    def test_28_force_push_is_absent(self):
        self.assertNotIn("--force", self.text)
        self.assertNotIn("push --force", self.text)

    def test_29_personal_access_credentials_are_absent(self):
        for marker in (
            "PERSONAL_ACCESS_TOKEN",
            "GH_PAT",
            "secrets.PAT",
            "github_pat_",
        ):
            self.assertNotIn(marker, self.text)

    def test_30_external_api_secrets_are_not_referenced(self):
        for marker in (
            "BLS_API_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "GITHUB_MODELS",
            "${{ secrets.",
        ):
            self.assertNotIn(marker, self.text)

    def test_31_docs_index_is_not_modified(self):
        self.assertNotIn("docs/index.html", self.text)
        allowed = self.step_block("Validate processing result")
        self.assertNotIn('f"docs/index', allowed)


if __name__ == "__main__":
    unittest.main()
