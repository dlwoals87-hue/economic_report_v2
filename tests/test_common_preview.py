from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.common import preview


class CommonPreviewTests(unittest.TestCase):
    def test_stable_json_sha_excludes_integrity_and_preserves_decimal_strings(self):
        first = {"amount": "1.20", "integrity": {"sha256": "old"}}
        second = {"integrity": {"sha256": "new"}, "amount": "1.20"}
        self.assertEqual(preview.stable_json_sha256(first), preview.stable_json_sha256(second))
        self.assertIn(b'"1.20"', preview.json_bytes({"amount": "1.20"}))

    def test_immutable_write_is_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            preview.write_immutable_bytes(path, b"one")
            self.assertEqual(path.read_bytes(), b"one")
            with self.assertRaises(preview.ImmutableWriteConflict):
                preview.write_immutable_bytes(path, b"one")

    def test_external_preview_root_rejects_internal_relative_and_parent_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); root = base / "project"; root.mkdir()
            self.assertEqual(preview.external_preview_root(root, base / "preview"), (base / "preview").resolve())
            for candidate in (root / "preview", Path("preview"), base / "preview" / ".." / "other"):
                with self.assertRaises(preview.PreviewSafetyError):
                    preview.external_preview_root(root, candidate)

    def test_symlink_and_local_reference_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); root = base / "project"; root.mkdir(); link = base / "preview"; link.mkdir()
            with patch.object(Path, "is_symlink", lambda path: path == link):
                with self.assertRaises(preview.PreviewSafetyError):
                    preview.external_preview_root(root, link)
        self.assertEqual(preview.local_preview_reference("reports/sample.html"), Path("reports/sample.html"))
        self.assertIsNone(preview.local_preview_reference("https://example.com"))
        for value in ("../outside.html", "file:///outside.html", "data/x.html"):
            with self.assertRaises(preview.PreviewSafetyError):
                preview.local_preview_reference(value, blocked_top_levels={"data"})

    def test_preview_asset_copy_and_missing_source_are_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "docs"; destination = base / "preview"; asset = source / "reports/sample.html"
            asset.parent.mkdir(parents=True); asset.write_text("sample", encoding="utf-8")
            self.assertTrue(preview.copy_preview_asset(source, destination, Path("reports/sample.html")))
            self.assertFalse(preview.copy_preview_asset(source, destination, Path("reports/sample.html")))
            self.assertEqual(preview.file_sha256(asset), preview.file_sha256(destination / "reports/sample.html"))
            with self.assertRaises(preview.PreviewSafetyError):
                preview.copy_preview_asset(source, destination, Path("missing.html"))

    def test_provenance_requires_common_fields(self):
        provenance = {"data_origin": "historical_backfill", "vintage_status": "current_api_snapshot", "not_as_released": True}
        preview.validate_historical_provenance(provenance, "2026-07-11T00:00:00Z", "a" * 64)
        with self.assertRaises(preview.PreviewSafetyError):
            preview.validate_historical_provenance({}, None, "short")
