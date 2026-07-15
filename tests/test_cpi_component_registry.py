from __future__ import annotations
import copy, json, unittest
from pathlib import Path
from scripts.collectors import bls_cpi_components as components

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=json.loads((ROOT/"config/bls_cpi_component_series.json").read_text(encoding="utf-8"))

class CpiComponentRegistryTests(unittest.TestCase):
    def test_01_registry_hierarchy_is_valid(self): components.validate_component_hierarchy(REGISTRY)
    def test_02_core_set_has_six_components(self): self.assertEqual(len(REGISTRY["core_components"]),6)
    def test_03_approved_components_have_official_references(self): self.assertTrue(all(item["official_reference"].startswith("https://www.bls.gov/") or item["official_reference"].startswith("https://download.bls.gov/") for item in REGISTRY["components"] if item["mapping_status"]=="APPROVED"))
    def test_04_mom_is_sa_and_yoy_is_nsa(self): self.assertTrue(all(item["mom_seasonal_adjustment"]=="seasonally_adjusted" and item["yoy_seasonal_adjustment"]=="not_seasonally_adjusted" for item in REGISTRY["components"] if item["mapping_status"]=="APPROVED"))
    def test_05_parent_child_aggregation_is_forbidden(self): self.assertTrue(all(not item["aggregation_allowed"] for item in REGISTRY["components"] if item["child_components"]))
    def test_06_duplicate_series_mapping_is_rejected(self):
        value=copy.deepcopy(REGISTRY); value["components"][1]["mom_series_id"]=value["components"][0]["mom_series_id"]
        with self.assertRaises(components.ComponentError): components.validate_component_hierarchy(value)
    def test_07_unknown_parent_is_rejected(self):
        value=copy.deepcopy(REGISTRY); value["components"][0]["parent_component"]="missing"
        with self.assertRaises(components.ComponentError): components.validate_component_hierarchy(value)
    def test_08_requested_series_uses_approved_only(self):
        value=copy.deepcopy(REGISTRY); value["components"][0]["mapping_status"]="REVIEW_REQUIRED"
        self.assertNotIn(REGISTRY["components"][0]["mom_series_id"],components.requested_series(value))
    def test_09_no_credentials_in_registry(self):
        text=(ROOT/"config/bls_cpi_component_series.json").read_text(encoding="utf-8").lower()
        for token in ("api_key","token","password","secret","authorization"): self.assertNotIn(token,text)
    def test_10_no_live_transport_is_present(self): self.assertNotIn("urlopen",Path(components.__file__).read_text(encoding="utf-8"))
