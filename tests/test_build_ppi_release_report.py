from __future__ import annotations

import hashlib
import copy
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.analysis import generate_ppi_analysis as analysis
from scripts.pipelines import build_ppi_historical_canonical as canonical
from scripts.pipelines import build_ppi_release_report as report
from tests.test_build_ppi_historical_canonical import PpiCanonicalTests


ROOT = Path(__file__).resolve().parents[1]


class PpiReportTests(unittest.TestCase):
    def inputs(self):
        value = canonical.build_canonical("US_PPI_2026_05", "2026-05", "2026-06-11T12:30:00Z", PpiCanonicalTests().observation())
        return value, analysis.build_analysis(value, "US_PPI_2026_05", datetime(2026, 7, 11, tzinfo=timezone.utc))

    def test_four_values_warning_and_design_blocks_are_preserved(self):
        value, interpreted = self.inputs()
        template = (ROOT / "templates/report.html").read_text(encoding="utf-8")
        document = report.build_report(value, interpreted, ROOT / "templates/report.html")
        self.assertNotIn("{{", document)
        self.assertIn("미국 생산자물가지수(PPI)", document)
        self.assertIn("전월비 1.3% · 전년비 1.3%", document)
        self.assertIn("무역서비스", document)
        for display in ("1.3%",):
            self.assertIn(display, document)
        self.assertEqual(document.count("미입력"), 5)
        self.assertEqual(document.count("산출하지 않음"), 4)
        self.assertIn("PPI 핵심 지표", document)
        self.assertIn("규칙 기반 PPI 해석", document)
        self.assertIn("데이터 가용성", document)
        self.assertIn("발표 당시 실시간으로 포착한 값이 아닙니다", document)
        self.assertIn("비용은 무료입니다", document)
        self.assertEqual(document.count('id="data-availability-summary"'), 1)
        self.assertNotIn("data-optional-section", document)
        self.assertNotIn("정보 없음", document)
        visible_text = re.sub(r"<style\b[^>]*>.*?</style\s*>", "", document, flags=re.I | re.S)
        self.assertNotRegex(visible_text.lower(), r"\b(null|none|undefined)\b")
        self.assertNotIn('class="card"></div>', document)
        self.assertEqual(re.findall(r"<style\b[^>]*>.*?</style\s*>", template, re.I | re.S), re.findall(r"<style\b[^>]*>.*?</style\s*>", document, re.I | re.S))
        self.assertEqual(re.findall(r"<script\b[^>]*>.*?</script\s*>", template, re.I | re.S), re.findall(r"<script\b[^>]*>.*?</script\s*>", document, re.I | re.S))

    def test_partial_optional_data_renders_only_the_present_group_and_value(self):
        value, interpreted = self.inputs()
        value = copy.deepcopy(value)
        value["optional_data"] = {"market_reaction": {"S&P 500": "1.0%", "Nasdaq": None}, "asset_prices": {"Dollar": ""}}
        value["integrity"]["sha256"] = canonical.sha256_payload(value)
        document = report.build_report(value, interpreted, ROOT / "templates/report.html")
        self.assertIn('data-optional-section="market_reaction"', document)
        self.assertNotIn('data-optional-section="asset_prices"', document)
        self.assertIn("S&amp;P 500", document)
        self.assertNotIn("Nasdaq", document)
