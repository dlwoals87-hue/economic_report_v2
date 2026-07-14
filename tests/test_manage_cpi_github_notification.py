from __future__ import annotations

import unittest

from scripts.automation import manage_cpi_github_notification as manager


class ManageCpiGithubNotificationTests(unittest.TestCase):
    def success_payload(self):
        return {"should_notify": True, "event_id": "US_CPI_2026_06", "reference_period": "2026-06", "notification_key": "cpi:US_CPI_2026_06:report-published", "provider": "rule_based", "external_api_called": False, "cost": "free", "processing_status": "PROCESSED_AND_INDEXED", "report_url": "https://owner.github.io/repo/reports/US_CPI_2026_06.html"}

    def test_success_marker_and_body(self):
        key, _title, body = manager.success_issue(self.success_payload())
        self.assertIn(f"notification-key:{key}", body)

    def test_failure_and_cancelled_are_distinct(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            key, title, body = manager.failure_issue({"id": 12, "conclusion": conclusion, "name": "Process CPI Release", "head_branch": "main", "head_sha": "abcdef123", "actor": {"login": "bot"}, "html_url": "https://example/run"})
            self.assertEqual(key, "cpi:process-failure:12"); self.assertIn(conclusion, title); self.assertIn(conclusion, body)

    def test_non_failure_has_no_issue(self):
        self.assertIsNone(manager.failure_issue({"id": 1, "conclusion": "success"}))

    def test_dry_run_never_calls_api(self):
        result = manager.manage("owner/repo", "key", "title", "body", dry_run=True, apply=False, api=lambda *_args: (_ for _ in ()).throw(AssertionError("API")))
        self.assertEqual(result.status, "NOTIFICATION_DRY_RUN")

    def test_open_and_closed_issue_markers_block_duplicates(self):
        for issues in ([{"body": "<!-- notification-key:key -->"}], [{"state": "closed", "body": "<!-- notification-key:key -->"}]):
            result = manager.manage("owner/repo", "key", "title", "body", dry_run=False, apply=True, api=lambda *_args, items=issues: items, environment={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "x"})
            self.assertEqual(result.status, "NOTIFICATION_ALREADY_EXISTS")

    def test_pagination_is_followed(self):
        calls = []
        def api(url, token, method="GET", payload=None):
            calls.append(url)
            return [{} for _ in range(100)] if url.endswith("page=1") else []
        self.assertFalse(manager.marker_exists("owner/repo", "x", "marker", api)); self.assertEqual(len(calls), 2)

    def test_apply_creates_once(self):
        calls = []
        def api(url, token, method="GET", payload=None):
            calls.append((method, payload)); return [] if method == "GET" else {"number": 1}
        result = manager.manage("owner/repo", "key", "title", "body", dry_run=False, apply=True, api=api, environment={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "x"})
        self.assertEqual(result.status, "NOTIFICATION_CREATED"); self.assertEqual(calls[-1][0], "POST")

    def test_apply_outside_actions_is_skipped(self):
        self.assertEqual(manager.manage("owner/repo", "key", "title", "body", dry_run=False, apply=True, environment={}).status, "NOTIFICATION_SKIPPED")


if __name__ == "__main__":
    unittest.main()
