from __future__ import annotations
import copy, json, unittest
from pathlib import Path
from scripts.collectors import bls_cpi_components as components

ROOT=Path(__file__).resolve().parents[1]

def registry():
    value=json.loads((ROOT/"config/bls_cpi_component_series.json").read_text(encoding="utf-8"))
    for item in value["components"]:
        if item["component_id"] not in value["core_components"]: item["mapping_status"]="REVIEW_REQUIRED"
    return value

def response(reg=None):
    reg=reg or registry(); rows=[]
    for index,series_id in enumerate(components.requested_series(reg)):
        base=Decimal("100")+Decimal(index)
        data=[{"year":"2026","period":"M06","value":str(base+2)},{"year":"2026","period":"M05","value":str(base+1)},{"year":"2025","period":"M06","value":str(base)}]
        rows.append({"seriesID":series_id,"data":data})
    return {"status":"REQUEST_SUCCEEDED","Results":{"series":rows}}

from decimal import Decimal

class BlsCpiComponentsTests(unittest.TestCase):
    def parse(self, raw=None, reg=None): return components.parse_component_response(raw or response(reg),reg or registry())
    def test_01_normal_fixture_parses(self): self.assertEqual(len(self.parse()),12)
    def test_02_deterministic_parse(self): self.assertEqual(self.parse(),self.parse())
    def test_03_m13_is_ignored(self):
        raw=response(); raw["Results"]["series"][0]["data"].append({"year":"2026","period":"M13","value":"999"}); self.parse(raw)
    def test_04_missing_series_is_blocked(self):
        raw=response(); raw["Results"]["series"].pop()
        with self.assertRaisesRegex(components.ComponentError,"missing"): self.parse(raw)
    def test_05_duplicate_series_is_blocked(self):
        raw=response(); raw["Results"]["series"].append(copy.deepcopy(raw["Results"]["series"][0]))
        with self.assertRaisesRegex(components.ComponentError,"duplicate series"): self.parse(raw)
    def test_06_unexpected_series_is_blocked(self):
        raw=response(); raw["Results"]["series"].append({"seriesID":"CUUR999999999","data":[]})
        with self.assertRaisesRegex(components.ComponentError,"unexpected"): self.parse(raw)
    def test_07_non_numeric_is_blocked(self):
        raw=response(); raw["Results"]["series"][0]["data"][0]["value"]="no"
        with self.assertRaises(components.ComponentError): self.parse(raw)
    def test_08_malformed_status_is_blocked(self):
        with self.assertRaises(components.ComponentError): self.parse({"status":"REQUEST_FAILED"})
    def test_09_common_period_is_found(self): self.assertEqual(components.find_common_component_period(self.parse(),registry()),"2026-06")
    def test_10_period_mismatch_is_blocked(self):
        raw=response(); raw["Results"]["series"][0]["data"]=[{"year":"2026","period":"M06","value":"101"}]
        with self.assertRaises(components.ComponentError): components.find_common_component_period(self.parse(raw),registry())
    def test_11_metrics_preserve_decimal_and_round_display(self):
        metrics=components.build_component_metrics(self.parse(),registry()); one=metrics["components"][0]["mom"]
        self.assertEqual(one["raw"],"0.9615384615384615384615384615385"); self.assertEqual(one["display"],"1.0%")
    def test_12_mom_and_yoy_use_distinct_series(self):
        one=components.build_component_metrics(self.parse(),registry())["components"][0]; self.assertNotEqual(one["mom"]["series_id"],one["yoy"]["series_id"])
    def test_13_contribution_is_unavailable_without_weight_formula(self):
        result=components.build_component_metrics(self.parse(),registry()); self.assertEqual(result["contribution_status"],"CONTRIBUTION_UNAVAILABLE"); self.assertIsNone(result["components"][0]["contribution"]["contribution_raw"])
    def test_14_observation_is_fixture_only(self):
        parsed=self.parse(); metrics=components.build_component_metrics(parsed,registry()); value=components.build_component_observation(parsed,metrics,registry(),"2026-07-01T00:00:00Z","component-fixture")
        self.assertTrue(value["validation"]["test_fixture"]); self.assertFalse(value["provenance"]["live_api_called"])
    def test_15_snapshot_sha_is_stable(self):
        metrics=components.build_component_metrics(self.parse(),registry()); a=components.build_component_snapshot(metrics,registry(),"2026-07-01T00:00:00Z","component-fixture"); b=components.build_component_snapshot(metrics,registry(),"2026-07-01T00:00:00Z","component-fixture"); self.assertEqual(a["integrity"]["sha256"],b["integrity"]["sha256"])
    def test_16_snapshot_is_immutable(self):
        value=components.build_component_snapshot(components.build_component_metrics(self.parse(),registry()),registry(),"2026-07-01T00:00:00Z","component-fixture"); self.assertTrue(value["integrity"]["immutable"])
    def test_17_no_actual_or_previous_fields_are_used(self):
        text=json.dumps(components.build_component_metrics(self.parse(),registry())); self.assertNotIn('"actual"',text); self.assertNotIn('"previous"',text)
    def test_18_fixture_is_not_project_data(self): self.assertFalse((ROOT/"data/consensus/cpi/components").exists())
    def test_19_malformed_json_is_blocked(self):
        with self.assertRaises(components.ComponentError): components.parse_component_fixture_bytes(b"{",registry())
    def test_20_malformed_utf8_is_blocked(self):
        with self.assertRaises(components.ComponentError): components.parse_component_fixture_bytes(b"\xff",registry())
    def test_21_credential_key_is_blocked(self):
        raw=response(); raw["api_key"]="no"
        with self.assertRaises(components.ComponentError): components.parse_component_fixture_bytes(json.dumps(raw).encode(),registry())
    def test_22_fixture_traversal_is_blocked(self):
        with self.assertRaises(components.ComponentError): components.build_component_snapshot(components.build_component_metrics(self.parse(),registry()),registry(),"2026-07-01T00:00:00Z","../bad")
    def test_23_fixture_backslash_is_blocked(self):
        with self.assertRaises(components.ComponentError): components.build_component_snapshot(components.build_component_metrics(self.parse(),registry()),registry(),"2026-07-01T00:00:00Z","bad\\fixture")

if __name__=="__main__": unittest.main()
