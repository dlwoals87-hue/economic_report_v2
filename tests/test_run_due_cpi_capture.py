from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "automation" / "run_due_cpi_capture.py"
SPEC = importlib.util.spec_from_file_location("run_due_cpi_capture", MODULE_PATH)
run_due_cpi_capture = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["run_due_cpi_capture"] = run_due_cpi_capture
SPEC.loader.exec_module(run_due_cpi_capture)


@dataclass
class FakeCaptureResult:
    status: str
    event_id: str
    reference_period: str
    api_call_count: int = 0
    as_released_path: str | None = None
    raw_snapshot_path: str | None = None
    processed_path: str | None = None
    request_mode: str | None = None


NOW = datetime(2026, 7, 14, 12, 40, tzinfo=timezone.utc)


def event(event_id: str, reference_period: str, release_datetime_utc: str):
    return {
        "event_id": event_id,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": reference_period,
        "release_datetime_utc": release_datetime_utc,
        "metrics": {},
        "consensus_status": "not_entered",
    }


def write_calendar(root: Path, events):
    path = root / "data" / "calendar" / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"events": events}, indent=2) + "\n", encoding="utf-8")


def create_commit_files(root: Path):
    paths = [
        "data/releases/cpi/US_CPI_2026_06/as_released.json",
        "data/raw/bls/cpi/2026-06/retrieved_20260714T123100Z.json",
        "data/processed/bls/cpi_latest.json",
    ]
    for item in paths:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    return paths


def captured_result(paths):
    return FakeCaptureResult(
        status="CAPTURED",
        event_id="US_CPI_2026_06",
        reference_period="2026-06",
        api_call_count=1,
        as_released_path=paths[0],
        raw_snapshot_path=paths[1],
        processed_path=paths[2],
        request_mode="unregistered",
    )


