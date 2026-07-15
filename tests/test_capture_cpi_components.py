from __future__ import annotations

import copy
import errno
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.collectors import bls_cpi_components as components
from scripts.pipelines import capture_cpi_components as capture


ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = "US_CPI_2026_06"
NOW = datetime(2026, 7, 14, 12, 35, tzinfo=timezone.utc)


def registry() -> dict:
    return json.loads((ROOT / "config" / "bls_cpi_component_series.json").read_text(encoding="utf-8"))


def response(series_ids: tuple[str, ...], *, delta: int = 0) -> dict:
    rows = []
    for index, series_id in enumerate(series_ids):
        base = 100 + index + delta
        rows.append(
            {
                "seriesID": series_id,
                "data": [
                    {"year": "2026", "period": "M06", "value": str(base + 2)},
                    {"year": "2026", "period": "M05", "value": str(base + 1)},
                    {"year": "2025", "period": "M06", "value": str(base)},
                ],
            }
        )
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": rows}}


class CaptureCpiComponentsTests(unittest.TestCase):
    def make_root(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        (root / "data" / "calendar").mkdir(parents=True)
        (root / "data" / "releases" / "cpi" / EVENT_ID).mkdir(parents=True)
        (root / "config" / "bls_cpi_component_series.json").write_text(
            json.dumps(registry()), encoding="utf-8"
        )
        (root / "data" / "calendar" / "events.json").write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "event_id": EVENT_ID,
                            "indicator_type": "CPI",
                            "reference_period": "2026-06",
                            "release_datetime_utc": "2026-07-14T12:30:00Z",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json").write_text(
            json.dumps(
                {
                    "event_id": EVENT_ID,
                    "indicator_type": "CPI",
                    "reference_period": "2026-06",
                    "capture_status": "captured",
                }
            ),
            encoding="utf-8",
        )

    def test_request_batches_respect_unregistered_limit(self):
        batches = capture.request_batches(registry())
        self.assertEqual([len(batch) for batch in batches], [25, 7])
        self.assertEqual(tuple(item for batch in batches for item in batch), components.requested_series(registry()))

    def test_missing_headline_never_calls_fetcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            (root / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json").unlink()
            fetcher = mock.Mock()
            result = capture.run(EVENT_ID, root=root, fetcher=fetcher, now=NOW)
            self.assertEqual(result["status"], "COMPONENT_DATA_NOT_AVAILABLE_YET")
            self.assertFalse(result["api_called"])
            self.assertEqual(result["commit_paths"], [])
            fetcher.assert_not_called()

    def test_no_fetcher_is_dry_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            result = capture.run(EVENT_ID, root=root, now=NOW)
            self.assertEqual(result["status"], "COMPONENT_DATA_NOT_AVAILABLE_YET")
            self.assertFalse((root / "data" / "raw").exists())
            self.assertFalse((root / "data" / "releases" / "cpi" / EVENT_ID / "components_as_released.json").exists())

    def test_mismatched_headline_release_never_calls_fetcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            headline = root / "data" / "releases" / "cpi" / EVENT_ID / "as_released.json"
            value = json.loads(headline.read_text(encoding="utf-8"))
            value["reference_period"] = "2026-05"
            headline.write_text(json.dumps(value), encoding="utf-8")
            fetcher = mock.Mock()
            result = capture.run(EVENT_ID, root=root, fetcher=fetcher, now=NOW)
            self.assertEqual(result["status"], "COMPONENT_DATA_NOT_AVAILABLE_YET")
            fetcher.assert_not_called()

    def test_outside_release_window_never_calls_fetcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            fetcher = mock.Mock()
            result = capture.run(
                EVENT_ID,
                root=root,
                fetcher=fetcher,
                now=datetime(2026, 7, 15, 12, 31, tzinfo=timezone.utc),
            )
            self.assertEqual(result["status"], "COMPONENT_DATA_NOT_AVAILABLE_YET")
            self.assertIn("outside", result["message"])
            fetcher.assert_not_called()

    def test_fixture_capture_creates_exact_two_allowlisted_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            result = capture.run(EVENT_ID, root=root, fetcher=lambda batch: response(batch), now=NOW)
            self.assertEqual(result["status"], "COMPONENTS_CAPTURED")
            self.assertFalse(result["api_called"])
            self.assertEqual(result["request_count"], 2)
            self.assertEqual(len(result["commit_paths"]), 2)
            self.assertTrue(result["commit_paths"][0].startswith("data/raw/bls/cpi_components/2026-06/retrieved_"))
            self.assertEqual(result["commit_paths"][1], f"data/releases/cpi/{EVENT_ID}/components_as_released.json")
            snapshot = json.loads((root / result["commit_paths"][1]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["completeness"], "COMPLETE")
            self.assertEqual(len(snapshot["components"]), 16)
            self.assertEqual(snapshot["integrity"]["sha256"], components._sha(snapshot))
            raw = json.loads((root / result["commit_paths"][0]).read_text(encoding="utf-8"))
            self.assertEqual(len(raw["batch_request_provenance"]), 2)
            self.assertFalse(raw["registration_key_used"])

    def test_incomplete_batch_does_not_create_component_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)

            def incomplete(batch):
                value = response(batch)
                if len(batch) == 7:
                    value["Results"]["series"].pop()
                return value

            result = capture.run(EVENT_ID, root=root, fetcher=incomplete, now=NOW)
            self.assertEqual(result["status"], "COMPONENT_SERIES_MISSING")
            self.assertEqual(result["commit_paths"], [])
            self.assertFalse((root / "data" / "releases" / "cpi" / EVENT_ID / "components_as_released.json").exists())

    def test_identical_repeat_is_immutable_already_captured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            first = capture.run(EVENT_ID, root=root, fetcher=lambda batch: response(batch), now=NOW)
            second = capture.run(EVENT_ID, root=root, fetcher=lambda batch: response(batch), now=NOW)
            self.assertEqual(first["status"], "COMPONENTS_CAPTURED")
            self.assertEqual(second["status"], "COMPONENT_ALREADY_CAPTURED")

    def test_different_repeat_is_immutable_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            capture.run(EVENT_ID, root=root, fetcher=lambda batch: response(batch), now=NOW)
            result = capture.run(EVENT_ID, root=root, fetcher=lambda batch: response(batch, delta=7), now=NOW)
            self.assertEqual(result["status"], "COMPONENT_IMMUTABLE_CONFLICT")

    def test_hard_link_fallback_is_exclusive_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            with mock.patch.object(capture.os, "link", side_effect=OSError(errno.ENOTSUP, "unsupported")):
                capture._write_new(path, {"value": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
            with self.assertRaises(FileExistsError):
                capture._write_new(path, {"value": 2})

    def test_unsafe_link_error_is_not_hidden_by_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            with mock.patch.object(capture.os, "link", side_effect=OSError(errno.EACCES, "denied")):
                with self.assertRaises(OSError):
                    capture._write_new(path, {"value": 1})
            self.assertFalse(path.exists())

    def test_symlink_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(capture.CaptureError):
                capture._write_new(link / "artifact.json", {"value": 1})


if __name__ == "__main__":
    unittest.main()
