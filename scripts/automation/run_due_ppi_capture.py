from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipelines import capture_ppi_release as capture  # noqa: E402


def run_due_capture(root: Path, *, now_utc: datetime | None = None, event_id: str | None = None, capture_func: Callable[..., Any] | None = None) -> tuple[dict[str, Any], int]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = capture.read_json(root / "data/calendar/events.json").get("events", [])
    if event_id:
        result = (capture_func or capture.capture_release)(root, event_id, now_utc=now)
        return result.payload(), 0
    due = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("indicator_type") != "PPI": continue
        release = capture.parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
        if release <= now <= release + timedelta(hours=24): due.append(event)
    if not due: return {"status":"NO_DUE_PPI_EVENT","event_id":None,"reference_period":None,"api_called":False,"created_paths":[],"commit_paths":[],"external_ai_api_called":False,"cost":"free"}, 0
    if len(due) > 1: return {"status":"MULTIPLE_DUE_PPI_EVENTS","event_id":None,"reference_period":None,"api_called":False,"created_paths":[],"commit_paths":[],"external_ai_api_called":False,"cost":"free"}, 1
    result = (capture_func or capture.capture_release)(root, due[0]["event_id"], now_utc=now)
    payload = result.payload(); created = [payload["as_released_path"]] if payload["status"] == "CAPTURED" and payload.get("as_released_path") else []
    payload.update({"created_paths":created,"commit_paths":created,"external_ai_api_called":False,"cost":"free"})
    return payload, 0


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--event-id"); parser.add_argument("--now-utc"); parser.add_argument("--result-json", required=True); args=parser.parse_args(argv)
    result, code = run_due_capture(Path.cwd(), event_id=args.event_id, now_utc=capture.parse_utc(args.now_utc,"--now-utc") if args.now_utc else None)
    result_path = Path(args.result_json)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(result["status"]); return code


if __name__ == "__main__":
    raise SystemExit(main())