class RunDueCpiCaptureTests(unittest.TestCase):
    def run_temp(self, callback):
        with tempfile.TemporaryDirectory() as tmp:
            return callback(Path(tmp))

    def test_future_event_only_returns_no_due_event(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T13:00:00Z")])
            result, code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "NO_DUE_EVENT")
        self.run_temp(case)

    def test_future_event_has_zero_bls_calls(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T13:00:00Z")])
            result, _code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )
            self.assertFalse(result["api_called"])
        self.run_temp(case)

    def test_expired_event_is_excluded_from_auto_selection(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_05", "2026-05", "2026-06-10T12:30:00Z")])
            result, _code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )
            self.assertEqual(result["status"], "NO_DUE_EVENT")
        self.run_temp(case)

    def test_already_captured_event_is_excluded(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])
            path = root / "data" / "releases" / "cpi" / "US_CPI_2026_06" / "as_released.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            result, _code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )
            self.assertEqual(result["status"], "NO_DUE_EVENT")
        self.run_temp(case)

    def test_existing_as_released_auto_path_does_not_capture_or_modify_files(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])
            release = root / "data" / "releases" / "cpi" / "US_CPI_2026_06" / "as_released.json"
            release.parent.mkdir(parents=True, exist_ok=True)
            release.write_text('{"already": true}\n', encoding="utf-8")
            before_text = release.read_text(encoding="utf-8")
            before_mtime = release.stat().st_mtime_ns
            raw_root = root / "data" / "raw" / "bls" / "cpi"

            result, code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )

            raw_files = list(raw_root.rglob("*")) if raw_root.exists() else []
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "NO_DUE_EVENT")
            self.assertFalse(result["captured"])
            self.assertFalse(result["api_called"])
            self.assertEqual(result["commit_paths"], [])
            self.assertEqual(release.read_text(encoding="utf-8"), before_text)
            self.assertEqual(release.stat().st_mtime_ns, before_mtime)
            self.assertEqual([path for path in raw_files if path.is_file()], [])
        self.run_temp(case)

    def test_single_due_event_calls_capture_once(self):
        def case(root):
            calls = []
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])

            def fake_capture(_root, event_id, now_utc=None):
                calls.append((event_id, now_utc))
                return FakeCaptureResult("WAITING_FOR_RELEASE", event_id, "2026-06")

            result, _code = run_due_cpi_capture.run_due_capture(root, now_utc=NOW, capture_func=fake_capture)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["event_id"], "US_CPI_2026_06")
        self.run_temp(case)

    def test_two_due_events_returns_multiple_due_events(self):
        def case(root):
            write_calendar(
                root,
                [
                    event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z"),
                    event("US_CPI_2026_07", "2026-07", "2026-07-14T12:35:00Z"),
                ],
            )
            result, code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda *_args, **_kwargs: self.fail("capture should not run"),
            )
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "MULTIPLE_DUE_EVENTS")

        self.run_temp(case)

    def test_auto_selection_uses_event_id_not_reference_period(self):
        def case(root):
            calls = []
            write_calendar(root, [event("CUSTOM_EVENT_ID", "2026-06", "2026-07-14T12:30:00Z")])

            def fake_capture(_root, event_id, now_utc=None):
                calls.append(event_id)
                return FakeCaptureResult("WAITING_FOR_RELEASE", event_id, "2026-06")

            run_due_cpi_capture.run_due_capture(root, now_utc=NOW, capture_func=fake_capture)
            self.assertEqual(calls, ["CUSTOM_EVENT_ID"])
        self.run_temp(case)

    def test_manual_event_id_uses_specified_event(self):
        def case(root):
            calls = []
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T13:00:00Z")])

            def fake_capture(_root, event_id, now_utc=None):
                calls.append(event_id)
                return FakeCaptureResult("WAITING_FOR_RELEASE", event_id, "2026-06")

            result, _code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                event_id="US_CPI_2026_06",
                capture_func=fake_capture,
            )
            self.assertEqual(calls, ["US_CPI_2026_06"])
            self.assertEqual(result["status"], "WAITING_FOR_RELEASE")
        self.run_temp(case)

    def test_waiting_status_writes_result_json(self):
        def case(root):
            result_path = Path(tempfile.gettempdir()) / "cpi_result_waiting.json"
            result = run_due_cpi_capture.empty_result("WAITING_FOR_RELEASE", "waiting")
            run_due_cpi_capture.write_result_json(result_path, result)
            self.assertTrue(result_path.exists())
            self.assertEqual(json.loads(result_path.read_text())["status"], "WAITING_FOR_RELEASE")
            result_path.unlink()
        self.run_temp(case)

    def test_commit_paths_only_when_captured(self):
        def case(root):
            paths = create_commit_files(root)
            cap = captured_result(paths)
            result = run_due_cpi_capture.result_from_capture(cap)
            self.assertEqual(result["commit_paths"], paths)
            no_due = run_due_cpi_capture.empty_result("NO_DUE_EVENT", "none")
            self.assertEqual(no_due["commit_paths"], [])
        self.run_temp(case)

    def test_data_not_available_has_empty_commit_paths(self):
        result = run_due_cpi_capture.result_from_capture(
            FakeCaptureResult("DATA_NOT_AVAILABLE_YET", "US_CPI_2026_06", "2026-06", api_call_count=1)
        )
        self.assertEqual(result["commit_paths"], [])

    def test_commit_paths_are_project_relative(self):
        def case(root):
            paths = create_commit_files(root)
            for item in paths:
                self.assertFalse(Path(item).is_absolute())
                self.assertNotIn("..", Path(item).parts)
        self.run_temp(case)

    def test_dotdot_commit_path_rejected(self):
        def case(root):
            with self.assertRaises(run_due_cpi_capture.AutomationError):
                run_due_cpi_capture.validate_commit_paths(root, ["../secret.txt"])
        self.run_temp(case)

    def test_absolute_commit_path_rejected(self):
        def case(root):
            with self.assertRaises(run_due_cpi_capture.AutomationError):
                run_due_cpi_capture.validate_commit_paths(root, [str(root / "data" / "x.json")])
        self.run_temp(case)

    def test_unallowed_commit_path_rejected(self):
        def case(root):
            path = root / "scripts" / "bad.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("print('bad')", encoding="utf-8")
            with self.assertRaises(run_due_cpi_capture.AutomationError):
                run_due_cpi_capture.validate_commit_paths(root, ["scripts/bad.py"])
        self.run_temp(case)

    def test_mixed_allowed_and_forbidden_commit_paths_rejects_entire_capture(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])
            calls = []

            def fake_capture(_root, event_id, now_utc=None):
                calls.append(event_id)
                release = "data/releases/cpi/US_CPI_2026_06/as_released.json"
                processed = "data/processed/bls/cpi_latest.json"
                forbidden = "docs/index.html"
                for item in (release, processed, forbidden):
                    path = root / item
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}", encoding="utf-8")
                return FakeCaptureResult(
                    "CAPTURED",
                    event_id,
                    "2026-06",
                    api_call_count=1,
                    as_released_path=release,
                    raw_snapshot_path=forbidden,
                    processed_path=processed,
                    request_mode="unregistered",
                )

            with self.assertRaisesRegex(
                run_due_cpi_capture.AutomationError,
                "commit path not allowed: docs/index.html",
            ):
                run_due_cpi_capture.run_due_capture(root, now_utc=NOW, capture_func=fake_capture)
            self.assertEqual(calls, ["US_CPI_2026_06"])
        self.run_temp(case)

    def test_api_key_not_written_to_result_json(self):
        result = run_due_cpi_capture.empty_result("NO_DUE_EVENT", "none")
        text = json.dumps(result)
        self.assertNotIn("SECRET_TEST_KEY", text)

    def test_missing_bls_api_key_environment_is_allowed(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])
            with patch.dict(os.environ, {}, clear=True):
                result, code = run_due_cpi_capture.run_due_capture(
                    root,
                    now_utc=NOW,
                    capture_func=lambda _root, event_id, now_utc=None: FakeCaptureResult(
                        "WAITING_FOR_RELEASE",
                        event_id,
                        "2026-06",
                    ),
                )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "WAITING_FOR_RELEASE")
        self.run_temp(case)

    def test_error_message_redacts_api_key(self):
        self.assertEqual(
            run_due_cpi_capture.sanitize_secret_text("bad SECRET_TEST_KEY", "SECRET_TEST_KEY"),
            "bad [REDACTED]",
        )

    def test_mock_tests_make_no_real_api_call(self):
        def case(root):
            write_calendar(root, [event("US_CPI_2026_06", "2026-06", "2026-07-14T12:30:00Z")])
            result, _code = run_due_cpi_capture.run_due_capture(
                root,
                now_utc=NOW,
                capture_func=lambda _root, event_id, now_utc=None: FakeCaptureResult(
                    "WAITING_FOR_RELEASE",
                    event_id,
                    "2026-06",
                    api_call_count=0,
                ),
            )
            self.assertFalse(result["api_called"])
        self.run_temp(case)


if __name__ == "__main__":
    unittest.main()
