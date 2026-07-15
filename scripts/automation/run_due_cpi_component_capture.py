"""Explicitly opt-in runner for the separate CPI component capture pipeline."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.collectors import bls_cpi
from scripts.pipelines import capture_cpi_components


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _live_fetcher(api_key: str | None, now: datetime):
    def fetch(series_ids: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
        fetched = bls_cpi.fetch_bls_response(api_key, now=now, logger=None, series_ids=series_ids)
        return fetched.response, {
            "request_count": fetched.request_count,
            "request_mode": fetched.request_mode,
            "registration_key_used": fetched.registration_key_used,
            "registration_key_rejected": fetched.registration_key_rejected,
            "fallback_used": fetched.fallback_used,
        }

    return fetch


def _select_due_event(root: Path, now: datetime) -> str | None:
    calendar = json.loads((root / "data" / "calendar" / "events.json").read_text(encoding="utf-8"))
    candidates: list[str] = []
    for event in calendar.get("events", []):
        if not isinstance(event, dict) or event.get("indicator_type") != "CPI":
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str):
            continue
        headline = root / "data" / "releases" / "cpi" / event_id / "as_released.json"
        component = root / "data" / "releases" / "cpi" / event_id / "components_as_released.json"
        release_text = event.get("release_datetime_utc")
        if not headline.is_file() or component.exists() or not isinstance(release_text, str):
            continue
        release = datetime.fromisoformat(release_text.replace("Z", "+00:00")).astimezone(timezone.utc)
        if release <= now <= release + timedelta(hours=24):
            candidates.append(event_id)
    if len(candidates) == 1:
        return candidates[0]
    return None


def run_component_capture(
    event_id: str | None,
    *,
    root: Path | None = None,
    enable_live_bls: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = (root or project_root()).resolve()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected_event_id = event_id or _select_due_event(root, current)
    if selected_event_id is None:
        return {
            "schema_version": "1.0",
            "status": "NO_DUE_COMPONENT_EVENT",
            "event_id": None,
            "reference_period": None,
            "api_called": False,
            "external_ai_api_called": False,
            "commit_paths": [],
        }
    if not enable_live_bls:
        return capture_cpi_components.run(selected_event_id, root=root, now=current)
    return capture_cpi_components.run(
        selected_event_id,
        root=root,
        now=current,
        fetcher=_live_fetcher(os.environ.get("BLS_API_KEY"), current),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id")
    parser.add_argument("--enable-live-bls", action="store_true")
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()
    result = run_component_capture(args.event_id, enable_live_bls=args.enable_live_bls)
    output = Path(args.result_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["status"])
    print(f"event_id: {result['event_id']}")
    print(f"api_called: {str(result['api_called']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
