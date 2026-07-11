from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation import run_cpi_historical_backfill as backfill


ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = "US_CPI_2026_05"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def event() -> dict[str, object]:
    return {
        "event_id": EVENT_ID,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": "2026-05",
        "release_datetime_utc": "2026-06-10T12:30:00Z",
        "metrics": {key: {"expected": None, "unit": "%"} for key in backfill.CPI_METRICS},
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def response(period="2026-05", omit=None) -> dict[str, object]:
    values = {
        "CUSR0000SA0": [("2026", "M05", "320"), ("2026", "M04", "319"), ("2026", "M03", "318"), ("2025", "M05", "310"), ("2025", "M04", "309"), ("2025", "M03", "308")],
        "CUUR0000SA0": [("2026", "M05", "330"), ("2026", "M04", "328"), ("2026", "M03", "326"), ("2025", "M05", "320"), ("2025", "M04", "318"), ("2025", "M03", "316")],
        "CUSR0000SA0L1E": [("2026", "M05", "250"), ("2026", "M04", "249"), ("2026", "M03", "248"), ("2025", "M05", "244"), ("2025", "M04", "243"), ("2025", "M03", "242")],
        "CUUR0000SA0L1E": [("2026", "M05", "260"), ("2026", "M04", "258"), ("2026", "M03", "257"), ("2025", "M05", "252"), ("2025", "M04", "250"), ("2025", "M03", "249")],
    }
    series = []
    for series_id, rows in values.items():
        data = [{"year": year, "period": month, "value": value} for year, month, value in rows]
        if period != "2026-05":
            data = [item for item in data if not (item["year"] == "2026" and item["period"] == "M05")]
            data.append({"year": "2026", "period": "M06", "value": "321"})
        if series_id == omit:
            continue
        series.append({"seriesID": series_id, "data": data})
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}


class HistoricalBackfillTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory(prefix="historical-backfill-") as temp:
            base = Path(temp)
            root = base / "project"
            out = base / "preview"
            self.write_inputs(root, [event()])
            return callback(root, out)

    def write_inputs(self, root: Path, events: list[dict[str, object]]) -> None:
        path = root / "data/calendar/events.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "events": events}, indent=2) + "\n", encoding="utf-8")
        profile = root / "data/indicator_profiles.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(json.dumps({"CPI": {"display_name": "US Consumer Price Index", "country": "US"}}), encoding="utf-8")
        docs = root / "docs"
        shutil.copytree(ROOT / "docs", docs, dirs_exist_ok=True)

    def execute(self, root: Path, out: Path, payload=None):
        return backfill.run_backfill(root, EVENT_ID, out, use_live_bls=False, now=NOW, response_fetcher=lambda _now: payload or response())

    def output(self, out: Path, name: str) -> Path:
        return out / EVENT_ID / name

    def test_01_historical_event_runs(self):
        self.run_in_temp(lambda root, out: self.assertEqual(self.execute(root, out).status, "BACKFILL_REHEARSAL_COMPLETED"))

    def test_02_missing_event_is_blocked(self):
        def case(root, out):
            self.write_inputs(root, [])
            with self.assertRaises(backfill.BackfillError) as raised:
                self.execute(root, out)
            self.assertEqual(raised.exception.code, "BACKFILL_EVENT_NOT_FOUND")
        self.run_in_temp(case)

    def test_03_duplicate_event_is_blocked(self):
        def case(root, out):
            self.write_inputs(root, [event(), event()])
            with self.assertRaises(backfill.BackfillError): self.execute(root, out)
        self.run_in_temp(case)

    def test_04_future_event_is_blocked(self):
        def case(root, out):
            payload = event(); payload["release_datetime_utc"] = "2026-08-10T12:30:00Z"; self.write_inputs(root, [payload])
            with self.assertRaises(backfill.BackfillError): self.execute(root, out)
        self.run_in_temp(case)

    def test_05_non_cpi_event_is_blocked(self):
        def case(root, out):
            payload = event(); payload["indicator_type"] = "PPI"; self.write_inputs(root, [payload])
            with self.assertRaises(backfill.BackfillError): self.execute(root, out)
        self.run_in_temp(case)

    def test_06_target_reference_period_is_used(self):
        self.run_in_temp(lambda root, out: (self.execute(root, out), self.assertEqual(json.loads(self.output(out, "historical_observation.json").read_text())["reference_period"], "2026-05")))

    def test_07_stale_month_is_blocked(self):
        def case(root, out):
            with self.assertRaises(backfill.BackfillError) as raised: self.execute(root, out, response("2026-06"))
            self.assertEqual(raised.exception.code, "BACKFILL_DATA_NOT_AVAILABLE")
        self.run_in_temp(case)

    def test_08_partial_series_is_blocked(self):
        def case(root, out):
            with self.assertRaises(backfill.BackfillError) as raised: self.execute(root, out, response(omit="CUUR0000SA0L1E"))
            self.assertEqual(raised.exception.code, "BACKFILL_PARTIAL_DATA")
        self.run_in_temp(case)

    def test_09_observation_has_historical_provenance(self):
        def case(root, out):
            self.execute(root, out); provenance = json.loads(self.output(out, "historical_observation.json").read_text())["provenance"]
            self.assertEqual(provenance["data_origin"], "historical_backfill"); self.assertEqual(provenance["vintage_status"], "current_api_snapshot"); self.assertTrue(provenance["not_as_released"])
        self.run_in_temp(case)

    def test_10_observation_separates_retrieval_and_release_times(self):
        def case(root, out):
            self.execute(root, out); data = json.loads(self.output(out, "historical_observation.json").read_text())
            self.assertNotEqual(data["retrieved_at_utc"], data["original_release_datetime_utc"])
        self.run_in_temp(case)

    def test_11_observation_integrity_hash_is_valid(self):
        def case(root, out):
            self.execute(root, out); data = json.loads(self.output(out, "historical_observation.json").read_text())
            self.assertEqual(data["integrity"]["sha256"], backfill.stable_sha256(data))
        self.run_in_temp(case)

    def test_12_historical_outputs_do_not_use_release_capture_terms(self):
        def case(root, out):
            self.execute(root, out)
            text = "".join(self.output(out, name).read_text(encoding="utf-8") for name in ("historical_observation.json", "canonical.json", "analysis.json", "report.html"))
            self.assertNotIn("actual_as_released", text); self.assertNotIn("release_capture", text)
        self.run_in_temp(case)

    def test_13_canonical_preserves_historical_provenance(self):
        def case(root, out):
            self.execute(root, out); canonical = json.loads(self.output(out, "canonical.json").read_text())
            self.assertEqual(canonical["meta"]["data_origin"], "historical_backfill"); self.assertTrue(canonical["source"]["not_as_released"])
        self.run_in_temp(case)

    def test_14_missing_snapshot_leaves_expected_and_surprise_null(self):
        def case(root, out):
            self.execute(root, out); metric = json.loads(self.output(out, "canonical.json").read_text())["event"]["headline"]["mom"]
            self.assertIsNone(metric["expected"]); self.assertIsNone(metric["surprise"])
        self.run_in_temp(case)

    def test_15_rule_based_analysis_is_free_and_has_no_ai_api(self):
        def case(root, out):
            self.execute(root, out); analysis = json.loads(self.output(out, "analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["provider"]["name"], "rule_based"); self.assertTrue(analysis["backfill"]["data_api_called"]); self.assertFalse(analysis["backfill"]["ai_api_called"]); self.assertEqual(analysis["backfill"]["cost"], "free")
        self.run_in_temp(case)

    def test_16_report_has_visible_historical_notice_and_preserves_style(self):
        def case(root, out):
            self.execute(root, out); report = self.output(out, "report.html").read_text(encoding="utf-8")
            self.assertIn("Historical CPI backfill rehearsal", report); self.assertIn("current BLS API historical snapshot", report); self.assertIn("<style", report); self.assertNotIn("<script", report)
        self.run_in_temp(case)

    def test_17_copied_index_registers_one_report_and_keeps_sample_link(self):
        def case(root, out):
            self.execute(root, out); index = self.output(out, "index.html").read_text(encoding="utf-8")
            self.assertIn("sample-report.html", index); self.assertEqual(index.count('data-event-id="US_CPI_2026_05"'), 1)
        self.run_in_temp(case)

    def test_18_index_marker_outside_content_is_preserved(self):
        def case(root, out):
            before = (root / "docs/index.html").read_text(encoding="utf-8"); self.execute(root, out); after = self.output(out, "index.html").read_text(encoding="utf-8")
            start = "<!-- AUTO_REAL_REPORTS_START -->"; end = "<!-- AUTO_REAL_REPORTS_END -->"
            if start in before: self.assertEqual(before.split(start)[0], after.split(start)[0])
        self.run_in_temp(case)

    def test_19_identical_rerun_is_idempotent(self):
        def case(root, out):
            first = self.execute(root, out); before = {name: self.output(out, name).read_bytes() for name in ("historical_observation.json", "canonical.json", "analysis.json", "report.html", "index.html")}
            second = backfill.run_backfill(root, EVENT_ID, out, use_live_bls=True, now=NOW)
            self.assertEqual(first.status, "BACKFILL_REHEARSAL_COMPLETED"); self.assertEqual(second.status, "BACKFILL_ALREADY_COMPLETE"); self.assertEqual(before, {name: self.output(out, name).read_bytes() for name in before})
        self.run_in_temp(case)

    def test_20_different_mocked_input_conflicts(self):
        def case(root, out):
            self.execute(root, out); changed = response(); changed["Results"]["series"][0]["data"][0]["value"] = "321"
            self.assertEqual(self.execute(root, out, changed).status, "BACKFILL_CONFLICT")
        self.run_in_temp(case)

    def test_21_project_internal_output_is_rejected(self):
        self.run_in_temp(lambda root, out: self.assertRaises(backfill.BackfillError, backfill.run_backfill, root, EVENT_ID, root / "inside", use_live_bls=False, now=NOW, response_fetcher=lambda _now: response()))

    def test_22_parent_output_path_is_rejected(self):
        self.run_in_temp(lambda root, out: self.assertRaises(backfill.BackfillError, backfill.output_root_path, root, Path("..") / "outside"))

    def test_23_symlink_output_is_rejected(self):
        def case(root, out):
            try: out.symlink_to(root, target_is_directory=True)
            except OSError: self.skipTest("symlinks unavailable")
            with self.assertRaises(backfill.BackfillError): self.execute(root, out)
        self.run_in_temp(case)

    def test_24_production_files_are_unchanged(self):
        files = ["data/calendar/events.json", "templates/sample_report_v11.html", "templates/report.html", "docs/index.html", ".github/workflows/capture-cpi-release.yml", ".github/workflows/process-cpi-release.yml", "scripts/pipelines/capture_cpi_release.py", "scripts/automation/run_due_cpi_capture.py"]
        before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
        self.run_in_temp(lambda root, out: self.execute(root, out))
        self.assertEqual(before, {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files})

    def test_25_no_production_release_output_is_created(self):
        self.run_in_temp(lambda root, out: self.execute(root, out))
        self.assertFalse((ROOT / "data/releases/cpi/US_CPI_2026_05/as_released.json").exists())

    def test_26_mocked_tests_do_not_call_live_fetcher(self):
        self.run_in_temp(lambda root, out: self.execute(root, out))

    def test_27_outputs_have_no_secrets_or_absolute_project_path(self):
        def case(root, out):
            self.execute(root, out); text = "".join(path.read_text(encoding="utf-8") for path in (out / EVENT_ID).iterdir() if path.is_file())
            self.assertNotIn("BLS_API_KEY", text); self.assertNotIn(str(root), text)
        self.run_in_temp(case)

    def test_28_sample_html_links_are_copied_into_preview(self):
        def case(root, out):
            self.execute(root, out)
            self.assertTrue((out / EVENT_ID / "reports/sample-report.html").is_file())
            self.assertTrue((out / EVENT_ID / "reports/sample-cpi-report.html").is_file())
        self.run_in_temp(case)

    def test_29_sample_copy_sha_matches_docs_source(self):
        def case(root, out):
            self.execute(root, out)
            source = root / "docs/reports/sample-report.html"
            copied = out / EVENT_ID / "reports/sample-report.html"
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(copied.read_bytes()).hexdigest())
        self.run_in_temp(case)

    def test_30_all_preview_local_html_links_resolve(self):
        def case(root, out):
            self.execute(root, out)
            preview = out / EVENT_ID
            links = backfill.referenced_paths((preview / "index.html").read_text(encoding="utf-8"))
            self.assertTrue(all((preview / link).is_file() for link in links if link.suffix == ".html"))
        self.run_in_temp(case)

    def test_31_external_and_anchor_links_are_ignored(self):
        self.assertIsNone(backfill.local_reference("https://example.com/report.html"))
        self.assertIsNone(backfill.local_reference("#section"))
        self.assertIsNone(backfill.local_reference("javascript:void(0)"))

    def test_32_unsafe_links_are_rejected(self):
        for href in ("../outside.html", "file:///C:/outside.html", "C:/outside.html"):
            with self.assertRaises(backfill.BackfillError):
                backfill.local_reference(href)

    def test_33_repair_preserves_backfill_report_bytes(self):
        def case(root, out):
            self.execute(root, out)
            preview = out / EVENT_ID
            before = (preview / "report.html").read_bytes()
            (preview / "reports/sample-report.html").unlink()
            result = backfill.run_backfill(root, EVENT_ID, out, use_live_bls=False, now=NOW)
            self.assertEqual(result.status, "BACKFILL_PREVIEW_LINKS_REPAIRED")
            self.assertEqual(before, (preview / "report.html").read_bytes())
        self.run_in_temp(case)

    def test_34_repair_rerun_is_idempotent(self):
        def case(root, out):
            self.execute(root, out)
            preview = out / EVENT_ID
            (preview / "reports/sample-report.html").unlink()
            backfill.run_backfill(root, EVENT_ID, out, use_live_bls=False, now=NOW)
            result = backfill.run_backfill(root, EVENT_ID, out, use_live_bls=False, now=NOW)
            self.assertEqual(result.status, "BACKFILL_ALREADY_COMPLETE")
            self.assertTrue(result.preview_links_valid)
            self.assertEqual(result.missing_local_links, ())
        self.run_in_temp(case)

    def test_35_docs_sources_are_unchanged_by_preview_copy(self):
        source = ROOT / "docs/reports/sample-report.html"
        before = source.read_bytes()
        self.run_in_temp(lambda root, out: self.execute(root, out))
        self.assertEqual(before, source.read_bytes())


if __name__ == "__main__":
    unittest.main()
