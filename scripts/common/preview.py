from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class PreviewSafetyError(ValueError):
    """Raised for an unsafe preview path or local preview reference."""


class ImmutableWriteConflict(FileExistsError):
    """Raised when an immutable destination already exists."""


def stable_json_sha256(payload: dict[str, Any], *, exclude_integrity_sha: bool = True) -> str:
    value = copy.deepcopy(payload)
    if exclude_integrity_sha and isinstance(value.get("integrity"), dict):
        value["integrity"].pop("sha256", None)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_immutable_bytes(path: Path, data: bytes) -> None:
    if path.exists():
        raise ImmutableWriteConflict(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ImmutableWriteConflict(str(path)) from exc
        except OSError:
            if path.exists():
                raise ImmutableWriteConflict(str(path))
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def external_preview_root(project_root: Path, requested: Path) -> Path:
    if not requested.is_absolute() or ".." in requested.parts:
        raise PreviewSafetyError("output root must be an absolute path without parent traversal")
    resolved = requested.resolve(strict=False)
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        pass
    else:
        raise PreviewSafetyError("output root must be outside the project")
    for candidate in (requested, *requested.parents):
        if candidate.exists() and candidate.is_symlink():
            raise PreviewSafetyError("output root cannot use symlinks")
    return resolved


def local_preview_reference(value: str, *, blocked_top_levels: set[str] | None = None) -> Path | None:
    href = value.split("#", 1)[0].split("?", 1)[0]
    if not href or value.startswith("#") or href.lower().startswith(("javascript:", "http:", "https:", "mailto:")):
        return None
    if href.lower().startswith("file:"):
        raise PreviewSafetyError("file URL is not allowed")
    path = Path(href)
    blocked = blocked_top_levels or set()
    if path.is_absolute() or ":" in path.drive or ".." in path.parts or any(part.startswith(".") or part in blocked for part in path.parts):
        raise PreviewSafetyError("unsafe local preview reference")
    return path


def copy_preview_asset(source_root: Path, destination_root: Path, relative: Path) -> bool:
    source = source_root / relative
    destination = destination_root / relative
    if not source.is_file() or source.is_symlink():
        raise PreviewSafetyError("source preview asset is missing or unsafe")
    if destination.exists():
        if destination.is_symlink() or file_sha256(source) != file_sha256(destination):
            raise ImmutableWriteConflict(str(destination))
        return False
    write_immutable_bytes(destination, source.read_bytes())
    return True


def validate_historical_provenance(provenance: dict[str, Any], retrieved_at_utc: Any, observation_sha256: Any) -> None:
    if not isinstance(provenance, dict):
        raise PreviewSafetyError("historical provenance must be an object")
    required = {"data_origin", "vintage_status", "not_as_released"}
    if not required.issubset(provenance) or not isinstance(retrieved_at_utc, str) or not retrieved_at_utc or not isinstance(observation_sha256, str) or len(observation_sha256) != 64:
        raise PreviewSafetyError("historical provenance fields are incomplete")
