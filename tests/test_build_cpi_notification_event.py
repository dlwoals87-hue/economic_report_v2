from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.automation import build_cpi_notification_event as builder


EVENT_ID = "US_CPI_2026_06"


class BuildCpiNotificationEventTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / f"docs/reports/{EVENT_ID}.html"; report.parent.mkdir(parents=True); report.write_text("report", encoding="utf-8")
            index = root / "docs/index.html"; index.write_text(f'<a href="docs/reports/{EVENT_ID}.html">report</a>', encoding="utf-8")
            return callback(root)

    def result(self, status="PROCESSED_AND_INDEXED"):
        return {"status": status, "event_id": EVENT_ID, "reference_period": "2026-06", "provider": "rule_based", "external_api_called": False, "cost_mode": "free", "report": {"path": f"docs/reports/{EVENT_ID}.html"}}

    def test_success_payload(self):
        self.run_in_temp(lambda root: self.assertTrue(builder.build_event(root, self.result(), "owner/repo").should_notify))

    def test_index_only_resumed_payload(self):
        self.run_in_temp(lambda root: self.assertEqual(builder.build_event(root, self.result("INDEX_ONLY_RESUMED"), "owner/repo").processing_status, "INDEX_ONLY_RESUMED"))

    def test_non_publish_status_is_skipped(self):
        self.run_in_temp(lambda root: self.assertFalse(builder.build_event(root, self.result("NO_PENDING_EVENT"), "owner/repo").should_notify))

    def test_missing_report_is_rejected(self):
        def case(root):
            (root / f"docs/reports/{EVENT_ID}.html").unlink()
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(case)

    def test_unsafe_report_paths_are_rejected(self):
        def case(root):
            payload = self.result(); payload["report"] = {"path": "../report.html"}
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, payload, "owner/repo")
        self.run_in_temp(case)

    def test_index_registration_is_required(self):
        def case(root):
            (root / "docs/index.html").write_text("missing", encoding="utf-8")
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(case)

    def test_marker_key_and_pages_url(self):
        self.run_in_temp(lambda root: (self.assertEqual(builder.build_event(root, self.result(), "owner/repo").notification_key, f"cpi:{EVENT_ID}:report-published"), self.assertIn("owner.github.io/repo/docs/reports", builder.build_event(root, self.result(), "owner/repo").report_url)))


if __name__ == "__main__":
    unittest.main()
