from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.automation import lock_cpi_consensus


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pipelines" / "build_cpi_release_canonical.py"
SPEC = importlib.util.spec_from_file_location("build_cpi_release_canonical", MODULE_PATH)
build_cpi_release_canonical = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["build_cpi_release_canonical"] = build_cpi_release_canonical
SPEC.loader.exec_module(build_cpi_release_canonical)


EVENT_ID = "US_CPI_2026_06"
REFERENCE_PERIOD = "2026-06"


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metric(actual_raw, actual_display, previous_raw, previous_display):
    return {
        "actual_as_released_raw": actual_raw,
        "actual_as_released_display": actual_display,
        "previous_as_released_raw": previous_raw,
        "previous_as_released_display": previous_display,
        "actual_current_raw": "9.9",
        "actual_current_display": "9.9%",
        "unit": "%",
    }


def calendar_event(expected_values=None, event_id=EVENT_ID, reference_period=REFERENCE_PERIOD):
    expected_values = expected_values or {
        "headline_mom": None,
        "headline_yoy": None,
        "core_mom": None,
        "core_yoy": None,
    }
    return {
        "event_id": event_id,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "metrics": {
            key: {
                "expected": value,
                "unit": "%",
            }
            for key, value in expected_values.items()
        },
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def release_payload(event_id=EVENT_ID, reference_period=REFERENCE_PERIOD):
    payload = {
        "schema_version": "1.0",
        "event_id": event_id,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "captured_at_utc": "2026-07-14T12:31:00Z",
        "capture_status": "captured",
        "release_vintage": "first_observed_after_release",
        "metrics": {
            "headline_mom": metric("0.3", "0.3%", "0.5", "0.5%"),
            "headline_yoy": metric("2.9", "2.9%", "3.0", "3.0%"),
            "core_mom": metric("0.2", "0.2%", "0.3", "0.3%"),
            "core_yoy": metric("3.1", "3.1%", "3.2", "3.2%"),
        },
        "source": {
            "provider": "U.S. Bureau of Labor Statistics",
            "raw_snapshot_path": "data/raw/bls/cpi/2026-06/retrieved_20260714T123100Z.json",
            "request_mode": "unregistered_fallback",
            "retrieved_at_utc": "2026-07-14T12:31:00Z",
        },
        "integrity": {
            "immutable": True,
            "sha256": None,
        },
    }
    payload["integrity"]["sha256"] = build_cpi_release_canonical.stable_sha256(payload)
    return payload


def write_base_inputs(root: Path, event=None):
    event_payload = event or calendar_event()
    write_json(root / "data" / "calendar" / "events.json", {"version": 1, "events": [event_payload]})
    write_json(
        root / "data" / "indicator_profiles.json",
        {"CPI": {"display_name": "US Consumer Price Index", "country": "US"}},
    )
    if event_payload.get("consensus_status") == "complete":
        values = {
            key: str(event_payload["metrics"][key]["expected"])
            for key in lock_cpi_consensus.CPI_METRICS
        }
        write_consensus_snapshot(root, values, event_payload)


def write_release(root: Path, payload=None, event_id=EVENT_ID):
    path = root / "data" / "releases" / "cpi" / event_id / "as_released.json"
    write_json(path, payload or release_payload(event_id=event_id))
    return path


def write_consensus_snapshot(root: Path, values: dict[str, str], event_payload=None, path_event_id=None):
    payload = event_payload or calendar_event()
    snapshot_event = dict(payload)
    snapshot_event["consensus_source"] = "Trusted survey"
    snapshot_event["consensus_status"] = "complete"
    snapshot_event["entered_at_utc"] = "2026-07-14T11:00:00Z"
    parsed = {key: lock_cpi_consensus.parse_expected(value, key) for key, value in values.items()}
    snapshot = lock_cpi_consensus.build_snapshot(
        snapshot_event,
        parsed,
        lock_cpi_consensus.parse_utc("2026-07-14T12:00:00Z", "locked_at_utc"),
    )
    path = root / "data" / "consensus" / "cpi" / (path_event_id or payload["event_id"]) / "consensus_snapshot.json"
    write_json(path, snapshot)
    return path


def default_output(root: Path, event_id=EVENT_ID) -> Path:
    return root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"


def read_canonical(root: Path, event_id=EVENT_ID):
    return json.loads(default_output(root, event_id).read_text(encoding="utf-8"))


class BuildCpiReleaseCanonicalTests(unittest.TestCase):
    def run_in_temp(self, callback):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_base_inputs(root)
            return callback(root)

    def build(self, root: Path, event_id=EVENT_ID, output=None):
        return build_cpi_release_canonical.build_from_files(root, event_id, output=output)

    def test_missing_as_released_returns_release_not_captured(self):
        def case(root):
            result = self.build(root)
            self.assertEqual(result.status, "RELEASE_NOT_CAPTURED")
            self.assertFalse(result.as_released_exists)
        self.run_in_temp(case)

    def test_missing_as_released_creates_no_output(self):
        def case(root):
            self.build(root)
            self.assertFalse(default_output(root).exists())
        self.run_in_temp(case)

    def test_event_id_mismatch_fails(self):
        def case(root):
            write_release(root, release_payload(event_id="US_CPI_2099_01"), event_id=EVENT_ID)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_reference_period_mismatch_fails(self):
        def case(root):
            write_release(root, release_payload(reference_period="2099-01"))
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_indicator_type_mismatch_fails(self):
        def case(root):
            payload = release_payload()
            payload["indicator_type"] = "PPI"
            payload["integrity"]["sha256"] = build_cpi_release_canonical.stable_sha256(payload)
            write_release(root, payload)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_integrity_immutable_false_fails(self):
        def case(root):
            payload = release_payload()
            payload["integrity"]["immutable"] = False
            payload["integrity"]["sha256"] = build_cpi_release_canonical.stable_sha256(payload)
            write_release(root, payload)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_sha256_mismatch_fails(self):
        def case(root):
            payload = release_payload()
            payload["integrity"]["sha256"] = "not-the-real-sha"
            write_release(root, payload)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_missing_one_metric_fails(self):
        def case(root):
            payload = release_payload()
            del payload["metrics"]["core_yoy"]
            payload["integrity"]["sha256"] = build_cpi_release_canonical.stable_sha256(payload)
            write_release(root, payload)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_actual_as_released_maps_to_canonical(self):
        def case(root):
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertEqual(canonical["event"]["headline"]["mom"]["actual_as_released_raw"], "0.3")
            self.assertEqual(canonical["event"]["core"]["yoy"]["actual_as_released_display"], "3.1%")
        self.run_in_temp(case)

    def test_previous_as_released_maps_to_canonical(self):
        def case(root):
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertEqual(canonical["event"]["headline"]["mom"]["previous_as_released_raw"], "0.5")
            self.assertEqual(canonical["event"]["core"]["yoy"]["previous_as_released_display"], "3.2%")
        self.run_in_temp(case)

    def test_actual_current_is_not_used_as_canonical_value(self):
        def case(root):
            write_release(root)
            self.build(root)
            text = default_output(root).read_text(encoding="utf-8")
            canonical = read_canonical(root)
            self.assertEqual(canonical["event"]["headline"]["mom"]["actual_as_released_raw"], "0.3")
            self.assertNotIn("actual_current", text)
            self.assertNotIn("9.9", text)
        self.run_in_temp(case)

    def test_expected_null_makes_surprise_null(self):
        def case(root):
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertIsNone(canonical["event"]["headline"]["mom"]["expected"])
            self.assertIsNone(canonical["event"]["headline"]["mom"]["surprise"])
        self.run_in_temp(case)

    def test_numeric_expected_calculates_surprise(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "3.1", "core_mom": "0.2", "core_yoy": "3.1"})
            write_release(root)
            self.build(root)
            surprise = read_canonical(root)["event"]["headline"]["mom"]["surprise"]
            self.assertEqual(surprise["raw"], "0.2")
            self.assertEqual(surprise["display"], "0.2%p")
        self.run_in_temp(case)

    def test_above_expected_direction(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            write_release(root)
            self.build(root)
            self.assertEqual(
                read_canonical(root)["event"]["headline"]["mom"]["surprise"]["direction"],
                "above_expected",
            )
        self.run_in_temp(case)

    def test_below_expected_direction(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.3", "headline_yoy": "3.1", "core_mom": "0.2", "core_yoy": "3.1"})
            write_release(root)
            self.build(root)
            self.assertEqual(
                read_canonical(root)["event"]["headline"]["yoy"]["surprise"]["direction"],
                "below_expected",
            )
        self.run_in_temp(case)

    def test_in_line_direction(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.3", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            write_release(root)
            self.build(root)
            self.assertEqual(
                read_canonical(root)["event"]["core"]["mom"]["surprise"]["direction"],
                "in_line",
            )
        self.run_in_temp(case)

    def test_release_utc_converts_to_asia_seoul(self):
        def case(root):
            write_release(root)
            self.build(root)
            meta = read_canonical(root)["meta"]
            self.assertEqual(meta["release_datetime_utc"], "2026-07-14T12:30:00Z")
            self.assertEqual(meta["release_datetime_kst"], "2026-07-14T21:30:00+09:00")
        self.run_in_temp(case)

    def test_is_sample_false(self):
        def case(root):
            write_release(root)
            self.build(root)
            self.assertFalse(read_canonical(root)["meta"]["is_sample"])
        self.run_in_temp(case)

    def test_data_origin_bls_release_capture(self):
        def case(root):
            write_release(root)
            self.build(root)
            self.assertEqual(read_canonical(root)["meta"]["data_origin"], "bls_release_capture")
        self.run_in_temp(case)

    def test_analysis_pending(self):
        def case(root):
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertEqual(canonical["meta"]["analysis_status"], "pending")
            self.assertEqual(canonical["analysis"]["status"], "pending")
            self.assertIsNone(canonical["analysis"]["provider"])
            self.assertIsNone(canonical["analysis"]["model"])
        self.run_in_temp(case)

    def test_sample_ai_text_is_not_included(self):
        def case(root):
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            serialized = json.dumps(canonical, ensure_ascii=False)
            self.assertIsNone(canonical["analysis"]["summary_html"])
            self.assertEqual(canonical["analysis"]["key_points"], [])
            self.assertNotIn("sample analysis", serialized.lower())
            self.assertNotIn("market interpretation", serialized.lower())
        self.run_in_temp(case)

    def test_output_path_parent_directory_is_rejected(self):
        def case(root):
            write_release(root)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root, output="../canonical_release.json")
        self.run_in_temp(case)

    def test_absolute_output_outside_project_is_rejected(self):
        def case(root):
            write_release(root)
            outside = Path(tempfile.gettempdir()) / "canonical_release.json"
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root, output=str(outside))
        self.run_in_temp(case)

    def test_same_result_second_run_is_already_up_to_date(self):
        def case(root):
            write_release(root)
            first = self.build(root)
            before = default_output(root).read_text(encoding="utf-8")
            second = self.build(root)
            self.assertEqual(first.status, "CANONICAL_CREATED")
            self.assertEqual(second.status, "ALREADY_UP_TO_DATE")
            self.assertEqual(before, default_output(root).read_text(encoding="utf-8"))
        self.run_in_temp(case)

    def test_existing_different_output_refuses_overwrite(self):
        def case(root):
            write_release(root)
            output = default_output(root)
            write_json(output, {"schema_version": "different"})
            before = output.read_text(encoding="utf-8")
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
            self.assertEqual(before, output.read_text(encoding="utf-8"))
        self.run_in_temp(case)

    def test_api_key_string_is_not_written_to_output(self):
        def case(root):
            old_key = os.environ.get("BLS_API_KEY")
            os.environ["BLS_API_KEY"] = "SECRET_TEST_KEY"
            try:
                write_release(root)
                self.build(root)
                self.assertNotIn("SECRET_TEST_KEY", default_output(root).read_text(encoding="utf-8"))
            finally:
                if old_key is None:
                    os.environ.pop("BLS_API_KEY", None)
                else:
                    os.environ["BLS_API_KEY"] = old_key
        self.run_in_temp(case)

    def test_fixture_is_not_written_to_project_data_releases(self):
        event_id = "US_CPI_TEST_FIXTURE"

        def case(root):
            write_base_inputs(root, calendar_event(event_id=event_id))
            write_release(root, release_payload(event_id=event_id), event_id=event_id)
            self.build(root, event_id=event_id)
            self.assertFalse((ROOT / "data" / "releases" / "cpi" / event_id).exists())
        self.run_in_temp(case)

    def test_locked_snapshot_expected_values_are_mapped(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.8", "core_mom": "0.2", "core_yoy": "3.0"})
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertEqual(canonical["event"]["headline"]["mom"]["expected"], "0.1")
            self.assertEqual(canonical["event"]["core"]["yoy"]["expected"], "3")
            self.assertEqual(canonical["event"]["consensus"]["status"], "locked")
        self.run_in_temp(case)

    def test_locked_snapshot_calculates_surprise(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            write_release(root)
            self.build(root)
            self.assertEqual(read_canonical(root)["event"]["headline"]["mom"]["surprise"]["raw"], "0.2")
        self.run_in_temp(case)

    def test_missing_snapshot_keeps_expected_null(self):
        def case(root):
            write_release(root)
            self.build(root)
            self.assertIsNone(read_canonical(root)["event"]["headline"]["mom"]["expected"])
        self.run_in_temp(case)

    def test_mutable_calendar_expected_is_ignored_without_snapshot(self):
        def case(root):
            write_base_inputs(root, calendar_event(expected_values={
                "headline_mom": "9.9", "headline_yoy": "9.9", "core_mom": "9.9", "core_yoy": "9.9",
            }))
            write_release(root)
            self.build(root)
            metric = read_canonical(root)["event"]["headline"]["mom"]
            self.assertIsNone(metric["expected"])
            self.assertIsNone(metric["surprise"])
        self.run_in_temp(case)

    def test_snapshot_sha_mismatch_blocks_canonical(self):
        def case(root):
            path = write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["integrity"]["sha256"] = "0" * 64
            write_json(path, payload)
            write_release(root)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
            self.assertFalse(default_output(root).exists())
        self.run_in_temp(case)

    def test_snapshot_event_id_mismatch_blocks_canonical(self):
        def case(root):
            bad_event = calendar_event(event_id="US_CPI_2099_01")
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"}, bad_event, path_event_id=EVENT_ID)
            write_release(root)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_snapshot_reference_period_mismatch_blocks_canonical(self):
        def case(root):
            bad_event = calendar_event(reference_period="2099-01")
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"}, bad_event, path_event_id=EVENT_ID)
            write_release(root)
            with self.assertRaises(build_cpi_release_canonical.ReleaseCanonicalError):
                self.build(root)
        self.run_in_temp(case)

    def test_snapshot_path_and_hash_are_recorded(self):
        def case(root):
            path = write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            write_release(root)
            self.build(root)
            canonical = read_canonical(root)
            self.assertEqual(canonical["source"]["consensus_snapshot_path"], "data/consensus/cpi/US_CPI_2026_06/consensus_snapshot.json")
            self.assertEqual(canonical["source"]["consensus_snapshot_sha256"], snapshot["integrity"]["sha256"])
        self.run_in_temp(case)

    def test_snapshot_validation_does_not_modify_as_released(self):
        def case(root):
            write_consensus_snapshot(root, {"headline_mom": "0.1", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"})
            release_path = write_release(root)
            before = release_path.read_bytes()
            self.build(root)
            self.assertEqual(before, release_path.read_bytes())
        self.run_in_temp(case)


if __name__ == "__main__":
    unittest.main()
