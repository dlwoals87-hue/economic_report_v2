from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/notify-cpi-processing.yml"
PROCESS = ROOT / ".github/workflows/process-cpi-release.yml"


class GitHubCpiNotificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.process = PROCESS.read_text(encoding="utf-8")

    def test_workflow_run_trigger_and_guards(self):
        for value in ("name: Notify CPI Processing", "workflow_run:", '"Process CPI Release"', "- completed", "head_branch == 'main'", "head_repository.full_name == github.repository"):
            self.assertIn(value, self.text)

    def test_minimum_permissions(self):
        self.assertRegex(self.text, r"contents: read")
        self.assertRegex(self.text, r"actions: read")
        self.assertRegex(self.text, r"issues: write")
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("id-token: write", self.text)

    def test_no_pat_or_external_secret_or_git_mutation(self):
        for value in ("PERSONAL_ACCESS_TOKEN", "GH_PAT", "secrets.PAT", "git add .", "git add -A", "--force", "OPENAI_API_KEY", "BLS_API_KEY"):
            self.assertNotIn(value, self.text)

    def test_success_artifact_and_failure_metadata_paths_exist(self):
        self.assertIn("cpi-notification-event", self.text)
        self.assertIn("workflow_run.json", self.text)
        self.assertIn("manage_cpi_github_notification.py", self.text)

    def test_process_builds_artifact_after_push(self):
        self.assertIn("build_cpi_notification_event.py", self.process)
        self.assertIn("actions/upload-artifact@v4", self.process)
        self.assertLess(self.process.index("git push origin HEAD:main"), self.process.index("Build CPI notification event"))
        self.assertNotRegex(self.process, r"git add\s+\.(?:\s|$)")


if __name__ == "__main__":
    unittest.main()
