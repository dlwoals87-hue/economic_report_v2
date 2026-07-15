"""Capture an immutable CPI component snapshot after a headline CPI release.

The default entry point deliberately has no network transport.  Production callers
must explicitly supply the BLS fetcher, while tests supply deterministic fixtures.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from scripts.collectors import bls_cpi_components as components


ROOT = Path(__file__).resolve().parents[2]
BLS_UNREGISTERED_MAX_SERIES = 25


class CaptureError(ValueError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CaptureError("INVALID_INPUT")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError("INVALID_INPUT") from exc
    if not isinstance(value, dict):
        raise CaptureError("INVALID_INPUT")
    return value


def _may_use_exclusive_create_fallback(exc: OSError) -> bool:
    unsupported = {errno.EXDEV, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
    # Windows ERROR_INVALID_FUNCTION and ERROR_NOT_SUPPORTED for unsupported links.
    return exc.errno in unsupported or getattr(exc, "winerror", None) in {1, 50}


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    """Create once without overwriting or following a pre-existing link."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    parent_check = path.parent
    while parent_check != parent_check.parent:
        if parent_check.exists() and parent_check.is_symlink():
            raise CaptureError("OUTPUT_SYMLINK_REJECTED")
        parent_check = parent_check.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(payload)
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except OSError as exc:
            if not _may_use_exclusive_create_fallback(exc):
                raise
            # `xb` is still exclusive: a concurrent writer wins without replacement.
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
    finally:
        temp.unlink(missing_ok=True)


