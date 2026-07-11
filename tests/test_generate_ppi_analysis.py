from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.analysis import generate_ppi_analysis as analysis
from scripts.pipelines import build_ppi_historical_canonical as canonical
from tests.test_build_ppi_historical_canonical import PpiCanonicalTests


class PpiAnalysisTests(unittest.TestCase):
    def canonical(self):
        return canonical.build_canonical("US_PPI_2026_05", "2026-05", "2026-06-11T12:30:00Z", PpiCanonicalTests().observation())

    def test_rule_based_is_free_without_external_ai(self):
        result = analysis.build_analysis(self.canonical(), "US_PPI_2026_05", datetime(2026, 7, 11, tzinfo=timezone.utc))
        self.assertEqual(result["provider"]["name"], "rule_based")
        self.assertFalse(result["provider"]["external_ai_api_called"])
        self.assertEqual(result["usage"]["cost"], "free")

    def test_analysis_states_limits_without_market_or_policy_prediction(self):
        result = analysis.build_analysis(self.canonical(), "US_PPI_2026_05", datetime(2026, 7, 11, tzinfo=timezone.utc))
        text = " ".join(result["analysis"]["limitations"])
        self.assertIn("trade services", result["analysis"]["core"])
        self.assertIn("does not establish", text)
        self.assertIn("unavailable", text)
