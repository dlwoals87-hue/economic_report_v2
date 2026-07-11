from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.automation import lock_cpi_consensus
from scripts.diagnostics import check_cpi_release_readiness as readiness


ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = "US_CPI_2026_06"
COPIED_FILES = (
    *readiness.REQUIRED_FILES,
    "templates/sample_report_v11.html",
    ".github/workflows/capture-cpi-release.yml",
    ".github/workflows/process-cpi-release.yml",
)


class CpiReleaseReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.offline = readiness.run_offline_dry_run()

    def temporary_project(self) -> tempfile.TemporaryDirectory[str]:
        temp = tempfile.TemporaryDirectory(prefix="cpi-readiness-test-")
        root = Path(temp.name)
        for relative in COPIED_FILES:
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return temp

    def result_for(self, root: Path) -> readiness.ReadinessResult:
        return readiness.check_readiness(root, EVENT_ID)

    def replace(self, path: Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def write_locked_snapshot(self, root: Path) -> None:
        calendar = json.loads((root / "data/calendar/events.json").read_text(encoding="utf-8"))
        event = next(item for item in calendar["events"] if item["event_id"] == EVENT_ID)
        snapshot_event = dict(event)
        snapshot_event["consensus_source"] = "Trusted survey"
        snapshot_event["consensus_status"] = "complete"
        snapshot_event["entered_at_utc"] = "2026-07-14T11:00:00Z"
        values = {"headline_mom": "0.3", "headline_yoy": "2.9", "core_mom": "0.2", "core_yoy": "3.1"}
        snapshot = lock_cpi_consensus.build_snapshot(
            snapshot_event,
            {key: lock_cpi_consensus.parse_expected(value, key) for key, value in values.items()},
            lock_cpi_consensus.parse_utc("2026-07-14T12:00:00Z", "locked_at_utc"),
        )
        path = root / "data/consensus/cpi" / EVENT_ID / "consensus_snapshot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    def test_01_normal_project_passes(self) -> None:
        with self.temporary_project() as temp:
            self.assertEqual(self.result_for(Path(temp)).status, "READINESS_PASS")

    def test_02_event_must_exist(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / "data/calendar/events.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["events"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn("exactly once", " ".join(self.result_for(Path(temp)).errors))

    def test_03_event_must_not_be_duplicated(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / "data/calendar/events.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            event = next(item for item in payload["events"] if item["event_id"] == EVENT_ID)
            payload["events"].append(event)
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn("exactly once", " ".join(self.result_for(Path(temp)).errors))

    def test_04_release_time_must_be_timezone_aware(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / "data/calendar/events.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            event = next(item for item in payload["events"] if item["event_id"] == EVENT_ID)
            event["release_datetime_utc"] = "2026-07-14T12:30:00"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn("timezone-aware", " ".join(self.result_for(Path(temp)).errors))

    def test_05_capture_workflow_is_required(self) -> None:
        with self.temporary_project() as temp:
            (Path(temp) / ".github/workflows/capture-cpi-release.yml").unlink()
            self.assertEqual(self.result_for(Path(temp)).status, "READINESS_FAIL")

    def test_06_process_workflow_is_required(self) -> None:
        with self.temporary_project() as temp:
            (Path(temp) / ".github/workflows/process-cpi-release.yml").unlink()
            self.assertEqual(self.result_for(Path(temp)).status, "READINESS_FAIL")

    def test_07_capture_workflow_name_is_checked(self) -> None:
        with self.temporary_project() as temp:
            self.replace(Path(temp) / ".github/workflows/capture-cpi-release.yml", "name: Capture CPI Release", "name: Broken")
            self.assertIn("capture workflow missing", " ".join(self.result_for(Path(temp)).errors))

    def test_08_process_workflow_trigger_is_checked(self) -> None:
        with self.temporary_project() as temp:
            self.replace(Path(temp) / ".github/workflows/process-cpi-release.yml", '"Capture CPI Release"', '"Other workflow"')
            self.assertIn("process workflow missing", " ".join(self.result_for(Path(temp)).errors))

    def test_09_rule_based_default_is_checked(self) -> None:
        with self.temporary_project() as temp:
            self.replace(Path(temp) / "scripts/automation/process_cpi_release.py", 'DEFAULT_PROVIDER = "rule_based"', 'DEFAULT_PROVIDER = "openai"')
            self.assertIn("rule_based", " ".join(self.result_for(Path(temp)).errors))

    def test_10_process_workflow_rejects_secrets(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / ".github/workflows/process-cpi-release.yml"
            path.write_text(path.read_text(encoding="utf-8") + "\n      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n", encoding="utf-8")
            self.assertIn("forbidden", " ".join(self.result_for(Path(temp)).errors))

    def test_11_capture_workflow_rejects_git_add_dot(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / ".github/workflows/capture-cpi-release.yml"
            path.write_text(path.read_text(encoding="utf-8") + "\n      git add .\n", encoding="utf-8")
            self.assertIn("git add .", " ".join(self.result_for(Path(temp)).errors))

    def test_12_process_workflow_rejects_force_push(self) -> None:
        with self.temporary_project() as temp:
            path = Path(temp) / ".github/workflows/process-cpi-release.yml"
            path.write_text(path.read_text(encoding="utf-8") + "\n      git push --force\n", encoding="utf-8")
            self.assertIn("--force", " ".join(self.result_for(Path(temp)).errors))

    def test_13_required_template_is_checked(self) -> None:
        with self.temporary_project() as temp:
            (Path(temp) / "templates/report.html").unlink()
            self.assertIn("required file missing", " ".join(self.result_for(Path(temp)).errors))

    def test_14_offline_waiting_has_no_api_call(self) -> None:
        self.assertTrue(self.offline["waiting"])

    def test_15_offline_stale_data_is_not_captured(self) -> None:
        self.assertTrue(self.offline["stale"])

    def test_16_offline_capture_is_immutable(self) -> None:
        self.assertTrue(self.offline["capture"])

    def test_17_offline_processing_creates_all_outputs(self) -> None:
        self.assertTrue(self.offline["processing"])
        self.assertTrue(self.offline["canonical"])
        self.assertTrue(self.offline["analysis"])
        self.assertTrue(self.offline["report"])
        self.assertTrue(self.offline["index"])

    def test_18_offline_rerun_is_idempotent(self) -> None:
        self.assertTrue(self.offline["rerun"])

    def test_19_offline_tampering_is_blocked(self) -> None:
        self.assertTrue(self.offline["tamper_release"])
        self.assertTrue(self.offline["tamper_canonical"])
        self.assertTrue(self.offline["tamper_report"])

    def test_20_diagnostic_does_not_modify_production_files(self) -> None:
        before = readiness._snapshot(ROOT)
        result = readiness.check_readiness(ROOT, EVENT_ID)
        self.assertEqual(result.status, "READINESS_PASS")
        self.assertEqual(before, readiness._snapshot(ROOT))

    def test_21_normal_project_uses_free_mode(self) -> None:
        with self.temporary_project() as temp:
            self.assertTrue(self.result_for(Path(temp)).free_mode)

    def test_22_normal_project_requires_no_external_api(self) -> None:
        with self.temporary_project() as temp:
            self.assertFalse(self.result_for(Path(temp)).external_api_required)

    def test_23_locked_consensus_is_reported(self) -> None:
        with self.temporary_project() as temp:
            root = Path(temp)
            self.write_locked_snapshot(root)
            result = self.result_for(root)
            self.assertEqual(result.status, "READINESS_PASS")
            self.assertEqual(result.consensus, "locked")
            self.assertIsNone(result.consensus_warning)

    def test_24_not_ready_consensus_has_warning(self) -> None:
        with self.temporary_project() as temp:
            result = self.result_for(Path(temp))
            self.assertEqual(result.consensus, "not_ready")
            self.assertEqual(result.consensus_warning, "Actual-versus-expected comparison will be unavailable.")

    def test_25_missing_consensus_does_not_fail_readiness(self) -> None:
        with self.temporary_project() as temp:
            self.assertEqual(self.result_for(Path(temp)).status, "READINESS_PASS")

    def test_26_missing_consensus_reports_comparison_warning(self) -> None:
        with self.temporary_project() as temp:
            self.assertIn("comparison will be unavailable", self.result_for(Path(temp)).consensus_warning or "")


if __name__ == "__main__":
    unittest.main()