def request_batches(registry: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    requested = components.requested_series(registry)
    return tuple(
        requested[index : index + BLS_UNREGISTERED_MAX_SERIES]
        for index in range(0, len(requested), BLS_UNREGISTERED_MAX_SERIES)
    )


def _event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    found = [
        event
        for event in calendar.get("events", [])
        if isinstance(event, dict) and event.get("event_id") == event_id
    ]
    if len(found) != 1 or found[0].get("indicator_type") != "CPI":
        raise CaptureError("INVALID_INPUT")
    return found[0]


def _within_component_capture_window(event: dict[str, Any], now: datetime) -> bool:
    value = event.get("release_datetime_utc")
    if not isinstance(value, str):
        raise CaptureError("INVALID_INPUT")
    try:
        release = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise CaptureError("INVALID_INPUT") from exc
    return release <= now <= release + timedelta(hours=24)


def _headline_release_matches(path: Path, event: dict[str, Any]) -> bool:
    try:
        release = _read(path)
    except CaptureError:
        return False
    return (
        release.get("event_id") == event["event_id"]
        and release.get("indicator_type") == "CPI"
        and release.get("reference_period") == event["reference_period"]
        and release.get("capture_status") == "captured"
    )


def _merged_response(responses: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for response in responses:
        if not isinstance(response, dict):
            raise components.ComponentError("INVALID_INPUT", "BLS response must be an object")
        results = response.get("Results")
        series = results.get("series") if isinstance(results, dict) else None
        if response.get("status") != "REQUEST_SUCCEEDED" or not isinstance(series, list):
            raise components.ComponentError("INVALID_INPUT", "BLS response status invalid")
        rows.extend(series)
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": rows}}


def _fetch_batch(
    fetcher: Callable[[tuple[str, ...]], Any], batch: tuple[str, ...]
) -> tuple[dict[str, Any], dict[str, Any]]:
    fetched = fetcher(batch)
    if isinstance(fetched, tuple) and len(fetched) == 2:
        response, metadata = fetched
        if not isinstance(metadata, dict):
            raise components.ComponentError("INVALID_INPUT", "fetch metadata must be an object")
    else:
        response, metadata = fetched, {}
    if not isinstance(response, dict):
        raise components.ComponentError("INVALID_INPUT", "BLS response must be an object")
    return response, metadata


def _same_snapshot(existing: Path, proposed: dict[str, Any]) -> bool:
    return not existing.is_symlink() and existing.is_file() and _read(existing) == proposed


def run(
    event_id: str,
    *,
    root: Path = ROOT,
    registry_path: Path | None = None,
    events_path: Path | None = None,
    fetcher: Callable[[tuple[str, ...]], Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Capture only components; never creates, modifies, or rolls back headline CPI."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = root.resolve()
    registry = _read(registry_path or root / "config" / "bls_cpi_component_series.json")
    event = _event(_read(events_path or root / "data" / "calendar" / "events.json"), event_id)
    release_path = root / "data" / "releases" / "cpi" / event_id / "as_released.json"
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event_id,
        "reference_period": event["reference_period"],
        "headline_release_found": _headline_release_matches(release_path, event),
        "component_captured": False,
        "api_called": False,
        "request_count": 0,
        "raw_snapshot_path": None,
        "immutable_component_path": None,
        "canonical_component_status": "unavailable",
        "report_rebuild_status": "not_requested",
        "external_ai_api_called": False,
        "commit_paths": [],
        "error_code": None,
        "retryable": False,
        "message": None,
    }
    if not result["headline_release_found"]:
        result.update(
            status="COMPONENT_DATA_NOT_AVAILABLE_YET",
            retryable=True,
            message="headline release missing or invalid",
        )
        return result
    if not _within_component_capture_window(event, now):
        result.update(
            status="COMPONENT_DATA_NOT_AVAILABLE_YET",
            retryable=False,
            message="outside component capture window",
        )
        return result
    if fetcher is None:
        result.update(
            status="COMPONENT_DATA_NOT_AVAILABLE_YET",
            retryable=True,
            message="live fetcher not supplied",
        )
        return result

    batches = request_batches(registry)
    try:
        fetched_batches = [_fetch_batch(fetcher, batch) for batch in batches]
        raw_responses = [item[0] for item in fetched_batches]
        request_metadata = [item[1] for item in fetched_batches]
        parsed = components.parse_component_response(_merged_response(raw_responses), registry)
        metrics = components.build_component_metrics(parsed, registry, event["reference_period"])
    except components.ComponentError as exc:
        result.update(status=exc.code, error_code=exc.code, retryable=True, message=exc.message)
        return result

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    raw_path = root / "data" / "raw" / "bls" / "cpi_components" / event["reference_period"] / f"retrieved_{stamp}.json"
    release_snapshot_path = root / "data" / "releases" / "cpi" / event_id / "components_as_released.json"
    registry_sha = _sha_bytes(json.dumps(registry, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    request_count = sum(int(item.get("request_count", 1)) for item in request_metadata)
    request_mode = "fixture" if not request_metadata or all(not item for item in request_metadata) else "live"
    registration_key_used = any(item.get("registration_key_used") is True for item in request_metadata)
    raw_payload = {
        "schema_version": "cpi-component-raw-v1",
        "retrieved_at_utc": _iso(now),
        "provider": "U.S. Bureau of Labor Statistics",
        "api_version": "v2",
        "request_mode": request_mode,
        "registration_key_used": registration_key_used,
        "request_count": request_count,
        "requested_series": list(components.requested_series(registry)),
        "batches": [list(batch) for batch in batches],
        "batch_request_provenance": [
            {
                "request_count": int(item.get("request_count", 1)),
                "request_mode": item.get("request_mode", "fixture"),
                "registration_key_used": item.get("registration_key_used") is True,
                "registration_key_rejected": item.get("registration_key_rejected") is True,
                "fallback_used": item.get("fallback_used") is True,
            }
            for item in request_metadata
        ],
        "responses": raw_responses,
        "registry_version": registry["registry_version"],
        "registry_sha256": registry_sha,
        "test_fixture": request_mode == "fixture",
        "not_real_market_data": request_mode == "fixture",
    }
    raw_bytes = _json_bytes(raw_payload)
    snapshot = {
        "schema_version": "cpi-component-release-v1",
        "event_id": event_id,
        "indicator_type": "CPI",
        "reference_period": event["reference_period"],
        "release_datetime_utc": event["release_datetime_utc"],
        "retrieved_at_utc": _iso(now),
        "provider": "U.S. Bureau of Labor Statistics",
        "registry_version": registry["registry_version"],
        "registry_sha256": registry_sha,
        "raw_snapshot_path": raw_path.relative_to(root).as_posix(),
        "raw_snapshot_sha256": _sha_bytes(raw_bytes),
        "components": metrics["components"],
        "completeness": "COMPLETE",
        "validation": {
            "status": "COMPONENT_SNAPSHOT_READY",
            "test_fixture": request_mode == "fixture",
            "not_real_market_data": request_mode == "fixture",
        },
        "contribution_status": metrics["contribution_status"],
        "integrity": {"immutable": True, "sha256": None},
    }
    snapshot["integrity"]["sha256"] = components._sha(snapshot)

    if release_snapshot_path.exists() or release_snapshot_path.is_symlink():
        if _same_snapshot(release_snapshot_path, snapshot):
            result.update(status="COMPONENT_ALREADY_CAPTURED")
        else:
            result.update(status="COMPONENT_IMMUTABLE_CONFLICT", error_code="COMPONENT_IMMUTABLE_CONFLICT")
        return result
    try:
        _write_new(raw_path, raw_payload)
        _write_new(release_snapshot_path, snapshot)
    except FileExistsError:
        # Do not remove an unexpected file and never attempt a replacement.
        if _same_snapshot(release_snapshot_path, snapshot):
            result.update(status="COMPONENT_ALREADY_CAPTURED")
        else:
            result.update(status="COMPONENT_IMMUTABLE_CONFLICT", error_code="COMPONENT_IMMUTABLE_CONFLICT")
        return result
    except (CaptureError, OSError) as exc:
        result.update(
            status="COMPONENT_OUTPUT_ERROR",
            error_code="COMPONENT_OUTPUT_ERROR",
            retryable=True,
            message=str(exc),
        )
        return result

    paths = [raw_path.relative_to(root).as_posix(), release_snapshot_path.relative_to(root).as_posix()]
    result.update(
        status="COMPONENTS_CAPTURED",
        component_captured=True,
        api_called=request_mode == "live",
        request_count=request_count,
        raw_snapshot_path=paths[0],
        immutable_component_path=paths[1],
        canonical_component_status="not_rebuilt",
        commit_paths=paths,
    )
    return result
