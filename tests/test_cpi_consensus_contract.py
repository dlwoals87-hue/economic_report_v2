from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.consensus import cpi_contract as contract


EVENT_ID = "US_CPI_2026_08"
RELEASE = "2026-09-11T12:30:00Z"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def event() -> dict[str, object]:
    return {"event_id": EVENT_ID, "indicator_type": "CPI", "country": "US", "reference_period": "2026-08", "release_datetime_utc": RELEASE, "metrics": {key: {"expected": None, "unit": "%"} for key in contract.CPI_METRICS}, "consensus_source": None, "consensus_status": "not_entered", "entered_at_utc": None}


def observation(*, status="COMPLETE", value="0.2") -> dict[str, object]:
    metrics = {}
    for key in contract.CPI_METRICS:
        raw = None if status == "UNAVAILABLE" else value if status == "COMPLETE" else (value if key == "headline_mom" else None)
        metrics[key] = {"expected_raw": raw, "expected_display": None if raw is None else f"{float(raw):.1f}%", "unit": "%", "provider_metric_label": f"Fixture {key}", "mapping_version": "fixture-v1"}
    payload: dict[str, object] = {"schema_version": contract.OBSERVATION_SCHEMA, "provider_id": "fixture_provider", "provider_name": "Fixture Provider", "retrieved_at_utc": "2026-09-10T12:00:00Z", "observed_at_utc": "2026-09-10T11:59:00Z", "source_url": "https://fixture.example/cpi", "source_reference": "fixture-consensus", "source_document_sha256": "a" * 64, "raw_response_path": "data/consensus/cpi/raw/fixture.json", "raw_response_sha256": "b" * 64, "response_version": "fixture-v1", "event_id": EVENT_ID, "indicator_type": "CPI", "country": "US", "reference_period": "2026-08", "release_datetime_utc": RELEASE, "status": status, "metrics": metrics, "integrity": {"immutable": True, "sha256": None}}
    payload["integrity"]["sha256"] = contract.stable_sha256(payload)  # type: ignore[index]
    return payload


class CpiConsensusContractTests(unittest.TestCase):
    def test_01_complete_observation_validates(self): self.assertEqual(contract.validate_observation(observation(), event()), "COMPLETE")
    def test_02_incomplete_observation_is_preserved(self): self.assertEqual(contract.validate_observation(observation(status="INCOMPLETE"), event()), "INCOMPLETE")
    def test_03_unavailable_observation_is_preserved(self): self.assertEqual(contract.validate_observation(observation(status="UNAVAILABLE"), event()), "UNAVAILABLE")
    def test_04_snapshot_is_immutable(self): self.assertTrue(contract.build_snapshot(observation(), event(), NOW)["integrity"]["immutable"])
    def test_05_snapshot_sha_is_stable(self):
        self.assertEqual(contract.build_snapshot(observation(), event(), NOW)["integrity"]["sha256"], contract.build_snapshot(observation(), event(), NOW)["integrity"]["sha256"])
    def test_06_snapshot_has_exact_four_metrics(self): self.assertEqual(set(contract.build_snapshot(observation(), event(), NOW)["metrics"]), set(contract.CPI_METRICS))
    def test_07_snapshot_rejects_post_release_capture(self):
        with self.assertRaises(contract.CpiConsensusContractError): contract.build_snapshot(observation(), event(), datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc))
    def test_08_observation_rejects_after_release_retrieval(self):
        value = observation(); value["retrieved_at_utc"] = RELEASE; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        self.assertEqual(contract.validate_observation(value, event()), "AFTER_RELEASE")
    def test_09_event_id_mismatch_rejected(self):
        value = observation(); value["event_id"] = "US_CPI_2026_07"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_10_period_mismatch_rejected(self):
        value = observation(); value["reference_period"] = "2026-07"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_11_release_mismatch_rejected(self):
        value = observation(); value["release_datetime_utc"] = "2026-09-12T12:30:00Z"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_12_bad_unit_rejected(self):
        value = observation(); value["metrics"]["headline_mom"]["unit"] = "index"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_13_locale_number_rejected(self):
        value = observation(); value["metrics"]["headline_mom"]["expected_raw"] = "0,2"; value["metrics"]["headline_mom"]["expected_display"] = "0.2%"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_14_nan_rejected(self):
        value = observation(); value["metrics"]["headline_mom"]["expected_raw"] = "NaN"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_15_inf_rejected(self):
        value = observation(); value["metrics"]["headline_mom"]["expected_raw"] = "Infinity"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_16_unknown_field_rejected(self):
        value = observation(); value["actual"] = "0.2"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_17_tamper_rejected(self):
        value = observation(); value["provider_name"] = "Changed"
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_18_credential_in_source_rejected(self):
        value = observation(); value["source_url"] = "https://fixture.example/?api_key=no"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_19_raw_path_traversal_rejected(self):
        value = observation(); value["raw_response_path"] = "data/../secret.json"; value["integrity"]["sha256"] = contract.stable_sha256(value)  # type: ignore[index]
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_observation(value, event())
    def test_20_snapshot_validation_rejects_tamper(self):
        snapshot = contract.build_snapshot(observation(), event(), NOW); snapshot["metrics"]["core_yoy"]["expected_raw"] = "0.3"
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_snapshot(snapshot, event())
    def test_20b_snapshot_rejects_credential_source(self):
        snapshot = contract.build_snapshot(observation(), event(), NOW); snapshot["source"]["url"] = "https://fixture.example/?token=no"; snapshot["integrity"]["sha256"] = contract.stable_sha256(snapshot)
        with self.assertRaises(contract.CpiConsensusContractError): contract.validate_snapshot(snapshot, event())
    def test_21_safe_relative_rejects_outside_root(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            with self.assertRaises(contract.CpiConsensusContractError): contract.safe_relative(Path(temp), Path(other) / "x.json")
    def test_22_read_json_rejects_symlink_or_nonfile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target = root / "target.json"; target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            try: link.symlink_to(target)
            except OSError: self.skipTest("symlinks unavailable")
            with self.assertRaises(contract.CpiConsensusContractError): contract.read_json(link)


if __name__ == "__main__": unittest.main()
