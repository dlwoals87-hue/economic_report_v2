"""Collect pre-release PPI market consensus without changing calendar data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.providers import trading_economics_calendar as provider  # noqa: E402


PPI_EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
STATUS_BY_NORMALIZED = {
    "complete": "PPI_CONSENSUS_COLLECTED",
    "partial": "PPI_CONSENSUS_PARTIAL",
    "unavailable": "PPI_CONSENSUS_UNAVAILABLE",
}


class PpiConsensusCollectorError(Exception):
    pass


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED") from exc
    if parsed.tzinfo is None:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_calendar(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    return payload


def _find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    match = PPI_EVENT_RE.fullmatch(event_id)
    if match is None:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    matches = [item for item in calendar["events"] if isinstance(item, dict) and item.get("event_id") == event_id]
    if len(matches) != 1:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US":
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    if event.get("reference_period") != f"{match.group(1)}-{match.group(2)}":
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    return event


def _allowed_result_bases(root: Path) -> tuple[Path, ...]:
    return (
        root.resolve(),
        Path(tempfile.gettempdir()).resolve(),
        (root.parent / "economic_report_v2_ppi_ops").resolve(strict=False),
    )


def safe_result_path(path: Path, root: Path) -> bool:
    """Allow only non-symlink diagnostic output outside immutable data areas."""

    if ".." in path.parts or str(path).startswith(("\\\\.\\", "\\\\?\\")):
        return False
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    if not any(resolved.is_relative_to(base) for base in _allowed_result_bases(root)):
        return False
    if path.exists() and (path.is_symlink() or path.is_dir()):
        return False
    if not path.parent.exists() or path.parent.is_symlink():
        return False
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent.exists()):
        return False
    protected = (
        (root / "data" / "calendar" / "events.json").resolve(strict=False),
        (root / "data" / "consensus").resolve(strict=False),
        (root / "data" / "releases").resolve(strict=False),
    )
    return not any(resolved == item or resolved.is_relative_to(item) for item in protected)


def _stable_json(payload: dict[str, Any]) -> bytes:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json.loads(content)
    return content.encode("utf-8")


def write_result(path: Path, root: Path, result: dict[str, Any]) -> None:
    if not safe_result_path(path, root):
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    content = _stable_json(result)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _base_result(status: str, event: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "event_id": event.get("event_id") if event else None,
        "provider": "trading_economics",
        "external_api_called": False,
        "external_ai_api_called": False,
        "cost": "free",
    }
    if event:
        result["reference_period"] = event["reference_period"]
        result["release_datetime_utc"] = event["release_datetime_utc"]
    return result


def collect(
    event_id: str,
    *,
    root: Path = PROJECT_ROOT,
    events_path: Path | None = None,
    now_utc: datetime | None = None,
    api_key: str | None = None,
    provider_fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return a collector result; calendar data and snapshots remain untouched."""

    root = root.resolve()
    calendar = _read_calendar(events_path or root / "data" / "calendar" / "events.json")
    event = _find_event(calendar, event_id)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise PpiConsensusCollectorError("PPI_CONSENSUS_INPUT_REQUIRED")
    now = now.astimezone(timezone.utc)
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    if now >= release:
        return _base_result("PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED", event)

    key = api_key if api_key is not None else os.environ.get("TRADING_ECONOMICS_API_KEY")
    if not key or not key.strip():
        return _base_result("CONSENSUS_PROVIDER_KEY_MISSING", event)

    fetcher = provider_fetcher or provider.fetch_calendar
    try:
        rows = fetcher(key)
        normalized = provider.normalize(
            rows,
            event_id=event_id,
            reference_period=event["reference_period"],
            release_datetime_utc=event["release_datetime_utc"],
            retrieved_at_utc=iso_utc(now),
        )
    except provider.ProviderError as exc:
        result = _base_result(exc.status, event)
        result["external_api_called"] = True
        return result

    result = _base_result(STATUS_BY_NORMALIZED[normalized["status"]], event)
    result.update(
        {
            "external_api_called": True,
            "normalized_status": normalized["status"],
            "retrieved_at_utc": normalized["retrieved_at_utc"],
            "metrics": normalized["metrics"],
            "raw_payload_sha256": normalized["raw_payload_sha256"],
            "normalized_sha256": normalized["integrity"]["sha256"],
            "provider_data_type": normalized["provider_data_type"],
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect pre-release PPI consensus without changing calendar data")
    parser.add_argument("--event-id")
    parser.add_argument("--events")
    parser.add_argument("--now-utc")
    parser.add_argument("--result-json")
    args = parser.parse_args(argv)
    if not args.event_id:
        print("PPI_CONSENSUS_INPUT_REQUIRED", file=sys.stderr)
        return 2
    root = PROJECT_ROOT
    event: dict[str, Any] | None = None
    try:
        now = parse_utc(args.now_utc, "now_utc") if args.now_utc else datetime.now(timezone.utc)
        events = Path(args.events) if args.events else root / "data" / "calendar" / "events.json"
        result = collect(args.event_id, root=root, events_path=events, now_utc=now)
        event = {"event_id": result["event_id"]} if result.get("event_id") else None
        if args.result_json:
            write_result(Path(args.result_json), root, result)
    except PpiConsensusCollectorError as exc:
        result = _base_result(str(exc), event)
        result["event_id"] = args.event_id
        if args.result_json:
            try:
                write_result(Path(args.result_json), root, result)
            except PpiConsensusCollectorError:
                print("PPI_CONSENSUS_INPUT_REQUIRED", file=sys.stderr)
                return 2
        print(result["status"], file=sys.stderr)
        return 1
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
