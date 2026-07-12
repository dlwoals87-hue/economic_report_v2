"""Persist one immutable, pre-release PPI consensus observation."""

from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collectors import ppi_consensus  # noqa: E402


PPI_EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
NORMAL_STATUSES = {
    "PPI_CONSENSUS_COLLECTED": "complete",
    "PPI_CONSENSUS_PARTIAL": "partial",
    "PPI_CONSENSUS_UNAVAILABLE": "unavailable",
}
LINK_FALLBACK_ERRNOS = {errno.EXDEV, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
LINK_FALLBACK_WINERRORS = {1, 50}


class ObservationError(Exception):
    pass


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID") from exc
    if parsed.tzinfo is None:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_json(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    return text.encode("utf-8")


def _sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _observation_sha(payload: dict[str, Any]) -> str:
    candidate = copy.deepcopy(payload)
    candidate["integrity"] = {}
    return _sha256(candidate)


def _load_event(events_path: Path, event_id: str) -> dict[str, Any]:
    if not events_path.is_file() or events_path.is_symlink():
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    match = PPI_EVENT_RE.fullmatch(event_id)
    if match is None:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    try:
        calendar = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID") from exc
    matches = [item for item in calendar.get("events", []) if isinstance(item, dict) and item.get("event_id") == event_id]
    if len(matches) != 1:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US" or event.get("reference_period") != f"{match.group(1)}-{match.group(2)}":
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
    parse_utc(event.get("release_datetime_utc"))
    return event


def _safe_output_root(root: Path, output_root: Path) -> bool:
    if ".." in output_root.parts or str(output_root).startswith(("\\\\.\\", "\\\\?\\")):
        return False
    expected = (root / "data" / "consensus" / "ppi").resolve(strict=False)
    try:
        resolved = output_root.resolve(strict=False)
    except OSError:
        return False
    if resolved != expected or any(parent.is_symlink() for parent in (output_root, *output_root.parents) if parent.exists()):
        return False
    protected = ((root / "data" / "calendar").resolve(strict=False), (root / "data" / "releases").resolve(strict=False))
    return not any(resolved == path or resolved.is_relative_to(path) for path in protected)


def _compact_timestamp(retrieved_at_utc: str) -> str:
    return parse_utc(retrieved_at_utc).strftime("%Y%m%dT%H%M%SZ")


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_link_fallback(exc: OSError) -> bool:
    return exc.errno in LINK_FALLBACK_ERRNOS or getattr(exc, "winerror", None) in LINK_FALLBACK_WINERRORS


def _write_exclusive(path: Path, content: bytes) -> None:
    """Link a complete temporary file or use exclusive-create on known NTFS limits."""

    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    created_target = False
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except OSError as exc:
            if not _is_link_fallback(exc):
                raise
            try:
                with path.open("xb") as handle:
                    created_target = True
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if created_target and path.exists() and not path.is_symlink():
                    path.unlink()
                raise
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_existing(path: Path, expected: bytes) -> str:
    if path.is_symlink() or not path.is_file():
        return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR"
    try:
        actual = path.read_bytes()
        payload = json.loads(actual.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR"
    if not isinstance(payload, dict) or payload.get("integrity", {}).get("sha256") != _observation_sha(payload):
        return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR"
    if actual != _stable_json(payload):
        return "PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR"
    return "PPI_CONSENSUS_OBSERVATION_ALREADY_EXISTS" if actual == expected else "PPI_CONSENSUS_OBSERVATION_CONFLICT"


def _base_result(status: str, event_id: str, collector_result: dict[str, Any] | None = None) -> dict[str, Any]:
    collector_result = collector_result or {}
    return {
        "status": status,
        "event_id": event_id,
        "provider": "trading_economics",
        "normalized_status": collector_result.get("normalized_status"),
        "retrieved_at_utc": collector_result.get("retrieved_at_utc"),
        "observation_path": None,
        "observation_created": False,
        "eligible_for_apply": False,
        "missing_metrics": [],
        "observation_sha256": None,
        "raw_payload_sha256": collector_result.get("raw_payload_sha256"),
        "created_paths": [],
        "external_api_called": bool(collector_result.get("external_api_called", False)),
        "external_ai_api_called": False,
        "cost": "free",
        "next_action": "RETRY_CONSENSUS_COLLECTION",
    }


def _observation_payload(event: dict[str, Any], collector_result: dict[str, Any], now: datetime) -> dict[str, Any]:
    normalized = collector_result.get("normalized")
    if not isinstance(normalized, dict) or not isinstance(normalized.get("integrity"), dict):
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    if normalized["integrity"].get("sha256") != _sha256({**normalized, "integrity": {}}):
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    normalized_status = collector_result.get("normalized_status")
    if normalized_status not in {"complete", "partial", "unavailable"} or normalized.get("status") != normalized_status:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    retrieved = parse_utc(normalized.get("retrieved_at_utc"))
    release = parse_utc(event["release_datetime_utc"])
    if retrieved >= release:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    metrics = normalized.get("metrics")
    if not isinstance(metrics, dict) or not set(metrics).issubset(PPI_METRICS):
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    missing = [metric for metric in PPI_METRICS if metric not in metrics]
    if normalized_status == "complete" and missing:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    source_field = collector_result.get("source_field")
    if source_field not in {"Forecast", "ForecastValue"}:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    raw_sha = normalized.get("raw_payload_sha256")
    if not isinstance(raw_sha, str) or len(raw_sha) != 64:
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    warnings = collector_result.get("warnings", [])
    provider_event_ids = collector_result.get("provider_event_ids", {})
    provider_tickers = collector_result.get("provider_tickers", {})
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings) or not isinstance(provider_event_ids, dict) or not isinstance(provider_tickers, dict):
        raise ObservationError("PPI_CONSENSUS_OBSERVATION_INTEGRITY_ERROR")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event["event_id"],
        "provider": "trading_economics",
        "provider_data_type": "market_consensus",
        "reference_period": event["reference_period"],
        "release_datetime_utc": event["release_datetime_utc"],
        "retrieved_at_utc": iso_utc(retrieved),
        "normalized_status": normalized_status,
        "metrics": {metric: metrics[metric] for metric in PPI_METRICS if metric in metrics},
        "missing_metrics": missing,
        "warnings": warnings,
        "provider_event_ids": provider_event_ids,
        "provider_tickers": provider_tickers,
        "source_field": source_field,
        "raw_payload_sha256": raw_sha,
        "normalized_sha256": normalized["integrity"]["sha256"],
        "observation_created_at_utc": iso_utc(now),
        "eligible_for_apply": normalized_status == "complete",
        "immutable": True,
        "provenance": {
            "data_origin": "live_consensus_capture",
            "observation_type": "pre_release_market_consensus",
            "provider": "trading_economics",
            "observed_before_release": True,
            "not_actual_release_data": True,
        },
        "integrity": {"sha256": None},
    }
    payload["integrity"]["sha256"] = _observation_sha(payload)
    return payload


def capture_observation(
    event_id: str,
    *,
    root: Path = PROJECT_ROOT,
    events_path: Path | None = None,
    output_root: Path | None = None,
    now_utc: datetime | None = None,
    collector: Callable[..., dict[str, Any]] = ppi_consensus.collect,
) -> dict[str, Any]:
    root = root.resolve()
    events = events_path or root / "data" / "calendar" / "events.json"
    output = output_root or root / "data" / "consensus" / "ppi"
    try:
        event = _load_event(events, event_id)
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ObservationError("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID")
        now = now.astimezone(timezone.utc)
        if now >= parse_utc(event["release_datetime_utc"]):
            return _base_result("PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED", event_id)
        if not _safe_output_root(root, output):
            return _base_result("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID", event_id)
        collector_result = collector(event_id, root=root, events_path=events, now_utc=now)
    except ObservationError as exc:
        return _base_result(str(exc), event_id)
    except ppi_consensus.PpiConsensusCollectorError:
        return _base_result("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID", event_id)

    status = collector_result.get("status")
    if status not in NORMAL_STATUSES:
        result = _base_result(str(status or "PPI_CONSENSUS_OBSERVATION_INPUT_INVALID"), event_id, collector_result)
        result["next_action"] = "CONFIGURE_PROVIDER_API_KEY" if status == "CONSENSUS_PROVIDER_KEY_MISSING" else "RETRY_CONSENSUS_COLLECTION"
        return result
    try:
        observation = _observation_payload(event, collector_result, now)
    except ObservationError as exc:
        return _base_result(str(exc), event_id, collector_result)

    path = output / event_id / "provider_observations" / f"{_compact_timestamp(observation['retrieved_at_utc'])}.json"
    if path.exists():
        existing_status = _validate_existing(path, _stable_json(observation))
        result = _base_result(existing_status, event_id, collector_result)
        result.update({
            "normalized_status": observation["normalized_status"],
            "retrieved_at_utc": observation["retrieved_at_utc"],
            "observation_path": _relative(root, path),
            "eligible_for_apply": observation["eligible_for_apply"],
            "missing_metrics": observation["missing_metrics"],
            "observation_sha256": observation["integrity"]["sha256"],
            "raw_payload_sha256": observation["raw_payload_sha256"],
            "next_action": "5.3G-2B_AUTO_APPLY_AND_LOCK" if observation["eligible_for_apply"] else "RETRY_CONSENSUS_COLLECTION",
        })
        return result

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.exists()):
        return _base_result("PPI_CONSENSUS_OBSERVATION_INPUT_INVALID", event_id, collector_result)
    content = _stable_json(observation)
    try:
        _write_exclusive(path, content)
    except FileExistsError:
        return capture_observation(event_id, root=root, events_path=events, output_root=output, now_utc=now, collector=collector)
    except OSError:
        return _base_result("PPI_CONSENSUS_OBSERVATION_WRITE_ERROR", event_id, collector_result)
    result = _base_result("PPI_CONSENSUS_OBSERVATION_CAPTURED", event_id, collector_result)
    result.update({
        "normalized_status": observation["normalized_status"],
        "retrieved_at_utc": observation["retrieved_at_utc"],
        "observation_path": _relative(root, path),
        "observation_created": True,
        "eligible_for_apply": observation["eligible_for_apply"],
        "missing_metrics": observation["missing_metrics"],
        "observation_sha256": observation["integrity"]["sha256"],
        "raw_payload_sha256": observation["raw_payload_sha256"],
        "created_paths": [_relative(root, path)],
        "next_action": "5.3G-2B_AUTO_APPLY_AND_LOCK" if observation["eligible_for_apply"] else "RETRY_CONSENSUS_COLLECTION",
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture an immutable pre-release PPI consensus observation")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--events")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--now-utc")
    parser.add_argument("--result-json")
    args = parser.parse_args(argv)
    now = parse_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    result = capture_observation(
        args.event_id,
        events_path=Path(args.events) if args.events else None,
        output_root=Path(args.output_root),
        now_utc=now,
    )
    if args.result_json:
        ppi_consensus.write_result(Path(args.result_json), PROJECT_ROOT, result)
    print(result["status"])
    return 0 if result["status"] in {"PPI_CONSENSUS_OBSERVATION_CAPTURED", "PPI_CONSENSUS_OBSERVATION_ALREADY_EXISTS", "CONSENSUS_PROVIDER_KEY_MISSING", "PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
