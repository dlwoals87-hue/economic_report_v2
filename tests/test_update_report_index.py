from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import process_cpi_release, update_report_index
from scripts.pipelines import build_cpi_release_report
from tests.test_build_cpi_release_canonical import (
    EVENT_ID,
    calendar_event,
    release_payload,
    write_base_inputs,
    write_json,
    write_release,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
SECOND_EVENT_ID = "US_CPI_2026_05"
INDEX_TEXT = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>경제지표 리포트</title>
<style>.keep{color:#123456}</style>
<script>window.keepIndexScript = true;</script>
</head>
<body>
<h1>경제지표 리포트</h1>
<p><a href="./reports/sample-report.html">샘플 리포트 보기</a></p>
<p><a href="./reports/sample-cpi-report.html">CPI 샘플 리포트</a></p>
<p><a href="./reports/sample-ppi-report.html">PPI 샘플 리포트</a></p>
<p><a href="./reports/sample-nfp-report.html">NFP 샘플 리포트</a></p>
<p><a href="./reports/sample-fomc-report.html">FOMC 샘플 리포트</a></p>
</body>
</html>
"""


def report_path(root: Path, event_id: str = EVENT_ID) -> Path:
    return root / "docs" / "reports" / f"{event_id}.html"


def canonical_path(root: Path, event_id: str = EVENT_ID) -> Path:
    return root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"


def index_path(root: Path) -> Path:
    return root / "docs" / "index.html"


def second_event() -> dict:
    event = calendar_event(event_id=SECOND_EVENT_ID, reference_period="2026-05")
    event["release_datetime_utc"] = "2026-06-10T12:30:00Z"
    return event


class UpdateReportIndexTests(unittest.TestCase):
    @contextmanager
    def temp_root(self, *, events=None):
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
            self.write_index(root)
            yield root

    def write_index(self, root: Path, text: str = INDEX_TEXT) -> None:
        index = index_path(root)
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(text, encoding="utf-8")

    def prepare_report(self, root: Path, event_id: str = EVENT_ID) -> None:
        if event_id == EVENT_ID:
            write_release(root)
        else:
            write_release(
                root,
                release_payload(event_id=event_id, reference_period="2026-05"),
                event_id=event_id,
            )
        processed = process_cpi_release.process_release(root, event_id, now=NOW)
        self.assertEqual(processed.status, "PROCESSED")
        rendered = build_cpi_release_report.build_report(root, event_id)
        self.assertEqual(rendered.status, "REPORT_CREATED")

    def update(self, root: Path, event_id: str = EVENT_ID, **kwargs):
        return update_report_index.update_report_index(root, event_id, **kwargs)

    def managed(self, text: str) -> str:
        start = text.index(update_report_index.START_MARKER)
        end = text.index(update_report_index.END_MARKER, start)
        return text[start:end + len(update_report_index.END_MARKER)]

    def test_01_missing_report_returns_report_not_found(self):
        with self.temp_root() as root:
            result = self.update(root)
            self.assertEqual(result.status, "REPORT_NOT_FOUND")

    def test_02_missing_report_does_not_modify_index(self):
        with self.temp_root() as root:
            before = (index_path(root).read_bytes(), index_path(root).stat().st_mtime_ns)
            self.update(root)
            self.assertEqual(before, (index_path(root).read_bytes(), index_path(root).stat().st_mtime_ns))

    def test_03_missing_canonical_does_not_modify_index(self):
        with self.temp_root() as root:
            report_path(root).parent.mkdir(parents=True, exist_ok=True)
            report_path(root).write_text("report\n", encoding="utf-8")
            before = index_path(root).read_bytes()
            result = self.update(root)
            self.assertEqual(result.status, "CANONICAL_RELEASE_NOT_FOUND")
            self.assertEqual(index_path(root).read_bytes(), before)

    def test_04_event_id_mismatch_does_not_modify_index(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            canonical = json.loads(canonical_path(root).read_text(encoding="utf-8"))
            canonical["meta"]["event_id"] = "US_CPI_2099_01"
            write_json(canonical_path(root), canonical)
            before = index_path(root).read_bytes()
            result = self.update(root)
            self.assertEqual(result.status, "REPORT_INTEGRITY_FAILED")
            self.assertEqual(index_path(root).read_bytes(), before)

    def test_05_report_integrity_failure_does_not_modify_index(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            path = report_path(root)
            path.write_text(path.read_text(encoding="utf-8").replace("0.3%", "9.9%", 1), encoding="utf-8")
            before = index_path(root).read_bytes()
            result = self.update(root)
            self.assertEqual(result.status, "REPORT_INTEGRITY_FAILED")
            self.assertEqual(index_path(root).read_bytes(), before)

    def test_06_missing_marker_is_inserted_once(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            result = self.update(root)
            text = index_path(root).read_text(encoding="utf-8")
            self.assertEqual(result.status, "INDEX_UPDATED")
            self.assertEqual(text.count(update_report_index.START_MARKER), 1)
            self.assertEqual(text.count(update_report_index.END_MARKER), 1)

    def test_07_one_actual_report_entry_is_added(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            managed = self.managed(index_path(root).read_text(encoding="utf-8"))
            self.assertIn('data-event-id="US_CPI_2026_06"', managed)
            self.assertIn("실제 발표 리포트", managed)
            self.assertNotIn("아직 자동 생성된 실제 발표 리포트가 없습니다.", managed)

    def test_08_entry_uses_relative_report_link(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            self.assertIn('href="reports/US_CPI_2026_06.html"', index_path(root).read_text(encoding="utf-8"))

    def test_09_rerun_never_duplicates_event(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            self.update(root)
            text = index_path(root).read_text(encoding="utf-8")
            self.assertEqual(text.count('data-event-id="US_CPI_2026_06"'), 1)

    def test_10_identical_rerun_is_already_up_to_date(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            result = self.update(root)
            self.assertEqual(result.status, "INDEX_ALREADY_UP_TO_DATE")
            self.assertFalse(result.index_changed)

    def test_11_same_event_with_different_sha_is_index_conflict(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            path = index_path(root)
            path.write_text(
                re.sub(
                    r"<!-- report-sha256: [0-9a-f]{64} -->",
                    "<!-- report-sha256: " + "f" * 64 + " -->",
                    path.read_text(encoding="utf-8"),
                    count=1,
                ),
                encoding="utf-8",
            )
            before = path.read_bytes()
            result = self.update(root)
            self.assertEqual(result.status, "INDEX_CONFLICT")
            self.assertEqual(path.read_bytes(), before)

    def test_12_multiple_entries_are_sorted_newest_first(self):
        with self.temp_root(events=[calendar_event(), second_event()]) as root:
            self.prepare_report(root, SECOND_EVENT_ID)
            self.update(root, SECOND_EVENT_ID)
            self.prepare_report(root, EVENT_ID)
            self.update(root, EVENT_ID)
            text = index_path(root).read_text(encoding="utf-8")
            self.assertLess(text.index(EVENT_ID), text.index(SECOND_EVENT_ID))

    def test_13_existing_sample_links_are_preserved(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            text = index_path(root).read_text(encoding="utf-8")
            for href in (
                "./reports/sample-report.html",
                "./reports/sample-cpi-report.html",
                "./reports/sample-ppi-report.html",
                "./reports/sample-nfp-report.html",
                "./reports/sample-fomc-report.html",
            ):
                self.assertIn(href, text)

    def test_14_marker_outside_content_is_unchanged(self):
        with self.temp_root(events=[calendar_event(), second_event()]) as root:
            self.prepare_report(root, SECOND_EVENT_ID)
            self.update(root, SECOND_EVENT_ID)
            before = index_path(root).read_text(encoding="utf-8")
            start = before.index(update_report_index.START_MARKER)
            end = before.index(update_report_index.END_MARKER, start) + len(update_report_index.END_MARKER)
            outside = (before[:start], before[end:])
            self.prepare_report(root, EVENT_ID)
            self.update(root, EVENT_ID)
            after = index_path(root).read_text(encoding="utf-8")
            after_start = after.index(update_report_index.START_MARKER)
            after_end = after.index(update_report_index.END_MARKER, after_start) + len(update_report_index.END_MARKER)
            self.assertEqual(outside, (after[:after_start], after[after_end:]))

    def test_15_style_blocks_are_unchanged(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            before = re.findall(r"<style\b[^>]*>.*?</style\s*>", index_path(root).read_text(encoding="utf-8"), re.S | re.I)
            self.update(root)
            after = re.findall(r"<style\b[^>]*>.*?</style\s*>", index_path(root).read_text(encoding="utf-8"), re.S | re.I)
            self.assertEqual(after, before)

    def test_16_script_blocks_are_unchanged(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            before = re.findall(r"<script\b[^>]*>.*?</script\s*>", index_path(root).read_text(encoding="utf-8"), re.S | re.I)
            self.update(root)
            after = re.findall(r"<script\b[^>]*>.*?</script\s*>", index_path(root).read_text(encoding="utf-8"), re.S | re.I)
            self.assertEqual(after, before)

    def test_17_dynamic_indicator_text_is_html_escaped(self):
        with self.temp_root() as root:
            write_json(
                root / "data" / "indicator_profiles.json",
                {"CPI": {"display_name": '<b title="x">CPI</b>', "country": "US"}},
            )
            self.prepare_report(root)
            self.update(root)
            managed = self.managed(index_path(root).read_text(encoding="utf-8"))
            self.assertIn("&lt;b title=&quot;x&quot;&gt;CPI&lt;/b&gt;", managed)
            self.assertNotIn('<b title="x">', managed)

    def test_18_script_in_dynamic_text_is_inert(self):
        with self.temp_root() as root:
            write_json(
                root / "data" / "indicator_profiles.json",
                {"CPI": {"display_name": "<script>alert(1)</script>", "country": "US"}},
            )
            self.prepare_report(root)
            self.update(root)
            managed = self.managed(index_path(root).read_text(encoding="utf-8"))
            self.assertNotIn("<script", managed.casefold())
            self.assertIn("&lt;script&gt;", managed)

    def test_19_event_handler_in_dynamic_text_is_inert(self):
        with self.temp_root() as root:
            write_json(
                root / "data" / "indicator_profiles.json",
                {"CPI": {"display_name": '<img src="x" onerror="alert(1)">', "country": "US"}},
            )
            self.prepare_report(root)
            self.update(root)
            managed = self.managed(index_path(root).read_text(encoding="utf-8"))
            self.assertIsNone(update_report_index.EVENT_HANDLER_RE.search(managed))
            self.assertIn("&lt;img", managed)

    def test_20_javascript_url_is_not_inserted(self):
        with self.temp_root() as root:
            write_json(
                root / "data" / "indicator_profiles.json",
                {"CPI": {"display_name": 'javascript:alert(1)', "country": "US"}},
            )
            self.prepare_report(root)
            self.update(root)
            managed = self.managed(index_path(root).read_text(encoding="utf-8"))
            self.assertIsNone(update_report_index.JAVASCRIPT_URL_RE.search(managed))
            self.assertIn('href="reports/US_CPI_2026_06.html"', managed)

    def test_21_invalid_event_id_is_rejected(self):
        with self.temp_root() as root:
            with self.assertRaises(update_report_index.ReportIndexError) as raised:
                self.update(root, "US_CPI_2026_06<script>")
            self.assertEqual(raised.exception.code, "INVALID_EVENT_ID")

    def test_22_index_outside_project_is_rejected(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            outside = root.parent / "outside-index.html"
            with self.assertRaises(update_report_index.ReportIndexError) as raised:
                self.update(root, index=str(outside.resolve()))
            self.assertEqual(raised.exception.code, "INVALID_PATH")
            self.assertFalse(outside.exists())

    def test_23_parent_path_is_rejected(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            with self.assertRaises(update_report_index.ReportIndexError) as raised:
                self.update(root, index="../outside-index.html")
            self.assertEqual(raised.exception.code, "INVALID_PATH")

    def test_24_symlink_report_is_rejected(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            target = report_path(root)
            original = Path.is_symlink

            def fake_is_symlink(path):
                return True if path == target else original(path)

            with mock.patch.object(Path, "is_symlink", fake_is_symlink):
                result = self.update(root)
            self.assertEqual(result.status, "REPORT_INTEGRITY_FAILED")

    def test_25_identical_result_keeps_index_mtime(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root)
            before = (index_path(root).read_bytes(), index_path(root).stat().st_mtime_ns)
            self.update(root)
            self.assertEqual(before, (index_path(root).read_bytes(), index_path(root).stat().st_mtime_ns))

    def test_26_index_and_result_json_do_not_expose_credentials(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            result_path = root / "result.json"
            self.update(root, result_json="result.json")
            text = index_path(root).read_text(encoding="utf-8") + result_path.read_text(encoding="utf-8")
            for marker in ("OPENAI_API_KEY", "BLS_API_KEY", "GITHUB_TOKEN", "sk-test-secret"):
                self.assertNotIn(marker, text)

    def test_27_index_and_result_json_do_not_expose_windows_paths(self):
        with self.temp_root() as root:
            self.prepare_report(root)
            self.update(root, result_json="result.json")
            text = index_path(root).read_text(encoding="utf-8") + (root / "result.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), text)
            self.assertNotRegex(text, r"[A-Za-z]:\\")

    def test_28_temp_fixture_never_touches_actual_docs_index(self):
        actual = ROOT / "docs" / "index.html"
        before = actual.read_bytes()
        with self.temp_root() as root:
            self.prepare_report(root)
            result = self.update(root)
            self.assertEqual(result.status, "INDEX_UPDATED")
        self.assertEqual(actual.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
