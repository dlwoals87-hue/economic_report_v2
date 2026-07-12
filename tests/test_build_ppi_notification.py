from __future__ import annotations

from pathlib import Path
import unittest

from scripts.automation import build_ppi_notification as notify


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "notify-ppi-processing.yml"


class PpiNotificationTests(unittest.TestCase):
    def test_manual_dispatch_is_always_skipped_without_upstream(self):
        self.assertEqual(
            notify.build_manual_dispatch_notification(),
            {
                "status": "NOTIFICATION_SKIPPED",
                "upstream_status": "MANUAL_DISPATCH_NO_UPSTREAM",
                "event_id": None,
                "notification_action": "none",
                "issue_created": False,
                "issue_updated": False,
                "issue_number": None,
                "external_ai_api_called": False,
                "cost": "free",
            },
        )

    def test_skip_success_failure(self):
        self.assertEqual(
            notify.build_notification({"status": "NO_PENDING_PPI_EVENT"})["status"],
            "NOTIFICATION_SKIPPED",
        )
        self.assertEqual(
            notify.build_notification({"status": "ALREADY_PROCESSED"})["status"],
            "NOTIFICATION_SKIPPED",
        )
        success = notify.build_notification(
            {
                "status": "PROCESSED_AND_INDEXED",
                "event_id": "US_PPI_2026_05",
                "cost_mode": "free",
            }
        )
        self.assertEqual(success["category"], "success")
        self.assertIn("ppi-processing:US_PPI_2026_05:success", success["body"])
        self.assertEqual(
            notify.build_notification(
                {"status": "PPI_PROCESSING_CONFLICT", "event_id": "US_PPI_2026_05"}
            )["category"],
            "failure",
        )

    def test_upstream_workflow_failure_has_run_marker(self):
        notification = notify.build_notification(
            {},
            workflow_conclusion="failure",
            workflow_run_id=12345,
            repository="owner/repo",
        )
        self.assertEqual(notification["status"], "NOTIFICATION_READY")
        self.assertEqual(notification["upstream_status"], "UPSTREAM_WORKFLOW_FAILURE")
        self.assertEqual(notification["category"], "failure")
        self.assertIn("https://github.com/owner/repo/actions/runs/12345", notification["body"])

    def test_issue_create_update_unchanged_and_duplicate(self):
        notification = notify.build_notification(
            {"status": "PROCESSED_AND_INDEXED", "event_id": "US_PPI_2026_05"}
        )
        created = notify.decide_issue_action(notification, [])
        self.assertEqual(created["notification_action"], "created")
        marker = "<!-- automation-key: ppi-processing:US_PPI_2026_05:success -->"
        self.assertEqual(
            notify.decide_issue_action(notification, [{"number": 7, "body": marker + "\nold"}])["notification_action"],
            "updated",
        )
        self.assertEqual(
            notify.decide_issue_action(notification, [{"number": 7, "body": created["body"]}])["notification_action"],
            "unchanged",
        )
        self.assertEqual(
            notify.decide_issue_action(notification, [{"body": marker}, {"body": marker}])["status"],
            "DUPLICATE_ISSUE_CONFLICT",
        )

    def test_failure_issue_create_update_and_unchanged(self):
        notification = notify.build_notification(
            {"status": "PPI_PROCESSING_CONFLICT", "event_id": "US_PPI_2026_05"}
        )
        created = notify.decide_issue_action(notification, [])
        self.assertEqual(created["notification_action"], "created")
        marker = "<!-- automation-key: ppi-processing:US_PPI_2026_05:failure -->"
        self.assertEqual(
            notify.decide_issue_action(notification, [{"number": 8, "body": marker + "\nold"}])["notification_action"],
            "updated",
        )
        self.assertEqual(
            notify.decide_issue_action(notification, [{"number": 8, "body": created["body"]}])["notification_action"],
            "unchanged",
        )

    def test_workflow_separates_manual_and_upstream_paths(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("workflow_run:", text)
        self.assertIn("Process PPI Release", text)
        self.assertIn("github.event_name == 'workflow_run'", text)
        self.assertIn("github.event.workflow_run.id", text)
        self.assertIn("repository: ${{ github.repository }}", text)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", text)
        self.assertIn("github-token: ${{ secrets.GITHUB_TOKEN }}", text)
        self.assertIn("build_manual_dispatch_notification", text)
        self.assertIn("actions/github-script@v7", text)
        self.assertIn("if: ${{ github.event_name == 'workflow_run'", text)
        self.assertIn("name: ppi-notification-result", text)
        self.assertNotIn("contents: write", text)
