"""Project a validated immutable CPI snapshot into a calendar event."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.consensus import cpi_contract as contract
from scripts.validators import validate_calendar_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _result(status: str, event_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": status, "event_id": event_id, "calendar_changed": False,
        "snapshot_path": None, "snapshot_sha256": None, "external_api_called": False,
        "external_ai_api_called": False, "cost": "free", **extra,
    }


def _write_calendar(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _projection(snapshot: dict[str, Any], relative_path: str) -> dict[str, Any]:
    return {
        "expected": {key: snapshot["metrics"][key]["expected_raw"] for key in contract.CPI_METRICS},
        "consensus_source": snapshot["provider"]["name"],
        "consensus_status": "complete",
        "entered_at_utc": snapshot["captured_at_utc"],
        "consensus_snapshot_path": relative_path,
        "consensus_snapshot_sha256": snapshot["integrity"]["sha256"],
    }


def _matches(event: dict[str, Any], projection: dict[str, Any]) -> bool:
    metrics = event.get("metrics")
    return isinstance(metrics, dict) and all(isinstance(metrics.get(key), dict) and metrics[key].get("expected") == projection["expected"][key] for key in contract.CPI_METRICS) and all(event.get(key) == projection[key] for key in ("consensus_source", "consensus_status", "entered_at_utc", "consensus_snapshot_path", "consensus_snapshot_sha256"))


def run(
    event_id: str,
    *,
    snapshot_path: Path,
    root: Path = PROJECT_ROOT,
    events_path: Path | None = None,
    now_utc: datetime | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        if not contract.safe_under(root, snapshot_path):
            raise contract.CpiConsensusContractError("snapshot path is unsafe")
        calendar_path = events_path or root / "data" / "calendar" / "events.json"
        if not contract.safe_under(root, calendar_path):
            raise contract.CpiConsensusContractError("calendar path is unsafe")
        calendar = contract.read_json(calendar_path)
        event = contract.find_event(calendar, event_id)
        snapshot = contract.read_json(snapshot_path)
        contract.validate_snapshot(snapshot, event)
        relative = contract.safe_relative(root, snapshot_path)
        if now >= contract.parse_utc(event["release_datetime_utc"], "release_datetime_utc"):
            return _result("CONSENSUS_AFTER_RELEASE", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
        projection = _projection(snapshot, relative)
        if _matches(event, projection):
            return _result("CONSENSUS_ALREADY_APPLIED", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
        metrics = event["metrics"]
        if any(metrics[key].get("expected") is not None for key in contract.CPI_METRICS) or event.get("consensus_snapshot_path") not in (None, relative):
            return _result("CONSENSUS_APPLY_CONFLICT", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
        if not apply:
            return _result("CONSENSUS_APPLY_READY", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
        updated = copy.deepcopy(calendar)
        target = contract.find_event(updated, event_id)
        for key in contract.CPI_METRICS:
            target["metrics"][key]["expected"] = projection["expected"][key]
        for key in ("consensus_source", "consensus_status", "entered_at_utc", "consensus_snapshot_path", "consensus_snapshot_sha256"):
            target[key] = projection[key]
        if not validate_calendar_events.validate_events_payload(updated, now=now).valid:
            return _result("INVALID_INPUT", event_id, snapshot_path=relative)
        _write_calendar(calendar_path, updated)
        return _result("CONSENSUS_APPLIED", event_id, calendar_changed=True, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
    except contract.CpiConsensusContractError:
        return _result("INVALID_INPUT", event_id)
    except OSError:
        return _result("INVALID_INPUT", event_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or apply a CPI consensus snapshot")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--events")
    parser.add_argument("--now-utc")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    now = contract.parse_utc(args.now_utc, "--now-utc") if args.now_utc else None
    result = run(args.event_id, snapshot_path=Path(args.snapshot), events_path=Path(args.events) if args.events else None, now_utc=now, apply=args.apply)
    print(result["status"])
    return 0 if result["status"] in {"CONSENSUS_APPLY_READY", "CONSENSUS_APPLIED", "CONSENSUS_ALREADY_APPLIED", "CONSENSUS_AFTER_RELEASE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
