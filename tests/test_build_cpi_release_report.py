from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.automation import process_cpi_release
from scripts.pipelines import build_cpi_release_report
from tests.test_build_cpi_release_canonical import (
    EVENT_ID,
    build_cpi_release_canonical,
    calendar_event,
    default_output as canonical_output,
    write_base_inputs,
    write_json,
    write_release,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
ACTUAL_REPORT = ROOT / "docs" / "reports" / f"{EVENT_ID}.html"


def analysis_output(root: Path) -> Path:
    return root / "data" / "analysis" / "cpi" / EVENT_ID / "cpi-analysis-v1.json"


def report_output(root: Path) -> Path:
    return root / "docs" / "reports" / f"{EVENT_ID}.html"


def complete_calendar_event() -> dict:
    event = calendar_event(
        expected_values={
            "headline_mom": "0.1",
            "headline_yoy": "3.1",
            "core_mom": "0.2",
            "core_yoy": "3.1",
        }
    )
    event["consensus_source"] = "manual test source"
    event["consensus_status"] = "complete"
    event["entered_at_utc"] = "2026-07-01T12:00:00Z"
    return event


class BuildCpiReleaseReportTests(unittest.TestCase):
    @contextmanager
    def temp_root(self, *, prepared=False, canonical_only=False, event=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_inputs(root, event=event)
            if prepared or canonical_only:
                write_release(root)
            if prepared:
                result = process_cpi_release.process_release(root, EVENT_ID, now=NOW)
                self.assertEqual(result.status, "PROCESSED")
            elif canonical_only:
                result = build_cpi_release_canonical.build_from_files(root, EVENT_ID)
                self.assertEqual(result.status, "CANONICAL_CREATED")
            yield root

    def build(self, root: Path, **kwargs):
        return build_cpi_release_report.build_report(root, EVENT_ID, **kwargs)

    def read_report(self, root: Path) -> str:
        return report_output(root).read_text(encoding="utf-8")

    def read_analysis(self, root: Path) -> dict:
        return json.loads(analysis_output(root).read_text(encoding="utf-8"))

    def change_analysis(self, root: Path, callback) -> None:
        payload = self.read_analysis(root)
        callback(payload["analysis"])
        write_json(analysis_output(root), payload)

    def metric_cell(self, document: str, metric: str, field: str) -> str:
        row = re.search(
            rf'<tr data-metric="{re.escape(metric)}">(.*?)</tr>',
            document,
            re.DOTALL,
        )
        self.assertIsNotNone(row)
        cell = re.search(
            rf'<td data-field="{re.escape(field)}">(.*?)</td>',
            row.group(1),
            re.DOTALL,
        )
        self.assertIsNotNone(cell)
        return html.unescape(re.sub(r"<[^>]*>", "", cell.group(1)))

    def test_01_missing_canonical_returns_not_found(self):
        with self.temp_root() as root:
            result = self.build(root)
            self.assertEqual(result.status, "CANONICAL_RELEASE_NOT_FOUND")

    def test_02_missing_analysis_returns_not_found(self):
        with self.temp_root(canonical_only=True) as root:
            result = self.build(root)
            self.assertEqual(result.status, "ANALYSIS_NOT_FOUND")

    def test_03_missing_inputs_create_no_html(self):
        with self.temp_root() as root:
            self.build(root)
            self.assertFalse(report_output(root).exists())

    def test_04_canonical_sha_mismatch_blocks_generation(self):
        with self.temp_root(prepared=True) as root:
            payload = self.read_analysis(root)
            payload["input"]["canonical_sha256"] = "0" * 64
            write_json(analysis_output(root), payload)
            with self.assertRaises(build_cpi_release_report.CpiReportError) as raised:
                self.build(root)
            self.assertEqual(raised.exception.code, "INPUT_INTEGRITY_MISMATCH")
            self.assertFalse(report_output(root).exists())

    def test_05_actual_as_released_maps_exactly(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            expected = {
                "headline_mom": "0.3%",
                "headline_yoy": "2.9%",
                "core_mom": "0.2%",
                "core_yoy": "3.1%",
            }
            for metric, value in expected.items():
                self.assertEqual(self.metric_cell(document, metric, "actual"), value)
            self.assertNotIn("9.9%", document)

    def test_06_previous_as_released_maps_exactly(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            expected = {
                "headline_mom": "0.5%",
                "headline_yoy": "3.0%",
                "core_mom": "0.3%",
                "core_yoy": "3.2%",
            }
            for metric, value in expected.items():
                self.assertEqual(self.metric_cell(document, metric, "previous"), value)

    def test_07_null_expected_displays_not_entered(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for metric in build_cpi_release_report.METRIC_ORDER:
                self.assertEqual(self.metric_cell(document, metric, "expected"), "미입력")

    def test_08_null_surprise_displays_unavailable(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for metric in build_cpi_release_report.METRIC_ORDER:
                self.assertEqual(self.metric_cell(document, metric, "surprise"), "산출 불가")

    def test_09_null_expected_has_no_direction_claim(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for phrase in ("예상 상회", "예상 하회", "예상 부합"):
                self.assertNotIn(phrase, document)

    def test_10_headline_mom_mapping(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertEqual(self.metric_cell(document, "headline_mom", "actual"), "0.3%")
            self.assertEqual(self.metric_cell(document, "headline_mom", "previous"), "0.5%")

    def test_11_headline_yoy_mapping(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertEqual(self.metric_cell(document, "headline_yoy", "actual"), "2.9%")
            self.assertEqual(self.metric_cell(document, "headline_yoy", "previous"), "3.0%")

    def test_12_core_mom_mapping(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertEqual(self.metric_cell(document, "core_mom", "actual"), "0.2%")
            self.assertEqual(self.metric_cell(document, "core_mom", "previous"), "0.3%")

    def test_13_core_yoy_mapping(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertEqual(self.metric_cell(document, "core_yoy", "actual"), "3.1%")
            self.assertEqual(self.metric_cell(document, "core_yoy", "previous"), "3.2%")

    def test_14_mom_and_yoy_are_not_swapped(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertNotEqual(
                self.metric_cell(document, "headline_mom", "actual"),
                self.metric_cell(document, "headline_yoy", "actual"),
            )
            self.assertNotEqual(
                self.metric_cell(document, "core_mom", "actual"),
                self.metric_cell(document, "core_yoy", "actual"),
            )

    def test_15_headline_and_core_are_not_swapped(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertEqual(self.metric_cell(document, "headline_yoy", "actual"), "2.9%")
            self.assertEqual(self.metric_cell(document, "core_yoy", "actual"), "3.1%")

    def test_16_rule_based_analysis_text_is_mapped(self):
        with self.temp_root(prepared=True) as root:
            wrapper = self.read_analysis(root)
            self.build(root)
            document = self.read_report(root)
            analysis = wrapper["analysis"]
            self.assertIn("<title>2026-06 미국 CPI 발표 리포트</title>", document)
            self.assertIn(analysis["executive_summary"]["one_line"], document)
            self.assertIn(analysis["executive_summary"]["detail"], document)
            self.assertIn("규칙 기반 자동 해석", document)
            self.assertIn("외부 AI API 사용하지 않음", document)

    def test_17_confidence_is_displayed(self):
        with self.temp_root(prepared=True) as root:
            confidence = self.read_analysis(root)["analysis"]["confidence"]
            self.build(root)
            self.assertIn(f"<b>분석 신뢰도</b> {confidence}", self.read_report(root))

    def test_18_unsupported_sections_are_replaced(self):
        with self.temp_root(prepared=True) as root:
            unsupported = self.read_analysis(root)["analysis"]["unsupported_sections"]
            self.build(root)
            document = self.read_report(root)
            self.assertIn(build_cpi_release_report.UNAVAILABLE, document)
            for item in unsupported:
                self.assertIn(item["reason"], document)

    def test_19_sample_market_sentence_is_absent(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertNotIn("S&P500", document)
            self.assertNotIn("시장 관심사", document)

    def test_20_sample_asset_numbers_are_absent(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for marker in ("$6.27T", "나스닥 +1.1%", "BTC +2.4%"):
                self.assertNotIn(marker, document)

    def test_21_sample_scenario_probabilities_are_absent(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for marker in ("기본 — 완만한 리스크온", "Bullish 68", "시나리오 확률"):
                self.assertNotIn(marker, document)

    def test_22_sample_payload_files_are_never_read(self):
        with self.temp_root(prepared=True) as root:
            original = Path.read_bytes

            def guarded(path):
                if path.name in {"sample_payload.json", "canonical_sample_payload.json"}:
                    raise AssertionError(f"sample payload read: {path}")
                return original(path)

            with mock.patch.object(Path, "read_bytes", guarded):
                result = self.build(root)
            self.assertEqual(result.status, "REPORT_CREATED")

    def test_23_final_html_has_zero_unresolved_placeholders(self):
        with self.temp_root(prepared=True) as root:
            result = self.build(root)
            document = self.read_report(root)
            self.assertEqual(result.missing_payload_keys, ())
            self.assertEqual(result.unused_payload_keys, ())
            for pattern in build_cpi_release_report.UNRESOLVED_PATTERNS:
                self.assertIsNone(pattern.search(document))

    def test_24_missing_required_payload_key_fails(self):
        with self.assertRaises(build_cpi_release_report.CpiReportError) as raised:
            build_cpi_release_report.render_flat_template("{{REQUIRED_KEY}}", {})
        self.assertEqual(raised.exception.code, "PAYLOAD_KEY_MISMATCH")

    def test_25_analysis_html_is_escaped(self):
        with self.temp_root(prepared=True) as root:
            attack = '<b title="x">분석</b><a href="javascript:alert(1)">링크</a>'
            self.change_analysis(
                root,
                lambda analysis: analysis["executive_summary"].__setitem__("one_line", attack),
            )
            self.build(root)
            document = self.read_report(root)
            self.assertIn("&lt;b title=&quot;x&quot;&gt;분석&lt;/b&gt;", document)
            self.assertNotIn('<b title="x">', document)
            self.assertNotIn('href="javascript:', document.casefold())

    def test_26_script_tag_in_analysis_is_inert_text(self):
        with self.temp_root(prepared=True) as root:
            attack = "<script>alert('x')</script>"
            self.change_analysis(
                root,
                lambda analysis: analysis["executive_summary"].__setitem__("one_line", attack),
            )
            self.build(root)
            document = self.read_report(root)
            self.assertNotIn("<script", document.casefold())
            self.assertIn("&lt;script&gt;", document)

    def test_27_event_handler_in_analysis_is_inert_text(self):
        with self.temp_root(prepared=True) as root:
            attack = '<img src="x" onerror="alert(1)"><span onclick="x()">문장</span>'
            self.change_analysis(
                root,
                lambda analysis: analysis["executive_summary"].__setitem__("one_line", attack),
            )
            self.build(root)
            document = self.read_report(root)
            self.assertIsNone(build_cpi_release_report.EVENT_HANDLER_RE.search(document))
            self.assertIn("&lt;img", document)
            self.assertIn("onerror=&quot;alert(1)&quot;", document)

    def test_28_no_external_javascript_is_added(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertNotRegex(document.casefold(), r"<script\b")
            self.assertNotIn(".js\"", document.casefold())
            template = build_cpi_release_report.TEMPLATE_PATH.read_text(encoding="utf-8")
            self.assertTrue(set(re.findall(r'href="([^"]+)"', document)).issubset(
                set(re.findall(r'href="([^"]+)"', template))
            ))

    def test_29_design_source_sha_is_unchanged(self):
        before = hashlib.sha256(build_cpi_release_report.DESIGN_SOURCE_PATH.read_bytes()).hexdigest()
        with self.temp_root(prepared=True) as root:
            self.build(root)
        after = hashlib.sha256(build_cpi_release_report.DESIGN_SOURCE_PATH.read_bytes()).hexdigest()
        self.assertEqual(after, before)

    def test_30_report_template_style_blocks_are_unchanged(self):
        template_path = build_cpi_release_report.TEMPLATE_PATH
        before = build_cpi_release_report._extract_styles(template_path.read_text(encoding="utf-8"))
        with self.temp_root(prepared=True) as root:
            self.build(root)
            rendered = self.read_report(root)
            self.assertEqual(build_cpi_release_report._extract_styles(rendered), before)
        after = build_cpi_release_report._extract_styles(template_path.read_text(encoding="utf-8"))
        self.assertEqual(after, before)

    def test_31_parent_output_path_is_rejected(self):
        with self.temp_root(prepared=True) as root:
            with self.assertRaises(build_cpi_release_report.CpiReportError) as raised:
                self.build(root, output="../outside.html")
            self.assertEqual(raised.exception.code, "INVALID_PATH")

    def test_32_absolute_output_outside_project_is_rejected(self):
        with self.temp_root(prepared=True) as root:
            outside = root.parent / "outside-cpi-report.html"
            with self.assertRaises(build_cpi_release_report.CpiReportError) as raised:
                self.build(root, output=str(outside.resolve()))
            self.assertEqual(raised.exception.code, "INVALID_PATH")
            self.assertFalse(outside.exists())

    def test_33_identical_rerun_is_already_up_to_date(self):
        with self.temp_root(prepared=True) as root:
            first = self.build(root)
            second = self.build(root)
            self.assertEqual(first.status, "REPORT_CREATED")
            self.assertEqual(second.status, "ALREADY_UP_TO_DATE")
            self.assertFalse(second.html_created)
            self.assertEqual(second.report_sha256, first.report_sha256)

    def test_34_different_existing_output_is_not_overwritten(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            output = report_output(root)
            output.write_text("existing immutable report\n", encoding="utf-8")
            before = output.read_bytes()
            with self.assertRaises(build_cpi_release_report.CpiReportError) as raised:
                self.build(root)
            self.assertEqual(raised.exception.code, "OUTPUT_CONFLICT")
            self.assertEqual(output.read_bytes(), before)

    def test_35_final_metric_cells_match_canonical(self):
        with self.temp_root(prepared=True, event=complete_calendar_event()) as root:
            canonical = json.loads(canonical_output(root).read_text(encoding="utf-8"))
            self.build(root)
            document = self.read_report(root)
            for metric_key in build_cpi_release_report.METRIC_ORDER:
                group, period = build_cpi_release_report.METRIC_LOCATIONS[metric_key]
                source = canonical["event"][group][period]
                expected = {
                    "actual": source["actual_as_released_display"],
                    "previous": source["previous_as_released_display"],
                    "expected": f"{source['expected']}%",
                    "surprise": source["surprise"]["display"],
                }
                for field, value in expected.items():
                    self.assertEqual(self.metric_cell(document, metric_key, field), value)

    def test_36_report_sha256_is_generated(self):
        with self.temp_root(prepared=True) as root:
            result = self.build(root)
            expected = hashlib.sha256(report_output(root).read_bytes()).hexdigest()
            self.assertEqual(result.report_sha256, expected)
            self.assertRegex(result.report_sha256, r"^[0-9a-f]{64}$")

    def test_37_api_keys_and_tokens_are_absent(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            for marker in ("OPENAI_API_KEY", "BLS_API_KEY", "GITHUB_TOKEN", "sk-"):
                self.assertNotIn(marker, document)

    def test_38_windows_absolute_paths_are_absent(self):
        with self.temp_root(prepared=True) as root:
            self.build(root)
            document = self.read_report(root)
            self.assertNotIn(str(root), document)
            self.assertNotRegex(document, r"[A-Za-z]:\\")

    def test_39_fixture_never_touches_actual_docs(self):
        before = ACTUAL_REPORT.read_bytes() if ACTUAL_REPORT.exists() else None
        with self.temp_root(prepared=True) as root:
            self.build(root)
            self.assertTrue(report_output(root).exists())
        after = ACTUAL_REPORT.read_bytes() if ACTUAL_REPORT.exists() else None
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
