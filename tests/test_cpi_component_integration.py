from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analysis import generate_cpi_analysis
from scripts.collectors import bls_cpi_components as components
from scripts.pipelines import build_cpi_release_canonical as canonical
from scripts.pipelines import build_cpi_release_report as report
from scripts.providers import rule_based


ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = "US_CPI_2026_06"


def registry():
    return json.loads((ROOT / "config" / "bls_cpi_component_series.json").read_text(encoding="utf-8"))


def component_snapshot():
    rows = []
    for item in registry()["components"]:
        if item["mapping_status"] != "APPROVED":
            continue
        rows.append(
            {
                "component_id": item["component_id"],
                "mom": {"display": "0.2%", "raw": "0.2"},
                "yoy": {"display": "2.5%", "raw": "2.5"},
                "contribution": {"contribution_display": "UNAVAILABLE_WEIGHT_OR_FORMULA"},
            }
        )
    value = {
        "schema_version": "cpi-component-release-v1",
        "event_id": EVENT_ID,
        "reference_period": "2026-06",
        "raw_snapshot_path": "data/raw/bls/cpi_components/2026-06/retrieved_fixture.json",
        "raw_snapshot_sha256": "raw-fixture-sha",
        "provider": "U.S. Bureau of Labor Statistics",
        "registry_version": registry()["registry_version"],
        "registry_sha256": "registry-fixture-sha",
        "components": rows,
        "completeness": "COMPLETE",
        "contribution_status": "CONTRIBUTION_UNAVAILABLE",
        "integrity": {"immutable": True, "sha256": None},
    }
    value["integrity"]["sha256"] = components._sha(value)
    return value


class CpiComponentIntegrationTests(unittest.TestCase):
    def write_snapshot(self, root: Path, value: dict):
        path = root / "data" / "releases" / "cpi" / EVENT_ID / "components_as_released.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_canonical_component_breakdown_is_unavailable_without_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                canonical.load_component_breakdown(root, {"event_id": EVENT_ID, "reference_period": "2026-06"})["status"],
                "unavailable",
            )

    def test_canonical_component_breakdown_includes_only_immutable_snapshot_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "bls_cpi_component_series.json").write_text(json.dumps(registry()), encoding="utf-8")
            self.write_snapshot(root, component_snapshot())
            value = canonical.load_component_breakdown(root, {"event_id": EVENT_ID, "reference_period": "2026-06"})
            self.assertEqual(value["status"], "available")
            self.assertEqual(len(value["components"]), 16)
            self.assertEqual(value["components"][0]["contribution"]["contribution_display"], "UNAVAILABLE_WEIGHT_OR_FORMULA")

    def test_invalid_component_snapshot_falls_back_without_breaking_headline_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "bls_cpi_component_series.json").write_text(json.dumps(registry()), encoding="utf-8")
            value = component_snapshot()
            value["integrity"]["sha256"] = "tampered"
            self.write_snapshot(root, value)
            result = canonical.load_component_breakdown(root, {"event_id": EVENT_ID, "reference_period": "2026-06"})
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "COMPONENT_RELEASE_INVALID")

    def test_incomplete_complete_claim_is_rejected_by_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "bls_cpi_component_series.json").write_text(json.dumps(registry()), encoding="utf-8")
            value = component_snapshot()
            value["components"].pop()
            value["integrity"]["sha256"] = components._sha(value)
            self.write_snapshot(root, value)
            result = canonical.load_component_breakdown(root, {"event_id": EVENT_ID, "reference_period": "2026-06"})
            self.assertEqual(result["status"], "unavailable")

    def test_analysis_facts_and_rule_based_output_mark_component_availability(self):
        source = {
            "meta": {"event_id": EVENT_ID, "reference_period": "2026-06", "release_datetime_kst": "2026-07-14T21:30:00+09:00"},
            "event": {
                "headline": {"mom": {"actual_as_released_raw": "0.1", "actual_as_released_display": "0.1%", "previous_as_released_raw": "0.2", "previous_as_released_display": "0.2%", "expected": None, "surprise": None}, "yoy": {"actual_as_released_raw": "2.0", "actual_as_released_display": "2.0%", "previous_as_released_raw": "2.1", "previous_as_released_display": "2.1%", "expected": None, "surprise": None}},
                "core": {"mom": {"actual_as_released_raw": "0.1", "actual_as_released_display": "0.1%", "previous_as_released_raw": "0.2", "previous_as_released_display": "0.2%", "expected": None, "surprise": None}, "yoy": {"actual_as_released_raw": "2.0", "actual_as_released_display": "2.0%", "previous_as_released_raw": "2.1", "previous_as_released_display": "2.1%", "expected": None, "surprise": None}},
            },
            "component_breakdown": {"status": "available", "components": [{"component_id": "shelter"}]},
        }
        facts = generate_cpi_analysis.build_facts(source)
        self.assertEqual(facts["component_breakdown"]["status"], "available")
        analysis = rule_based.generate_analysis(facts=facts).analysis
        self.assertNotIn("component_breakdown", [item["section"] for item in analysis["unsupported_sections"]])

    def test_renderer_has_available_and_unavailable_component_sections(self):
        unavailable = report._build_component_section({"component_breakdown": {"status": "unavailable"}})
        available = report._build_component_section({"component_breakdown": {"status": "available", "components": [{"display_name_ko": "Shelter", "display_group": "core", "mom": {"display": "0.2%"}, "yoy": {"display": "2.5%"}, "contribution": {"contribution_display": "UNAVAILABLE"}}]}})
        self.assertIn('data-component-breakdown="unavailable"', unavailable)
        self.assertIn('data-component-breakdown="available"', available)
        self.assertIn("0.2%", available)
        self.assertNotIn("Bloomberg", available)


if __name__ == "__main__":
    unittest.main()
