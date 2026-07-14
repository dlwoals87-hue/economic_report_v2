from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.automation import build_cpi_notification_event as builder


EVENT_ID = "US_CPI_2026_06"


class BuildCpiNotificationEventTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / f"docs/reports/{EVENT_ID}.html"; report.parent.mkdir(parents=True); report.write_text("report", encoding="utf-8")
            index = root / "docs/index.html"; index.write_text(self.index_entry(), encoding="utf-8")
            return callback(root)

    def index_entry(self, *, event_id=EVENT_ID, href=None):
        href = href or f"reports/{EVENT_ID}.html"
        return "\n".join((
            "<!-- AUTO_REAL_REPORTS_START -->",
            f'<article class="auto-real-report" data-event-id="{event_id}" data-report-href="{href}">report</article>',
            "<!-- AUTO_REAL_REPORTS_END -->",
        ))

    def result(self, status="PROCESSED_AND_INDEXED"):
        return {"status": status, "event_id": EVENT_ID, "reference_period": "2026-06", "provider": "rule_based", "external_api_called": False, "cost_mode": "free", "report": {"path": f"docs/reports/{EVENT_ID}.html"}}

    def test_success_payload(self):
        def case(root):
            event = builder.build_event(root, self.result(), "owner/repo")
            self.assertTrue(event.should_notify)
            self.assertEqual(
                set(event.payload()),
                {
                    "schema_version", "status", "should_notify", "event_id", "indicator_type",
                    "reference_period", "processing_status", "provider", "external_api_called",
                    "cost", "report_relative_path", "report_url", "notification_key",
                },
            )
        self.run_in_temp(case)

    def test_index_only_resumed_payload(self):
        self.run_in_temp(lambda root: self.assertEqual(builder.build_event(root, self.result("INDEX_ONLY_RESUMED"), "owner/repo").processing_status, "INDEX_ONLY_RESUMED"))

    def test_all_completed_processing_statuses_build_payloads(self):
        for status in (
            "PROCESSED_AND_INDEXED",
            "REPORT_ONLY_RESUMED_AND_INDEXED",
            "REPORT_ONLY_RESUMED",
            "INDEX_ONLY_RESUMED",
            "ALREADY_PROCESSED",
        ):
            with self.subTest(status=status):
                self.run_in_temp(lambda root: self.assertTrue(builder.build_event(root, self.result(status), "owner/repo").should_notify))

    def test_non_publish_status_is_skipped(self):
        self.run_in_temp(lambda root: self.assertFalse(builder.build_event(root, self.result("NO_PENDING_EVENT"), "owner/repo").should_notify))

    def test_unsafe_provider_metadata_is_rejected(self):
        for key, value in (("provider", "openai"), ("external_api_called", True), ("cost_mode", "paid")):
            with self.subTest(key=key):
                def case(root):
                    payload = self.result(); payload[key] = value
                    with self.assertRaises(builder.NotificationEventError): builder.build_event(root, payload, "owner/repo")
                self.run_in_temp(case)

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

    def test_index_registration_requires_the_exact_event_id_and_href(self):
        def case(root):
            (root / "docs/index.html").write_text(self.index_entry(event_id="US_CPI_2026_060"), encoding="utf-8")
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
            (root / "docs/index.html").write_text(self.index_entry(href=f"reports/{EVENT_ID}0.html"), encoding="utf-8")
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(case)

    def test_plain_text_comments_and_external_hrefs_do_not_register_a_report(self):
        invalid_indexes = (
            f'<!-- {EVENT_ID} reports/{EVENT_ID}.html -->',
            f'<p>{EVENT_ID} reports/{EVENT_ID}.html</p>',
            self.index_entry(href=f"https://example.test/reports/{EVENT_ID}.html"),
            self.index_entry(href=f"javascript:reports/{EVENT_ID}.html"),
            self.index_entry(href=f"reports/../{EVENT_ID}.html"),
        )
        for index_text in invalid_indexes:
            with self.subTest(index_text=index_text):
                def case(root):
                    (root / "docs/index.html").write_text(index_text, encoding="utf-8")
                    with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
                self.run_in_temp(case)

    def test_missing_or_symlinked_index_is_rejected(self):
        def missing(root):
            (root / "docs/index.html").unlink()
            with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(missing)

        def symlinked(root):
            with mock.patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(symlinked)

    def test_symlinked_report_is_rejected(self):
        def case(root):
            with mock.patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(builder.NotificationEventError): builder.build_event(root, self.result(), "owner/repo")
        self.run_in_temp(case)

    def test_marker_key_and_pages_url(self):
        def case(root):
            event = builder.build_event(root, self.result(), "owner/repo")
            self.assertEqual(event.notification_key, f"cpi:{EVENT_ID}:report-published")
            self.assertEqual(event.report_relative_path, f"docs/reports/{EVENT_ID}.html")
            self.assertEqual(event.report_url, f"https://owner.github.io/repo/reports/{EVENT_ID}.html")
            self.assertNotIn("/docs/", event.report_url)
        self.run_in_temp(case)


if __name__ == "__main__":
    unittest.main()
