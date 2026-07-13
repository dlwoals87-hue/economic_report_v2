import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.collectors import bls_employment as nfp


def payload(include_catalog=False):
    def series(series_id, values):
        row = {
            "seriesID": series_id,
            "data": [
                {"year": year, "period": period, "value": value}
                for year, period, value in values
            ],
        }
        if include_catalog:
            contract = nfp.OFFICIAL_SERIES_CONTRACT[series_id]
            row["catalog"] = {
                "title": contract["official_title"],
                "seasonality": contract["seasonality"],
                "frequency": contract["frequency"],
                "unit": contract["source_level_unit"],
                "measure_data_type": contract["measure_data_type"],
            }
        return row

    return {
        "Results": {
            "series": [
                series(nfp.SERIES["payroll"], [("2026", "M06", "159000"), ("2026", "M05", "158850")]),
                series(nfp.SERIES["unemployment"], [("2026", "M06", "4.1")]),
                series(nfp.SERIES["ahe"], [("2026", "M06", "36.50"), ("2026", "M05", "36.32")]),
            ]
        }
    }


def result(value, reference="2026-06"):
    return nfp.collect_from_response(value, reference, "2026-07-12T00:00:00Z")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATHS = (
    "data/calendar/events.json",
    "data/releases",
    "data/consensus",
    "data/generated",
    "data/analysis",
    ".github/workflows",
)


def protected_snapshot():
    snapshot = {}
    for relative in PROTECTED_PATHS:
        path = PROJECT_ROOT / relative
        if path.is_file():
            snapshot[relative] = nfp.stable_sha(path.read_bytes().hex())
        elif path.exists():
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                snapshot[str(child.relative_to(PROJECT_ROOT)).replace("\\", "/")] = nfp.stable_sha(child.read_bytes().hex())
    return snapshot


