from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.automation import run_ppi_historical_backfill as backfill
from scripts.pipelines import build_ppi_historical_canonical as canonical


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def response() -> dict:
    values = {"WPSFD4": {"2026-05": "101", "2026-04": "100", "2025-05": "95"}, "WPUFD4": {"2026-05": "106", "2026-04": "103", "2025-05": "100"}, "WPSFD49116": {"2026-05": "100.5", "2026-04": "100", "2025-05": "95"}, "WPUFD49116": {"2026-05": "105", "2026-04": "102", "2025-05": "100"}}
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": key, "data": [{"year": period[:4], "period": "M" + period[5:], "value": value} for period, value in rows.items()]} for key, rows in values.items()]}}


class PpiBackfillTests(unittest.TestCase):
    def execute(self, output: Path, payload=None, event="US_PPI_2026_05", period="2026-05", release="2026-06-11T12:30:00Z"):
        return backfill.run_backfill(ROOT, event, period, release, output, use_live_bls=False, now=NOW, response_fetcher=lambda: payload or response())

    def test_full_preview_and_index_are_created_without_production_changes(self):
        with tempfile.TemporaryDirectory(prefix="ppi-backfill-") as temporary:
            output = Path(temporary) / "preview"
            before = backfill.protected_hashes(ROOT)
            result = self.execute(output)
            event = output / "US_PPI_2026_05"
            self.assertEqual(result.status, "PPI_BACKFILL_REHEARSAL_COMPLETED")
            self.assertTrue(all((event / name).is_file() for name in ("historical_observation.json", "canonical.json", "analysis.json", "report.html", "index.html", "result.json")))
            self.assertIn("US_PPI_2026_05", (event / "index.html").read_text(encoding="utf-8"))
            report = (event / "report.html").read_text(encoding="utf-8")
            for display in ("1.0%", "6.0%", "0.5%", "5.0%"):
                self.assertIn(display, report)
            self.assertEqual(result.missing_local_links, ())
            backfill.ensure_protected(before)

    def test_same_input_is_idempotent_and_different_input_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="ppi-backfill-") as temporary:
            output = Path(temporary) / "preview"
            self.assertEqual(self.execute(output).status, "PPI_BACKFILL_REHEARSAL_COMPLETED")
            self.assertEqual(self.execute(output).status, "PPI_BACKFILL_ALREADY_COMPLETE")
            changed = response(); changed["Results"]["series"][0]["data"][0]["value"] = "103"
            self.assertEqual(self.execute(output, changed).status, "PPI_BACKFILL_CONFLICT")

    def test_request_and_output_protections_block_unsafe_inputs(self):
        with tempfile.TemporaryDirectory(prefix="ppi-backfill-") as temporary:
            base = Path(temporary)
            with self.assertRaises(backfill.PpiBackfillError):
                self.execute(base / "preview", event="US_PPI_2026_06")
            with self.assertRaises(backfill.PpiBackfillError):
                self.execute(base / "preview", release="2027-01-01T00:00:00Z")
            with self.assertRaises(backfill.PpiBackfillError):
                self.execute(ROOT / "preview")
            with self.assertRaises(backfill.PpiBackfillError):
                self.execute(base / "preview" / ".." / "other")

    def test_symlink_output_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="ppi-backfill-link-") as temporary:
            base = Path(temporary); target = base / "target"; target.mkdir(); link = base / "link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:
                link.mkdir()
                with patch.object(Path, "is_symlink", lambda path: path == link):
                    with self.assertRaises(backfill.PpiBackfillError):
                        self.execute(link)
            else:
                with self.assertRaises(backfill.PpiBackfillError):
                    self.execute(link)

    def test_fixture_mode_never_calls_live_bls(self):
        with tempfile.TemporaryDirectory(prefix="ppi-backfill-") as temporary:
            with patch.object(backfill.bls_ppi, "post_bls_payload") as post:
                result = self.execute(Path(temporary) / "preview")
            post.assert_not_called()
            self.assertFalse(result.data_api_called)
