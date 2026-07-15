"""Build a CPI consensus snapshot from one provider-neutral observation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.consensus import cpi_contract as contract


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _result(status: str, event_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": status, "event_id": event_id, "snapshot_path": None,
        "snapshot_sha256": None, "snapshot_created": False,
        "external_api_called": False, "external_ai_api_called": False, "cost": "free",
        **extra,
    }


def run(
    event_id: str,
    *,
    observation_path: Path,
    root: Path = PROJECT_ROOT,
    events_path: Path | None = None,
    now_utc: datetime | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        if not contract.safe_under(root, observation_path):
            raise contract.CpiConsensusContractError("observation path is unsafe")
        calendar_path = events_path or root / "data" / "calendar" / "events.json"
        if not contract.safe_under(root, calendar_path):
            raise contract.CpiConsensusContractError("calendar path is unsafe")
        event = contract.find_event(contract.read_json(calendar_path), event_id)
        observation = contract.read_json(observation_path)
        status = contract.validate_observation(observation, event)
        if status == "AFTER_RELEASE" or now >= contract.parse_utc(event["release_datetime_utc"], "release_datetime_utc"):
            return _result("CONSENSUS_AFTER_RELEASE", event_id)
        status_map = {
            "INCOMPLETE": "CONSENSUS_INCOMPLETE", "UNAVAILABLE": "CONSENSUS_UNAVAILABLE",
            "INVALID": "CONSENSUS_INVALID", "STALE": "CONSENSUS_INVALID",
        }
        if status != "COMPLETE":
            return _result(status_map[status], event_id)
        snapshot = contract.build_snapshot(observation, event, now)
        target = contract.snapshot_path(root, event_id)
        relative = contract.safe_relative(root, target)
        if not apply:
            return _result("SNAPSHOT_READY", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"])
        if target.exists() or target.is_symlink():
            existing = contract.read_json(target)
            try:
                contract.validate_snapshot(existing, event)
            except contract.CpiConsensusContractError:
                return _result("SNAPSHOT_CONFLICT", event_id, snapshot_path=relative)
            result_status = "SNAPSHOT_ALREADY_EXISTS" if existing == snapshot else "SNAPSHOT_CONFLICT"
            return _result(result_status, event_id, snapshot_path=relative, snapshot_sha256=existing["integrity"]["sha256"])
        try:
            contract.write_exclusive(target, snapshot)
        except FileExistsError:
            return run(event_id, observation_path=observation_path, root=root, events_path=calendar_path, now_utc=now, apply=True)
        return _result("SNAPSHOT_CREATED", event_id, snapshot_path=relative, snapshot_sha256=snapshot["integrity"]["sha256"], snapshot_created=True)
    except contract.CpiConsensusContractError:
        return _result("INVALID_INPUT", event_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or build an immutable CPI consensus snapshot")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--events")
    parser.add_argument("--now-utc")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    now = contract.parse_utc(args.now_utc, "--now-utc") if args.now_utc else None
    result = run(args.event_id, observation_path=Path(args.observation), events_path=Path(args.events) if args.events else None, now_utc=now, apply=args.apply)
    print(result["status"])
    return 0 if result["status"] in {"SNAPSHOT_READY", "SNAPSHOT_CREATED", "SNAPSHOT_ALREADY_EXISTS", "CONSENSUS_INCOMPLETE", "CONSENSUS_UNAVAILABLE", "CONSENSUS_AFTER_RELEASE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