class NfpTests(unittest.TestCase):
    def test_official_series_contract_is_exact(self):
        self.assertEqual(set(nfp.OFFICIAL_SERIES_CONTRACT), set(nfp.SERIES.values()))
        self.assertEqual(nfp.OFFICIAL_SERIES_CONTRACT[nfp.SERIES["payroll"]]["role"], "payroll_level")
        self.assertEqual(nfp.OFFICIAL_SERIES_CONTRACT[nfp.SERIES["unemployment"]]["role"], "unemployment_rate")
        self.assertEqual(nfp.OFFICIAL_SERIES_CONTRACT[nfp.SERIES["ahe"]]["role"], "average_hourly_earnings_level")

    def test_catalog_metadata_exact_match_and_local_contract_mode(self):
        verified = result(payload(include_catalog=True))
        self.assertEqual(verified["status"], "NFP_BLS_COLLECTED")
        self.assertEqual(verified["metadata_validation"]["mode"], "api_catalog_verified")
        self.assertTrue(verified["metadata_validation"]["metadata_from_api_response"])
        local = result(payload())
        self.assertEqual(local["metadata_validation"]["mode"], "local_official_contract")
        self.assertFalse(local["metadata_validation"]["metadata_from_api_response"])

    def test_catalog_contract_mismatches_are_blocked(self):
        for series_id, field, value in (
            (nfp.SERIES["payroll"], "title", "Total payrolls"),
            (nfp.SERIES["unemployment"], "title", "Unemployment Rate"),
            (nfp.SERIES["ahe"], "title", "Average hourly earnings manufacturing"),
            (nfp.SERIES["payroll"], "seasonality", "Not Seasonally Adjusted"),
            (nfp.SERIES["payroll"], "measure_data_type", "ALL EMPLOYEES"),
            (nfp.SERIES["payroll"], "frequency", "quarterly"),
            (nfp.SERIES["payroll"], "unit", "persons"),
        ):
            with self.subTest(series_id=series_id, field=field):
                broken = payload(include_catalog=True)
                row = next(item for item in broken["Results"]["series"] if item["seriesID"] == series_id)
                row["catalog"][field] = value
                self.assertEqual(result(broken)["status"], "NFP_SERIES_CONTRACT_UNVERIFIED")

    def test_series_missing_duplicate_extra_and_invalid_structure(self):
        for series_id in nfp.SERIES.values():
            with self.subTest(missing=series_id):
                broken = payload()
                broken["Results"]["series"] = [row for row in broken["Results"]["series"] if row["seriesID"] != series_id]
                partial = result(broken)
                self.assertEqual(partial["status"], "NFP_BLS_PARTIAL")
                self.assertEqual(partial["incomplete_reason"], "NFP_BLS_SERIES_MISSING")
        absent = {"Results": {"series": []}}
        self.assertEqual(result(absent)["status"], "NFP_BLS_SERIES_MISSING")
        duplicate = payload()
        duplicate["Results"]["series"].append(copy.deepcopy(duplicate["Results"]["series"][0]))
        self.assertEqual(result(duplicate)["status"], "NFP_BLS_DUPLICATE_SERIES")
        extra = payload()
        extra["Results"]["series"].append({"seriesID": "CES9999999999", "data": []})
        collected = result(extra)
        self.assertEqual(collected["status"], "NFP_BLS_COLLECTED")
        self.assertEqual(collected["metadata_validation"]["ignored_extra_series_ids"], ["CES9999999999"])
        invalid = payload()
        invalid["Results"]["series"] = {}
        self.assertEqual(result(invalid)["status"], "NFP_BLS_INVALID_RESPONSE")
        invalid = payload()
        invalid["Results"]["series"][0]["data"] = {}
        self.assertEqual(result(invalid)["status"], "NFP_BLS_INVALID_RESPONSE")

    def test_period_validation_and_reference_errors(self):
        duplicate = payload()
        duplicate["Results"]["series"][0]["data"].append({"year": "2026", "period": "M06", "value": "1"})
        self.assertEqual(result(duplicate)["status"], "NFP_BLS_DUPLICATE_PERIOD")
        for bad_period in ("M13", "M00", "Q01", "M1"):
            with self.subTest(period=bad_period):
                broken = payload()
                broken["Results"]["series"][0]["data"][0]["period"] = bad_period
                self.assertEqual(result(broken)["status"], "NFP_BLS_INVALID_RESPONSE")
        missing_current = payload()
        missing_current["Results"]["series"][1]["data"] = []
        self.assertEqual(result(missing_current)["status"], "NFP_BLS_PARTIAL")
        self.assertEqual(result(missing_current)["incomplete_reason"], "NFP_BLS_PERIOD_MISSING")
        missing_previous = payload()
        missing_previous["Results"]["series"][2]["data"] = [{"year": "2026", "period": "M06", "value": "36.5"}]
        self.assertEqual(result(missing_previous)["status"], "NFP_BLS_PARTIAL")
        self.assertEqual(result(missing_previous)["incomplete_reason"], "NFP_BLS_PERIOD_MISSING")
        gap = payload()
        gap["Results"]["series"][0]["data"][1]["period"] = "M04"
        self.assertEqual(result(gap)["status"], "NFP_BLS_PERIOD_GAP")
        stale = payload()
        stale["Results"]["series"][0]["data"] = [{"year": "2026", "period": "M05", "value": "159000"}]
        stale["Results"]["series"][1]["data"] = [{"year": "2026", "period": "M05", "value": "4.1"}]
        stale["Results"]["series"][2]["data"] = [{"year": "2026", "period": "M05", "value": "36.50"}]
        self.assertEqual(result(stale)["status"], "NFP_BLS_STALE")
        future = payload()
        for row in future["Results"]["series"]:
            row["data"] = [{"year": "2026", "period": "M07", "value": "1"}]
        self.assertEqual(result(future)["status"], "NFP_BLS_REFERENCE_MISMATCH")

    def test_year_boundary_and_numeric_validation(self):
        boundary = payload()
        boundary["Results"]["series"][0]["data"] = [{"year": "2026", "period": "M01", "value": "159000"}, {"year": "2025", "period": "M12", "value": "158900"}]
        boundary["Results"]["series"][1]["data"] = [{"year": "2026", "period": "M01", "value": "4.0"}]
        boundary["Results"]["series"][2]["data"] = [{"year": "2026", "period": "M01", "value": "36.5"}, {"year": "2025", "period": "M12", "value": "36.4"}]
        self.assertEqual(result(boundary, "2026-01")["metrics"]["nonfarm_payroll_change_k"]["value"], "100")
        boundary["Results"]["series"][0]["data"][1]["period"] = "M11"
        self.assertEqual(result(boundary, "2026-01")["status"], "NFP_BLS_PERIOD_GAP")
        for value in ("nope", "NaN", "Infinity", "-Infinity", True, {"value": 1}, [1]):
            with self.subTest(value=repr(value)):
                broken = payload()
                broken["Results"]["series"][0]["data"][0]["value"] = value
                self.assertEqual(result(broken)["status"], "NFP_BLS_INVALID_VALUE")
        zero = payload()
        zero["Results"]["series"][2]["data"][1]["value"] = "0"
        self.assertEqual(result(zero)["status"], "NFP_BLS_DIVIDE_BY_ZERO")

    def test_calculation_statuses_and_hashes(self):
        collected = result(payload())
        self.assertEqual(collected["status"], "NFP_BLS_COLLECTED")
        self.assertEqual(collected["metrics"]["nonfarm_payroll_change_k"]["value"], "150")
        self.assertEqual(collected["metrics"]["unemployment_rate"]["value"], "4.1")
        self.assertEqual(collected["metrics"]["average_hourly_earnings_mom"]["value"], "0.4955947136563876651982379")
        self.assertEqual(collected["data_origin"], "historical_backfill")
        self.assertTrue(collected["not_as_released"])
        self.assertFalse(collected["external_api_called"])
        self.assertFalse(collected["external_ai_api_called"])
        self.assertEqual(collected["cost"], "free")
        self.assertEqual(collected["source_periods"]["nonfarm_payroll_change_k"]["previous"], "2026-05")
        self.assertEqual(collected["metrics"]["average_hourly_earnings_mom"]["rounding"], "Decimal precision 28; no additional rounding")
        self.assertEqual(collected["raw_response_sha256"], nfp.stable_sha(payload()))
        self.assertEqual(collected["integrity"]["sha256"], nfp.stable_sha({**collected, "integrity": {}}))
        self.assertTrue(nfp.integrity_matches(collected))
        for status in ("NFP_BLS_DUPLICATE_SERIES", "NFP_BLS_DUPLICATE_PERIOD", "NFP_BLS_INVALID_VALUE"):
            with self.subTest(status=status):
                self.assertNotEqual(status, "NFP_BLS_PARTIAL")

    def test_provenance_hashes_and_integrity_detect_mutation(self):
        first = result(payload())
        second = result(payload())
        self.assertEqual(first["raw_response_sha256"], second["raw_response_sha256"])
        self.assertEqual(first["integrity"]["sha256"], second["integrity"]["sha256"])
        reordered = json.loads(json.dumps(payload(), sort_keys=True))
        self.assertEqual(first["raw_response_sha256"], result(reordered)["raw_response_sha256"])
        changed = payload()
        changed["Results"]["series"][0]["data"][0]["value"] = "159001"
        self.assertNotEqual(first["raw_response_sha256"], result(changed)["raw_response_sha256"])
        sensitive = payload()
        sensitive["api_key"] = "must-not-be-hashed"
        sensitive["endpoint"] = "https://example.invalid/never-called"
        self.assertEqual(first["raw_response_sha256"], result(sensitive)["raw_response_sha256"])
        tampered = copy.deepcopy(first)
        tampered["metrics"]["unemployment_rate"]["value"] = "9.9"
        self.assertFalse(nfp.integrity_matches(tampered))
        with self.assertRaises(ValueError):
            nfp.stable_sha({"value": float("nan")})

    def test_malformed_and_provider_errors_are_explicit(self):
        for malformed in (None, [], {}, {"Results": {}}, {"Results": {"series": {}}}):
            with self.subTest(malformed=repr(malformed)):
                self.assertEqual(result(malformed)["status"], "NFP_BLS_INVALID_RESPONSE")
        provider_error = payload()
        provider_error["status"] = "REQUEST_FAILED"
        self.assertEqual(result(provider_error)["status"], "NFP_BLS_PROVIDER_ERROR")
        provider_message = payload()
        provider_message["status"] = "REQUEST_SUCCEEDED"
        provider_message["message"] = ["provider warning"]
        self.assertEqual(result(provider_message)["status"], "NFP_BLS_PROVIDER_ERROR")

    def test_fixture_cli_uses_tempfile_only_and_malformed_json_is_safe(self):
        before = protected_snapshot()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_path = root / "fixture.json"
            result_path = root / "result.json"
            fixture_path.write_text("{not valid json", encoding="utf-8")
            exit_code = nfp.main([
                "--reference-period", "2026-06",
                "--fixture-json", str(fixture_path),
                "--result-json", str(result_path),
            ])
            written = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "NFP_BLS_INVALID_RESPONSE")
        self.assertFalse(written["external_api_called"])
        self.assertEqual(protected_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
