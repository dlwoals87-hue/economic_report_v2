from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
CAPTURE_WINDOW_HOURS = 24
JUNE_CPI_EVENT_ID = "US_CPI_2026_06"
JUNE_CPI_REFERENCE_PERIOD = "2026-06"
JUNE_CPI_RELEASE_UTC = "2026-07-14T12:30:00Z"


class CaptureError(Exception):
    """Raised when release capture cannot continue."""


@dataclass(frozen=True)
class CaptureResult:
    status: str
    event_id: str
    reference_period: str
    release_datetime_utc: str
    api_call_count: int = 0
    capture_window_end_utc: str | None = None
    now_utc: str | None = None
    latest_reference_period: str | None = None
    raw_snapshot_path: str | None = None
    processed_path: str | None = None
    as_released_path: str | None = None
    sha256: str | None = None
    request_mode: str | None = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_utc_datetime(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{field_name}: timezone-aware ISO 8601 value required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CaptureError(f"{field_name}: invalid timezone-aware ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise CaptureError(f"{field_name}: timezone offset required")
    return parsed.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def capture_window_end(release_dt: datetime) -> datetime:
    return release_dt + timedelta(hours=CAPTURE_WINDOW_HOURS)


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise CaptureError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CaptureError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def june_cpi_event() -> dict[str, Any]:
    return {
        "event_id": JUNE_CPI_EVENT_ID,
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": JUNE_CPI_REFERENCE_PERIOD,
        "release_datetime_utc": JUNE_CPI_RELEASE_UTC,
        "metrics": {
            metric: {
                "expected": None,
                "unit": "%",
            }
            for metric in CPI_METRICS
        },
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def ensure_june_cpi_event(calendar: dict[str, Any]) -> bool:
    events = calendar.get("events")
    if not isinstance(events, list):
        raise CaptureError("calendar events must be a list")
    if any(isinstance(event, dict) and event.get("event_id") == JUNE_CPI_EVENT_ID for event in events):
        return False
    events.append(june_cpi_event())
    return True


def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    events = calendar.get("events")
    if not isinstance(events, list):
        raise CaptureError("calendar events must be a list")
    matches = [event for event in events if isinstance(event, dict) and event.get("event_id") == event_id]
    if not matches:
        raise CaptureError(f"event not found: {event_id}")
    if len(matches) > 1:
        raise CaptureError(f"duplicate event_id: {event_id}")
    event = matches[0]
    if event.get("indicator_type") != "CPI":
        raise CaptureError(f"event is not CPI: {event_id}")
    parse_utc_datetime(event.get("release_datetime_utc"), "release_datetime_utc")
    return event


def release_path(root: Path, event_id: str) -> Path:
    return root / "data" / "releases" / "cpi" / event_id / "as_released.json"


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def import_bls_collector(root: Path):
    module_path = root / "scripts" / "collectors" / "bls_cpi.py"
    spec = importlib.util.spec_from_file_location("bls_cpi_for_capture", module_path)
    if spec is None or spec.loader is None:
        raise CaptureError("could not load BLS CPI collector")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bls_cpi_for_capture"] = module
    spec.loader.exec_module(module)
    return module


def default_collect_latest(root: Path, now_utc: datetime) -> dict[str, Any]:
    collector = import_bls_collector(root)
    return collector.collect_and_save(
        api_key=os.environ.get("BLS_API_KEY"),
        root=root,
        now=now_utc,
    )


def metric_as_released(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "actual_as_released_raw": metric["actual_current_raw"],
        "actual_as_released_display": metric["actual_current_display"],
        "previous_as_released_raw": metric["previous_current_raw"],
        "previous_as_released_display": metric["previous_current_display"],
    }


def hashable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cloned = json.loads(json.dumps(payload, ensure_ascii=False))
    integrity = cloned.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("sha256", None)
    return cloned


def stable_sha256(payload: dict[str, Any]) -> str:
    # The digest excludes integrity.sha256 and uses sorted compact JSON, making
    # identical release content produce the same SHA-256 across runs.
    stable_bytes = json.dumps(
        hashable_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(stable_bytes).hexdigest()


def build_release_payload(
    event: dict[str, Any],
    processed_payload: dict[str, Any],
    raw_snapshot_path: str,
    captured_at_utc: datetime,
) -> dict[str, Any]:
    metrics = processed_payload.get("metrics")
    if not isinstance(metrics, dict):
        raise CaptureError("processed payload missing metrics")
    missing = [metric for metric in CPI_METRICS if metric not in metrics]
    if missing:
        raise CaptureError(f"processed payload missing metrics: {missing}")
    release_dt = parse_utc_datetime(event["release_datetime_utc"], "release_datetime_utc")
    window_end = capture_window_end(release_dt)
    capture_delay_seconds = int((captured_at_utc.astimezone(timezone.utc) - release_dt).total_seconds())
    max_delay_seconds = CAPTURE_WINDOW_HOURS * 60 * 60
    if capture_delay_seconds < 0:
        raise CaptureError("capture_delay_seconds must not be negative")
    if capture_delay_seconds > max_delay_seconds:
        raise CaptureError("capture is outside the allowed release window")

    payload = {
        "schema_version": "1.0",
        "event_id": event["event_id"],
        "indicator_type": "CPI",
        "country": event.get("country", "US"),
        "reference_period": event["reference_period"],
        "release_datetime_utc": event["release_datetime_utc"],
        "captured_at_utc": iso_utc(captured_at_utc),
        "capture_status": "captured",
        "capture_window_hours": CAPTURE_WINDOW_HOURS,
        "capture_window_end_utc": iso_utc(window_end),
        "capture_delay_seconds": capture_delay_seconds,
        "captured_within_window": True,
        "release_vintage": "first_observed_after_release",
        "metrics": {
            metric: metric_as_released(metrics[metric])
            for metric in CPI_METRICS
        },
        "source": {
            "provider": "U.S. Bureau of Labor Statistics",
            "raw_snapshot_path": raw_snapshot_path,
            "request_mode": processed_payload.get("request_mode"),
            "retrieved_at_utc": processed_payload.get("retrieved_at_utc"),
        },
        "integrity": {
            "immutable": True,
            "sha256": None,
        },
    }
    payload["integrity"]["sha256"] = stable_sha256(payload)
    return payload


def write_immutable_release(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.rename(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def existing_release_sha(path: Path) -> str | None:
    try:
        payload = read_json(path)
    except CaptureError:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    integrity = payload.get("integrity")
    if isinstance(integrity, dict) and isinstance(integrity.get("sha256"), str):
        return integrity["sha256"]
    return stable_sha256(payload)


def capture_release(
    root: Path,
    event_id: str,
    now_utc: datetime | None = None,
    collector: Callable[[Path, datetime], dict[str, Any]] | None = None,
) -> CaptureResult:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    calendar = read_json(root / "data" / "calendar" / "events.json")
    event = find_event(calendar, event_id)
    release_dt = parse_utc_datetime(event["release_datetime_utc"], "release_datetime_utc")
    window_end = capture_window_end(release_dt)
    target_reference = event["reference_period"]
    out_path = release_path(root, event_id)

    if out_path.exists():
        return CaptureResult(
            status="ALREADY_CAPTURED",
            event_id=event_id,
            reference_period=target_reference,
            release_datetime_utc=iso_utc(release_dt),
            capture_window_end_utc=iso_utc(window_end),
            now_utc=iso_utc(now),
            api_call_count=0,
            as_released_path=relative_path(out_path, root),
            sha256=existing_release_sha(out_path),
        )

    if now < release_dt:
        return CaptureResult(
            status="WAITING_FOR_RELEASE",
            event_id=event_id,
            reference_period=target_reference,
            release_datetime_utc=iso_utc(release_dt),
            capture_window_end_utc=iso_utc(window_end),
            now_utc=iso_utc(now),
            api_call_count=0,
        )

    if now > window_end:
        return CaptureResult(
            status="CAPTURE_WINDOW_EXPIRED",
            event_id=event_id,
            reference_period=target_reference,
            release_datetime_utc=iso_utc(release_dt),
            capture_window_end_utc=iso_utc(window_end),
            now_utc=iso_utc(now),
            api_call_count=0,
        )

    collect = collector or default_collect_latest
    collect_result = collect(root, now)
    processed_payload = collect_result["processed_payload"]
    latest_reference = collect_result["reference_period"]
    raw_path = relative_path(collect_result["raw_snapshot_path"], root)
    processed_path = relative_path(collect_result["processed_path"], root)
    fetch_result = collect_result.get("fetch_result")
    api_call_count = int(getattr(fetch_result, "request_count", 1))

    if latest_reference != target_reference:
        return CaptureResult(
            status="DATA_NOT_AVAILABLE_YET",
            event_id=event_id,
            reference_period=target_reference,
            release_datetime_utc=iso_utc(release_dt),
            capture_window_end_utc=iso_utc(window_end),
            now_utc=iso_utc(now),
            api_call_count=api_call_count,
            latest_reference_period=latest_reference,
            raw_snapshot_path=raw_path,
            request_mode=processed_payload.get("request_mode"),
        )

    payload = build_release_payload(
        event=event,
        processed_payload=processed_payload,
        raw_snapshot_path=raw_path,
        captured_at_utc=now,
    )
    write_immutable_release(out_path, payload)
    return CaptureResult(
        status="CAPTURED",
        event_id=event_id,
        reference_period=target_reference,
        release_datetime_utc=iso_utc(release_dt),
        capture_window_end_utc=iso_utc(window_end),
        now_utc=iso_utc(now),
        api_call_count=api_call_count,
        latest_reference_period=latest_reference,
        raw_snapshot_path=raw_path,
        as_released_path=relative_path(out_path, root),
        processed_path=processed_path,
        sha256=payload["integrity"]["sha256"],
        request_mode=processed_payload.get("request_mode"),
    )


def print_result(result: CaptureResult) -> None:
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"reference_period: {result.reference_period}")
    print(f"release_datetime_utc: {result.release_datetime_utc}")
    if result.capture_window_end_utc:
        print(f"capture_window_end_utc: {result.capture_window_end_utc}")
    if result.now_utc:
        print(f"now_utc: {result.now_utc}")
    print(f"BLS API calls: {result.api_call_count}")
    if result.latest_reference_period:
        print(f"latest_reference_period: {result.latest_reference_period}")
    if result.raw_snapshot_path:
        print(f"raw_snapshot_path: {result.raw_snapshot_path}")
    if result.processed_path:
        print(f"processed_path: {result.processed_path}")
    if result.as_released_path:
        print(f"as_released_path: {result.as_released_path}")
    if result.request_mode:
        print(f"request_mode: {result.request_mode}")
    if result.sha256:
        print(f"sha256: {result.sha256}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--now-utc")
    args = parser.parse_args()

    try:
        now = parse_utc_datetime(args.now_utc, "--now-utc") if args.now_utc else None
        result = capture_release(project_root(), args.event_id, now_utc=now)
    except CaptureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
