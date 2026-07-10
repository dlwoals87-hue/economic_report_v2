from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.analysis import generate_cpi_analysis
from scripts.providers import rule_based


ROOT = Path(__file__).resolve().parents[1]
METRIC_KEYS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")


def make_facts(directions=None, *, consensus=False):
    directions = directions or {key: "decelerating" for key in METRIC_KEYS}
    metrics = {}
    percentage_tokens = []
    percentage_point_tokens = []
    for key in METRIC_KEYS:
        direction = directions[key]
        if direction == "accelerating":
            actual, previous = "0.5", "0.4"
        elif direction == "decelerating":
            actual, previous = "0.3", "0.4"
        else:
            actual, previous = "0.4", "0.4"
        actual_display = f"{actual}%"
        previous_display = f"{previous}%"
        for token in (actual_display, previous_display):
            if token not in percentage_tokens:
                percentage_tokens.append(token)

        expected = "0.4" if consensus else None
        surprise = None
        if consensus:
            difference = Decimal(actual) - Decimal(expected)
            raw = format(difference, "f").rstrip("0").rstrip(".") or "0"
            display = f"{difference:.1f}%p"
            surprise = {
                "raw": raw,
                "display": display,
                "direction": (
                    "above_expected"
                    if difference > 0
                    else "below_expected"
                    if difference < 0
                    else "in_line"
                ),
            }
            if "0.4%" not in percentage_tokens:
                percentage_tokens.append("0.4%")
            if display not in percentage_point_tokens:
                percentage_point_tokens.append(display)

        metrics[key] = {
            "actual": actual,
            "actual_display": actual_display,
            "previous": previous,
            "previous_display": previous_display,
            "expected": expected,
            "surprise": surprise,
            "change_from_previous_raw": str(Decimal(actual) - Decimal(previous)),
            "momentum_direction": direction,
        }
    return {
        "event_id": "US_CPI_TEST",
        "reference_period": "2026-06",
        "release_datetime_kst": "2026-07-14T21:30:00+09:00",
        "metrics": metrics,
        "consensus_available": consensus,
        "allowed_percentage_tokens": percentage_tokens,
        "allowed_percentage_point_tokens": percentage_point_tokens,
    }


def generate(facts):
    return rule_based.generate_analysis(facts=facts).analysis


class RuleBasedAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(
            (ROOT / "schemas" / "cpi_analysis_v1.schema.json").read_text(encoding="utf-8")
        )

    def test_external_api_calls_are_zero(self):
        result = rule_based.generate_analysis(facts=make_facts())
        self.assertFalse(result.external_api_called)
        self.assertEqual(result.api_calls, 0)
        self.assertEqual(result.usage, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})

    def test_output_satisfies_schema_and_all_post_validation(self):
        facts = make_facts()
        validation = generate_cpi_analysis.validate_analysis_output(
            generate(facts),
            self.schema,
            facts,
        )
        self.assertTrue(all(validation.values()))

    def test_actual_and_previous_displays_are_in_sentences(self):
        facts = make_facts()
        analysis = generate(facts)
        details = " ".join(point["detail"] for point in analysis["key_points"])
        for metric in facts["metrics"].values():
            self.assertIn(metric["actual_display"], details)
            self.assertIn(metric["previous_display"], details)

    def test_no_consensus_uses_no_above_or_below_claim(self):
        text = json.dumps(generate(make_facts()), ensure_ascii=False)
        self.assertNotIn("예상 상회", text)
        self.assertNotIn("예상 하회", text)
        self.assertNotIn("상회 방향", text)
        self.assertNotIn("하회 방향", text)

    def test_consensus_uses_canonical_surprise_directions(self):
        directions = {
            "headline_mom": "accelerating",
            "headline_yoy": "decelerating",
            "core_mom": "unchanged",
            "core_yoy": "accelerating",
        }
        text = json.dumps(generate(make_facts(directions, consensus=True)), ensure_ascii=False)
        self.assertIn("상회 방향", text)
        self.assertIn("하회 방향", text)
        self.assertIn("부합 방향", text)

    def test_headline_acceleration_interpretation(self):
        directions = {key: "unchanged" for key in METRIC_KEYS}
        directions["headline_mom"] = "accelerating"
        directions["headline_yoy"] = "accelerating"
        analysis = generate(make_facts(directions))
        self.assertIn("강화", analysis["inflation_interpretation"]["headline"])

    def test_headline_deceleration_interpretation(self):
        directions = {key: "unchanged" for key in METRIC_KEYS}
        directions["headline_mom"] = "decelerating"
        directions["headline_yoy"] = "decelerating"
        analysis = generate(make_facts(directions))
        self.assertIn("둔화", analysis["inflation_interpretation"]["headline"])

    def test_core_acceleration_interpretation(self):
        directions = {key: "unchanged" for key in METRIC_KEYS}
        directions["core_mom"] = "accelerating"
        directions["core_yoy"] = "accelerating"
        analysis = generate(make_facts(directions))
        self.assertIn("강화", analysis["inflation_interpretation"]["core"])

    def test_core_deceleration_interpretation(self):
        directions = {key: "unchanged" for key in METRIC_KEYS}
        directions["core_mom"] = "decelerating"
        directions["core_yoy"] = "decelerating"
        analysis = generate(make_facts(directions))
        self.assertIn("둔화", analysis["inflation_interpretation"]["core"])

    def test_policy_signal_hawkish(self):
        facts = make_facts({key: "accelerating" for key in METRIC_KEYS})
        self.assertEqual(generate(facts)["policy_implication"]["signal"], "hawkish")

    def test_policy_signal_dovish(self):
        facts = make_facts({key: "decelerating" for key in METRIC_KEYS})
        self.assertEqual(generate(facts)["policy_implication"]["signal"], "dovish")

    def test_policy_signal_mixed(self):
        directions = {
            "headline_mom": "accelerating",
            "headline_yoy": "decelerating",
            "core_mom": "accelerating",
            "core_yoy": "decelerating",
        }
        self.assertEqual(generate(make_facts(directions))["policy_implication"]["signal"], "mixed")

    def test_confidence_is_not_high_without_consensus(self):
        self.assertIn(generate(make_facts())["confidence"], ("medium", "low"))

    def test_all_unsupported_sections_are_included(self):
        sections = {item["section"] for item in generate(make_facts())["unsupported_sections"]}
        self.assertEqual(sections, set(rule_based.UNSUPPORTED_REASONS))

    def test_evidence_paths_are_valid(self):
        facts = make_facts()
        analysis = generate(facts)
        generate_cpi_analysis.validate_evidence_paths(analysis, facts)

    def test_no_new_percentage_tokens_are_created(self):
        facts = make_facts()
        analysis = generate(facts)
        allowed = set(facts["allowed_percentage_tokens"])
        found = {
            match.group(0).replace(" ", "")
            for text in generate_cpi_analysis._validated_text_fields(analysis)
            for match in generate_cpi_analysis.PERCENT_TOKEN_RE.finditer(text)
            if not match.group(0).replace(" ", "").endswith("%p")
        }
        self.assertTrue(found <= allowed)

    def test_no_new_percentage_point_tokens_are_created(self):
        facts = make_facts({key: "accelerating" for key in METRIC_KEYS}, consensus=True)
        analysis = generate(facts)
        allowed = set(facts["allowed_percentage_point_tokens"])
        found = {
            match.group(0).replace(" ", "")
            for text in generate_cpi_analysis._validated_text_fields(analysis)
            for match in generate_cpi_analysis.PERCENT_TOKEN_RE.finditer(text)
            if match.group(0).replace(" ", "").endswith("%p")
        }
        self.assertTrue(found <= allowed)


if __name__ == "__main__":
    unittest.main()
