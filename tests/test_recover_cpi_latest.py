from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.collectors import bls_cpi
from scripts.recovery import recover_cpi_latest as recovery


EVENT_ID = "US_CPI_2026_06"
REFERENCE_PERIOD = "2026-06"
RAW_PATH = "data/raw/bls/cpi/2026-06/retrieved_20260714T140853Z.json"
OUTPUT_PATH = "data/processed/bls/cpi_latest.json"


def response() -> dict:
    periods = {
        "CUSR0000SA0": {"2026-06": "101", "2026-05": "100", "2026-04": "99", "2025-06": "98", "2025-05": "97"},
        "CUUR0000SA0": {"2026-06": "104", "2026-05": "103", "2025-06": "100", "2025-05": "99"},
        "CUSR0000SA0L1E": {"2026-06": "102", "2026-05": "100", "2026-04": "99", "2025-06": "98", "2025-05": "97"},
        "CUUR0000SA0L1E": {"2026-06": "105", "2026-05": "104", "2025-06": "100", "2025-05": "99"},
    }
    return {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": series_id,
                    "data": [
                        {"year": period[:4], "period": f"M{period[-2:]}", "value": value, "footnotes": [{}]}
                        for period, value in values.items()
                    ],
                }
                for series_id, values in periods.items()
            ]
        },
    }


class RecoverCpiLatestTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        raw = root / RAW_PATH
        raw.parent.mkdir(parents=True)
        raw_payload = {
            "retrieved_at_utc": "2026-07-14T14:08:53.379992Z",
            "provider": "U.S. Bureau of Labor Statistics",
            "api_version": "v2",
            "request_mode": "unregistered",
            "registration_key_used": False,
            "response": response(),
        }
        raw.write_text(json.dumps(raw_payload), encoding="utf-8")
        (root / "data/calendar").mkdir(parents=True)
        calendar = {
            "events": [{
                "event_id": EVENT_ID, "indicator_type": "CPI", "country": "US",
                "reference_period": REFERENCE_PERIOD,
            }]
        }
        (root / "data/calendar/events.json").write_text(json.dumps(calendar), encoding="utf-8")
        self.write_release(root)
        return temporary, root

    def candidate(self, root: Path) -> dict:
        raw = json.loads((root / RAW_PATH).read_text(encoding="utf-8"))
        parsed, validation = bls_cpi.parse_bls_response(raw["response"])
        metrics = bls_cpi.build_metrics(parsed, REFERENCE_PERIOD)
        return bls_cpi.build_processed_payload(
            REFERENCE_PERIOD,
            recovery._parse_utc(raw["retrieved_at_utc"]),
            metrics,
            validation,
            root / RAW_PATH,
            root,
            raw["request_mode"],
            raw["registration_key_used"],
        )

    def write_release(self, root: Path) -> None:
        candidate = self.candidate_without_release(root)
        release = {
            "event_id": EVENT_ID,
            "reference_period": REFERENCE_PERIOD,
            "capture_status": "captured",
            "integrity": {"immutable": True},
            "source": {
                "raw_snapshot_path": RAW_PATH,
                "retrieved_at_utc": candidate["retrieved_at_utc"],
                "request_mode": "unregistered",
            },
            "metrics": {
                name: {
                    "actual_as_released_raw": metric["actual_current_raw"],
                    "actual_as_released_display": metric["actual_current_display"],
                    "previous_as_released_raw": metric["previous_current_raw"],
                    "previous_as_released_display": metric["previous_current_display"],
                }
                for name, metric in candidate["metrics"].items()
            },
        }
        path = root / f"data/releases/cpi/{EVENT_ID}/as_released.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(release), encoding="utf-8")

    def candidate_without_release(self, root: Path) -> dict:
        raw = json.loads((root / RAW_PATH).read_text(encoding="utf-8"))
        parsed, validation = bls_cpi.parse_bls_response(raw["response"])
        return bls_cpi.build_processed_payload(
            REFERENCE_PERIOD,
            recovery._parse_utc(raw["retrieved_at_utc"]),
            bls_cpi.build_metrics(parsed, REFERENCE_PERIOD),
            validation,
            root / RAW_PATH,
            root,
            raw["request_mode"],
            raw["registration_key_used"],
        )

    def recover(self, root: Path, **kwargs):
        return recovery.recover(root, event_id=EVENT_ID, raw_snapshot=RAW_PATH, **kwargs)

    def test_dry_run_is_ready_and_never_calls_network_or_collector_save(self):
        temporary, root = self.make_root()
        with temporary, mock.patch.object(bls_cpi, "collect_and_save", side_effect=AssertionError("network collector")), mock.patch.object(bls_cpi, "post_bls_payload", side_effect=AssertionError("network")):
            result = self.recover(root)
        self.assertEqual(result.status, "RECOVERY_READY")
        self.assertFalse(result.applied); self.assertFalse(result.network_called)
        self.assertEqual(result.commit_paths, [])
        self.assertFalse((root / OUTPUT_PATH).exists())

    def test_apply_creates_the_exact_collector_payload(self):
        temporary, root = self.make_root()
        with temporary:
            result = self.recover(root, apply=True)
            self.assertEqual(result.status, "RECOVERED")
            self.assertEqual(result.commit_paths, [OUTPUT_PATH])
            self.assertEqual(json.loads((root / OUTPUT_PATH).read_text(encoding="utf-8")), self.candidate(root))

    def test_identical_existing_output_is_a_no_op(self):
        temporary, root = self.make_root()
        with temporary:
            output = root / OUTPUT_PATH; output.parent.mkdir(parents=True); output.write_bytes(recovery._candidate_bytes(self.candidate(root)))
            before = output.read_bytes(); result = self.recover(root, apply=True)
            self.assertEqual(result.status, "ALREADY_UP_TO_DATE")
            self.assertFalse(result.applied); self.assertEqual(output.read_bytes(), before)

    def test_different_existing_output_is_a_conflict_without_overwrite(self):
        temporary, root = self.make_root()
        with temporary:
            output = root / OUTPUT_PATH; output.parent.mkdir(parents=True); output.write_text('{"different": true}\n', encoding="utf-8")
            before = output.read_bytes(); result = self.recover(root, apply=True)
            self.assertEqual(result.status, "RECOVERY_CONFLICT")
            self.assertEqual(output.read_bytes(), before); self.assertEqual(result.commit_paths, [])

    def test_release_metadata_mismatches_are_blocked(self):
        for field, value in (("event_id", "US_CPI_2026_05"), ("reference_period", "2026-05"), ("capture_status", "pending")):
            with self.subTest(field=field):
                temporary, root = self.make_root()
                with temporary:
                    path = root / f"data/releases/cpi/{EVENT_ID}/as_released.json"; release = json.loads(path.read_text(encoding="utf-8")); release[field] = value; path.write_text(json.dumps(release), encoding="utf-8")
                    self.assertEqual(self.recover(root).status, "RECOVERY_INTEGRITY_MISMATCH")
                    self.assertFalse((root / OUTPUT_PATH).exists())

    def test_release_source_and_metric_mismatches_are_blocked(self):
        cases = (
            ("source.raw_snapshot_path", "data/raw/bls/cpi/2026-06/retrieved_other.json"),
            ("source.retrieved_at_utc", "2026-07-14T14:08:54Z"),
            ("source.request_mode", "registered"),
            ("metrics.headline_mom.actual_as_released_raw", "999"),
            ("metrics.headline_mom.actual_as_released_display", "999.0%"),
            ("metrics.headline_mom.previous_as_released_raw", "999"),
            ("metrics.headline_mom.previous_as_released_display", "999.0%"),
        )
        for dotted, value in cases:
            with self.subTest(dotted=dotted):
                temporary, root = self.make_root()
                with temporary:
                    path = root / f"data/releases/cpi/{EVENT_ID}/as_released.json"; release = json.loads(path.read_text(encoding="utf-8"))
                    target = release
                    for key in dotted.split(".")[:-1]: target = target[key]
                    target[dotted.split(".")[-1]] = value
                    path.write_text(json.dumps(release), encoding="utf-8")
                    self.assertEqual(self.recover(root).status, "RECOVERY_INTEGRITY_MISMATCH")

    def test_raw_series_validation_and_malformed_json_are_blocked(self):
        for mutation in ("missing", "duplicate", "unexpected", "malformed"):
            with self.subTest(mutation=mutation):
                temporary, root = self.make_root()
                with temporary:
                    path = root / RAW_PATH
                    if mutation == "malformed":
                        path.write_text("{", encoding="utf-8")
                    else:
                        raw = json.loads(path.read_text(encoding="utf-8")); series = raw["response"]["Results"]["series"]
                        if mutation == "missing": series.pop()
                        elif mutation == "duplicate": series.append(copy.deepcopy(series[0]))
                        else: series.append({"seriesID": "OTHER", "data": series[0]["data"]})
                        path.write_text(json.dumps(raw), encoding="utf-8")
                    self.assertEqual(self.recover(root).status, "INVALID_INPUT")

    def test_raw_path_and_output_path_contracts_are_blocked(self):
        temporary, root = self.make_root()
        with temporary:
            for raw_path in ("../raw.json", "data\\raw\\bls\\cpi\\2026-06\\retrieved_x.json", "/tmp/raw.json", "data/raw/bls/ppi/2026-06/retrieved_x.json"):
                with self.subTest(raw_path=raw_path):
                    self.assertEqual(recovery.recover(root, event_id=EVENT_ID, raw_snapshot=raw_path).status, "INVALID_INPUT")
            self.assertEqual(self.recover(root, output="data/processed/bls/other.json").status, "INVALID_INPUT")

    def test_raw_credential_like_value_is_blocked(self):
        temporary, root = self.make_root()
        with temporary:
            path = root / RAW_PATH; path.write_bytes(path.read_bytes() + b"\nsk-12345678901234567890")
            self.assertEqual(self.recover(root).status, "INVALID_INPUT")

    def test_raw_symlink_and_output_symlink_are_blocked(self):
        temporary, root = self.make_root()
        with temporary, mock.patch.object(recovery, "_has_symlink_component", return_value=True):
            self.assertEqual(self.recover(root).status, "INVALID_INPUT")

        temporary, root = self.make_root()
        with temporary:
            output = root / OUTPUT_PATH; output.parent.mkdir(parents=True); output.write_text("existing", encoding="utf-8")
            with mock.patch.object(recovery, "_has_symlink_component", side_effect=lambda _root, path: path.name == "cpi_latest.json"):
                self.assertEqual(self.recover(root).status, "INVALID_INPUT")

    def test_exclusive_fallback_writes_and_cleans_temporary_files(self):
        temporary, root = self.make_root()
        with temporary, mock.patch.object(os, "link", side_effect=OSError("hard links unavailable")):
            result = self.recover(root, apply=True)
            self.assertEqual(result.status, "RECOVERED")
            self.assertFalse(list((root / "data/processed/bls").glob(".cpi_latest.json.*.tmp")))

    def test_force_option_is_not_exposed(self):
        parser = recovery.parse_args(["--event-id", EVENT_ID, "--raw-snapshot", RAW_PATH, "--result-json", "tmp/result.json"])
        self.assertFalse(hasattr(parser, "force"))


if __name__ == "__main__":
    unittest.main()
