from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.collectors import bls_ppi
from scripts.common import preview


METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
WINDOW_HOURS = 24


class PpiCaptureError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CaptureResult:
    status: str
    event_id: str
    reference_period: str
    api_called: bool
    as_released_path: str | None = None
    sha256: str | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def parse_utc(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PpiCaptureError("PPI_INVALID_EVENT", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PpiCaptureError("PPI_INVALID_EVENT", f"{field} requires timezone")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PpiCaptureError("PPI_INVALID_EVENT", "events JSON is unreadable") from exc
    if not isinstance(value, dict):
        raise PpiCaptureError("PPI_INVALID_EVENT", "events JSON must be an object")
    return value


def find_event(events: dict[str, Any], event_id: str) -> dict[str, Any]:
    values = events.get("events")
    matches = [item for item in values if isinstance(item, dict) and item.get("event_id") == event_id] if isinstance(values, list) else []
    if len(matches) != 1:
        raise PpiCaptureError("PPI_EVENT_NOT_FOUND" if not matches else "PPI_DUPLICATE_EVENT", "PPI event must be unique")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US":
        raise PpiCaptureError("PPI_INVALID_EVENT", "event must be US PPI")
    reference = event.get("reference_period")
    expected_id = f"US_PPI_{str(reference).replace('-', '_')}"
    if event_id != expected_id:
        raise PpiCaptureError("PPI_EVENT_REFERENCE_MISMATCH", "event_id and reference period differ")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    return event


def release_path(output_root: Path, event_id: str) -> Path:
    return output_root / "data" / "releases" / "ppi" / event_id / "as_released.json"


def build_payload(event: dict[str, Any], metrics: dict[str, dict[str, Any]], captured: datetime) -> dict[str, Any]:
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    payload = {
        "schema_version": "1.0", "event_id": event["event_id"], "indicator_type": "PPI", "country": "US",
        "reference_period": event["reference_period"], "release_datetime_utc": iso_utc(release),
        "captured_at_utc": iso_utc(captured), "capture_status": "captured_within_release_window",
        "source": {"provider": "BLS", "series_ids": bls_ppi.SOURCE_SERIES},
        "provenance": {"data_origin": "live_release_capture", "vintage_status": "as_released_capture", "not_as_released": False, "immutable": True},
        "metrics": {name: {"actual_raw": metrics[name]["value_raw"], "actual_display": metrics[name]["value_display"], "current_index": metrics[name]["current_index"], "comparison_index": metrics[name]["comparison_index"], "calculation": metrics[name]["calculation"], "series_id": metrics[name]["series_id"], "seasonal_adjustment": metrics[name]["seasonal_adjustment"]} for name in METRICS},
        "integrity": {"sha256": None},
    }
    payload["integrity"]["sha256"] = preview.stable_json_sha256(payload)
    return payload


def valid_existing(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("integrity", {}).get("sha256") == preview.stable_json_sha256(payload) else None


def capture_release(root: Path, event_id: str, *, events_path: Path | None = None, output_root: Path | None = None, now_utc: datetime | None = None, response: dict[str, Any] | None = None, use_live_bls: bool = False, fetcher: Callable[[str], dict[str, Any]] | None = None) -> CaptureResult:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event = find_event(read_json(events_path or root / "data/calendar/events.json"), event_id)
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    path = release_path(output_root or root, event_id)
    existing = valid_existing(path) if path.exists() else None
    if path.exists() and existing is None:
        return CaptureResult("CAPTURE_INTEGRITY_ERROR", event_id, event["reference_period"], False, str(path), None)
    if now < release:
        return CaptureResult("WAITING_FOR_RELEASE", event_id, event["reference_period"], False)
    if now > release + timedelta(hours=WINDOW_HOURS):
        return CaptureResult("CAPTURE_WINDOW_EXPIRED", event_id, event["reference_period"], False)
    if response is None:
        if not use_live_bls and fetcher is None:
            raise PpiCaptureError("PPI_LIVE_BLS_NOT_ENABLED", "live BLS requires explicit flag")
        response = fetcher(event["reference_period"]) if fetcher else bls_ppi.fetch_bls_response(os.environ.get("BLS_API_KEY"), event["reference_period"], logger=None).response
        api_called = True
    else:
        api_called = False
    try:
        series, _ = bls_ppi.parse_bls_response(response)
        metrics = bls_ppi.build_metrics(series, event["reference_period"])
    except bls_ppi.PpiError as exc:
        code = "DATA_NOT_AVAILABLE_YET" if exc.code == "PPI_REFERENCE_PERIOD_NOT_FOUND" else exc.code
        return CaptureResult(code, event_id, event["reference_period"], api_called)
    payload = build_payload(event, metrics, now)
    if existing is not None:
        same = {key: value for key, value in existing.items() if key not in {"captured_at_utc", "integrity"}} == {key: value for key, value in payload.items() if key not in {"captured_at_utc", "integrity"}}
        return CaptureResult("ALREADY_CAPTURED" if same else "CAPTURE_CONFLICT", event_id, event["reference_period"], api_called, str(path), existing["integrity"]["sha256"])
    try:
        preview.write_immutable_bytes(path, preview.json_bytes(payload))
    except preview.ImmutableWriteConflict:
        return CaptureResult("CAPTURE_CONFLICT", event_id, event["reference_period"], api_called)
    return CaptureResult("CAPTURED", event_id, event["reference_period"], api_called, str(path), payload["integrity"]["sha256"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True); parser.add_argument("--events"); parser.add_argument("--output-root", required=True); parser.add_argument("--now-utc"); parser.add_argument("--bls-response"); parser.add_argument("--use-live-bls", action="store_true"); parser.add_argument("--result-json")
    args = parser.parse_args(argv)
    response = read_json(Path(args.bls_response)) if args.bls_response else None
    result = capture_release(Path.cwd(), args.event_id, events_path=Path(args.events) if args.events else None, output_root=Path(args.output_root), now_utc=parse_utc(args.now_utc, "--now-utc") if args.now_utc else None, response=response, use_live_bls=args.use_live_bls)
    if args.result_json: Path(args.result_json).write_bytes(preview.json_bytes(result.payload()))
    print(json.dumps(result.payload(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
