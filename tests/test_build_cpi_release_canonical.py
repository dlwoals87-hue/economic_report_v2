from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


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
    write_json(root / "data" / "calendar" / "events.json", {"version": 1, "events": [event or calendar_event()]})
    write_json(
        root / "data" / "indicator_profiles.json",
        {"CPI": {"display_name": "US Consumer Price Index", "country": "US"}},
    )


def write_release(root: Path, payload=None, event_id=EVENT_ID):
    path = root / "data" / "releases" / "cpi" / event_id / "as_released.json"
    write_json(path, payload or release_payload(event_id=event_id))
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
            write_base_inputs(
                root,
                calendar_event(
                    expected_values={
                        "headline_mom": "0.1",
                        "headline_yoy": "3.1",
                        "core_mom": "0.2",
                        "core_yoy": None,
                    }
                ),
            )
            write_release(root)
            self.build(root)
            surprise = read_canonical(root)["event"]["headline"]["mom"]["surprise"]
            self.assertEqual(surprise["raw"], "0.2")
            self.assertEqual(surprise["display"], "0.2%p")
        self.run_in_temp(case)

    def test_above_expected_direction(self):
        def case(root):
            write_base_inputs(root, calendar_event(expected_values={
                "headline_mom": "0.1",
                "headline_yoy": None,
                "core_mom": None,
                "core_yoy": None,
            }))
            write_release(root)
            self.build(root)
            self.assertEqual(
                read_canonical(root)["event"]["headline"]["mom"]["surprise"]["direction"],
                "above_expected",
            )
        self.run_in_temp(case)

    def test_below_expected_direction(self):
        def case(root):
            write_base_inputs(root, calendar_event(expected_values={
                "headline_mom": None,
                "headline_yoy": "3.1",
                "core_mom": None,
                "core_yoy": None,
            }))
            write_release(root)
            self.build(root)
            self.assertEqual(
                read_canonical(root)["event"]["headline"]["yoy"]["surprise"]["direction"],
                "below_expected",
            )
        self.run_in_temp(case)

    def test_in_line_direction(self):
        def case(root):
            write_base_inputs(root, calendar_event(expected_values={
                "headline_mom": None,
                "headline_yoy": None,
                "core_mom": "0.2",
                "core_yoy": None,
            }))
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


if __name__ == "__main__":
    unittest.main()
