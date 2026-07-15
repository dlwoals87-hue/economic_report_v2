from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "capture-cpi-components.yml"


class CaptureCpiComponentsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_workflow_structure_and_live_opt_in_exist(self):
        self.assertEqual(self.lines[0], "name: Capture CPI Components")
        for item in ("on:", "permissions:", "concurrency:", "jobs:"):
            self.assertIn(item, self.lines)
        self.assertIn("--enable-live-bls", self.text)
        self.assertIn('timezone: "America/New_York"', self.text)

    def test_commit_paths_are_exact_and_rechecked_after_add(self):
        self.assertIn("git add --", self.text)
        self.assertIn("git diff --cached --name-only", self.text)
        self.assertIn("git diff --cached --name-status", self.text)
        self.assertIn("set(staged) != set(expected)", self.text)
        self.assertIn("len(staged) != 2", self.text)
        self.assertIn('code != "A"', self.text)
        self.assertIn("components_as_released.json", self.text)
        self.assertIn("data/raw/bls/cpi_components/", self.text)

    def test_disallowed_git_and_push_forms_absent(self):
        self.assertNotIn("git add .", self.text)
        self.assertNotIn("git add -A", self.text)
        self.assertNotIn("--force", self.text)
        self.assertNotIn("PERSONAL_ACCESS_TOKEN", self.text)
        self.assertNotIn("GH_PAT", self.text)


if __name__ == "__main__":
    unittest.main()
