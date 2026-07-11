from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis import generate_cpi_analysis  # noqa: E402
from scripts.automation import update_report_index  # noqa: E402
from scripts.collectors import bls_cpi  # noqa: E402
from scripts.common import preview as common_preview  # noqa: E402
from scripts.pipelines import build_cpi_release_report  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")


class BackfillError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class BackfillResult:
    status: str
    event_id: str
    reference_period: str | None
    data_api_called: bool
    ai_api_called: bool
    cost: str
    output_files: tuple[str, ...]
    observation_sha256: str | None
    preview_links_valid: bool | None = None
    missing_local_links: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = "1.0"
        value["output_files"] = list(self.output_files)
        value["missing_local_links"] = list(self.missing_local_links)
        return value


def project_root() -> Path:
    return PROJECT_ROOT


def stable_sha256(payload: dict[str, Any]) -> str:
    return common_preview.stable_json_sha256(payload)


def file_sha256(path: Path) -> str:
    return common_preview.file_sha256(path)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_new(path: Path, data: bytes) -> None:
    try:
        common_preview.write_immutable_bytes(path, data)
    except common_preview.ImmutableWriteConflict as exc:
        raise BackfillError("BACKFILL_CONFLICT", f"output already exists: {path.name}") from exc


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def read_calendar_event(root: Path, event_id: str, now: datetime) -> dict[str, Any]:
    try:
        calendar = validate_calendar_events.read_json(root / "data" / "calendar" / "events.json")
        validation = validate_calendar_events.validate_events_payload(calendar, now=now)
    except ValueError as exc:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", "calendar is unreadable") from exc
    if not validation.valid:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", "calendar validation failed")
    events = calendar.get("events")
    matches = [item for item in events if isinstance(item, dict) and item.get("event_id") == event_id] if isinstance(events, list) else []
    if len(matches) != 1:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", "target event is not unique")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", "target event must be US CPI")
    if event.get("reference_period") != "2026-05":
        raise BackfillError("BACKFILL_REFERENCE_PERIOD_MISMATCH", "target reference_period must be 2026-05")
    if parse_utc(event.get("release_datetime_utc"), "release_datetime_utc") >= now:
        raise BackfillError("BACKFILL_EVENT_NOT_FOUND", "target event is not historical")
    return event


def output_root_path(root: Path, value: str) -> Path:
    try:
        return common_preview.external_preview_root(root, Path(value))
    except common_preview.PreviewSafetyError as exc:
        raise BackfillError("BACKFILL_INVALID_OUTPUT_ROOT", str(exc)) from exc


def fetch_live_response(now: datetime) -> dict[str, Any]:
    return bls_cpi.fetch_bls_response(None, now=now, logger=None).response


def build_observation(event: dict[str, Any], response: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    try:
        series, _validation = bls_cpi.parse_bls_response(response)
    except bls_cpi.DataValidationError as exc:
        raise BackfillError("BACKFILL_PARTIAL_DATA", str(exc)) from exc
    period = event["reference_period"]
    missing = [series_id for series_id in bls_cpi.SOURCE_SERIES.values() if period not in series.get(series_id, {})]
    if missing:
        raise BackfillError("BACKFILL_DATA_NOT_AVAILABLE", "target reference period is not available for all series")
    try:
        calculated = bls_cpi.build_metrics(series, period)
    except bls_cpi.DataValidationError as exc:
        raise BackfillError("BACKFILL_DATA_NOT_AVAILABLE", str(exc)) from exc
    metrics = {
        key: {
            "series_id": calculated[key]["series_id"],
            "current_raw": calculated[key]["actual_current_raw"],
            "current_display": calculated[key]["actual_current_display"],
            "previous_raw": calculated[key]["previous_current_raw"],
            "previous_display": calculated[key]["previous_current_display"],
            "unit": "%",
        }
        for key in CPI_METRICS
    }
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event["event_id"],
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": period,
        "original_release_datetime_utc": event["release_datetime_utc"],
        "retrieved_at_utc": iso_utc(retrieved_at),
        "source": {"provider": "BLS", "series_ids": [bls_cpi.SOURCE_SERIES[key] for key in CPI_METRICS]},
        "provenance": {"data_origin": "historical_backfill", "vintage_status": "current_api_snapshot", "not_as_released": True, "immutable": True},
        "metrics": metrics,
        "integrity": {"sha256": None},
    }
    payload["integrity"]["sha256"] = stable_sha256(payload)
    common_preview.validate_historical_provenance(payload["provenance"], payload["retrieved_at_utc"], payload["integrity"]["sha256"])
    return payload


def build_canonical(event: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    observation_sha = observation["integrity"]["sha256"]
    grouped = {"headline": {}, "core": {}}
    locations = {"headline_mom": ("headline", "mom"), "headline_yoy": ("headline", "yoy"), "core_mom": ("core", "mom"), "core_yoy": ("core", "yoy")}
    for key, (section, cadence) in locations.items():
        metric = observation["metrics"][key]
        grouped[section][cadence] = {
            "actual_raw": metric["current_raw"],
            "actual_display": metric["current_display"],
            "previous_raw": metric["previous_raw"],
            "previous_display": metric["previous_display"],
            "expected": None,
            "unit": "%",
            "surprise": None,
        }
    grouped["consensus"] = {"status": "not_locked", "source": None, "entered_at_utc": None, "locked_at_utc": None, "consensus_snapshot_path": None, "consensus_snapshot_sha256": None}
    return {
        "schema_version": "1.0",
        "meta": {"event_id": event["event_id"], "indicator_type": "CPI", "indicator_name": "US Consumer Price Index", "country": "US", "reference_period": event["reference_period"], "release_datetime_utc": event["release_datetime_utc"], "release_datetime_kst": iso_kst(release), "is_sample": False, "data_origin": "historical_backfill", "data_status": "historical_backfill", "analysis_status": "pending"},
        "event": grouped,
        "source": {"provider": "BLS", "historical_observation_sha256": observation_sha, "retrieved_at_utc": observation["retrieved_at_utc"], "vintage_status": "current_api_snapshot", "not_as_released": True},
        "analysis": {"status": "pending", "provider": None, "model": None, "generated_at_utc": None, "summary_html": None, "key_points": []},
    }


def decorate_report(document: str) -> str:
    notice = '<section id="historical-backfill-notice"><p>Historical CPI backfill rehearsal. Data is a current BLS API historical snapshot, not release-time captured data. Not investment advice.</p></section>'
    if "</body>" not in document:
        raise BackfillError("BACKFILL_CONFLICT", "rendered report has no body closing tag")
    return document.replace("actual_as_released", "historical current value").replace("release_capture", "historical_observation").replace("</body>", notice + "</body>", 1)


HREF_RE = re.compile(r'''\b(?:href|src)=["']([^"']+)["']''', re.IGNORECASE)
HTML_SUFFIXES = {".html", ".htm"}
BLOCKED_PARTS = {".git", ".github", "data", "scripts"}


def local_reference(value: str) -> Path | None:
    try:
        return common_preview.local_preview_reference(value, blocked_top_levels=BLOCKED_PARTS)
    except common_preview.PreviewSafetyError as exc:
        raise BackfillError("BACKFILL_PREVIEW_LINKS_INVALID", str(exc)) from exc


def copy_preview_file(source_root: Path, destination_root: Path, relative: Path) -> bool:
    source = source_root / relative
    destination = destination_root / relative
    if not source.is_file() or source.is_symlink():
        raise BackfillError("BACKFILL_PREVIEW_LINKS_INVALID", f"missing or unsafe docs asset: {relative.as_posix()}")
    if destination.exists():
        if destination.is_symlink() or file_sha256(source) != file_sha256(destination):
            raise BackfillError("BACKFILL_CONFLICT", f"existing preview asset differs: {relative.as_posix()}")
        return False
    write_new(destination, source.read_bytes())
    return True


def referenced_paths(document: str) -> tuple[Path, ...]:
    references: list[Path] = []
    for value in HREF_RE.findall(document):
        reference = local_reference(value)
        if reference is not None and reference not in references:
            references.append(reference)
    return tuple(references)


def repair_preview_links(root: Path, preview_root: Path, event_id: str) -> tuple[bool, tuple[str, ...], int]:
    index = preview_root / "index.html"
    report = preview_root / "report.html"
    if not index.is_file() or not report.is_file():
        raise BackfillError("BACKFILL_PREVIEW_LINKS_INVALID", "preview index or report is missing")
    changed = False
    copied_html = 0
    queue = list(referenced_paths(index.read_text(encoding="utf-8")))
    visited: set[Path] = set()
    while queue:
        relative = queue.pop(0)
        if relative in visited:
            continue
        visited.add(relative)
        target = preview_root / relative
        if target.exists():
            if target.is_symlink():
                raise BackfillError("BACKFILL_PREVIEW_LINKS_INVALID", "preview link target is a symlink")
        else:
            changed = copy_preview_file(root / "docs", preview_root, relative) or changed
            if relative.suffix.lower() in HTML_SUFFIXES:
                copied_html += 1
        if relative.suffix.lower() in HTML_SUFFIXES:
            source_html = preview_root / relative
            for asset in referenced_paths(source_html.read_text(encoding="utf-8")):
                if asset not in visited:
                    queue.append(asset)
    missing: list[str] = []
    for relative in referenced_paths(index.read_text(encoding="utf-8")):
        if relative.suffix.lower() in HTML_SUFFIXES and not (preview_root / relative).is_file():
            missing.append(relative.as_posix())
    if missing:
        raise BackfillError("BACKFILL_PREVIEW_LINKS_INVALID", "missing local HTML preview links")
    return changed, tuple(missing), copied_html


def write_existing_result(path: Path, result: BackfillResult) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(json_bytes(result.payload()))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_index(source: str, event: dict[str, Any], report_sha: str) -> str:
    prefix, managed, suffix = update_report_index._marker_bounds(source)
    entries = update_report_index._parse_entries(managed)
    entry = update_report_index.ReportEntry(event["event_id"], "US Consumer Price Index", event["reference_period"], iso_kst(parse_utc(event["release_datetime_utc"], "release_datetime_utc")), "report.html", report_sha)
    if any(existing.event_id == entry.event_id for existing in entries):
        raise BackfillError("BACKFILL_CONFLICT", "backfill report is already indexed differently")
    candidate = prefix + update_report_index._render_managed_region(entries + [entry]) + suffix
    update_report_index._validate_final_index(source, candidate, update_report_index._render_managed_region(entries + [entry]))
    return candidate


def existing_result(event_dir: Path) -> BackfillResult | None:
    result_file = event_dir / "result.json"
    expected = ("historical_observation.json", "canonical.json", "analysis.json", "report.html", "index.html", "result.json")
    if not result_file.is_file() or any(not (event_dir / name).is_file() for name in expected):
        return None
    try:
        payload = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("status") not in {"BACKFILL_REHEARSAL_COMPLETED", "BACKFILL_PREVIEW_LINKS_REPAIRED"}:
        return None
    return BackfillResult("BACKFILL_ALREADY_COMPLETE", str(payload.get("event_id")), payload.get("reference_period"), False, False, "free", expected, payload.get("observation_sha256"), bool(payload.get("preview_links_valid")), tuple(payload.get("missing_local_links") or ()))


def run_backfill(root: Path, event_id: str, output_root: Path, *, use_live_bls: bool, now: datetime | None = None, response_fetcher: Callable[[datetime], dict[str, Any]] | None = None) -> BackfillResult:
    root = root.resolve()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output_root = output_root_path(root, str(output_root))
    event = read_calendar_event(root, event_id, current)
    event_dir = output_root / event_id
    if event_dir.exists():
        prior = existing_result(event_dir)
        if prior is not None and response_fetcher is None:
            changed, missing, _count = repair_preview_links(root, event_dir, event_id)
            status = "BACKFILL_PREVIEW_LINKS_REPAIRED" if changed else "BACKFILL_ALREADY_COMPLETE"
            result = BackfillResult(status, prior.event_id, prior.reference_period, False, False, "free", prior.output_files, prior.observation_sha256, True, missing)
            if changed or prior.preview_links_valid is not True:
                write_existing_result(event_dir / "result.json", result)
            return result
        if prior is not None and response_fetcher is not None:
            proposed = build_observation(event, response_fetcher(current), current)
            existing = json.loads((event_dir / "historical_observation.json").read_text(encoding="utf-8"))
            if existing == proposed:
                return prior
            return BackfillResult("BACKFILL_CONFLICT", event_id, event["reference_period"], True, False, "free", (), existing.get("integrity", {}).get("sha256"))
        return BackfillResult("BACKFILL_CONFLICT", event_id, event["reference_period"], False, False, "free", (), None)
    if not use_live_bls and response_fetcher is None:
        raise BackfillError("BACKFILL_LIVE_FLAG_REQUIRED", "--use-live-bls is required for a live rehearsal")
    response = response_fetcher(current) if response_fetcher is not None else fetch_live_response(current)
    observation = build_observation(event, response, current)
    canonical = build_canonical(event, observation)
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / f".{event_id}.{uuid4().hex}.tmp"
    stage.mkdir()
    try:
        workspace = stage / "workspace"
        (workspace / "data").mkdir(parents=True)
        (workspace / "docs").mkdir()
        shutil.copy2(root / "data" / "indicator_profiles.json", workspace / "data" / "indicator_profiles.json")
        shutil.copy2(root / "docs" / "index.html", workspace / "docs" / "index.html")
        canonical_path = workspace / "data" / "generated" / "cpi" / event_id / "canonical_release.json"
        write_new(canonical_path, json_bytes(canonical))
        analysis_result = generate_cpi_analysis.analyze_from_files(workspace, event_id, provider_name="rule_based", now_fn=lambda: current)
        if analysis_result.status != "ANALYSIS_GENERATED" or analysis_result.external_api_called or analysis_result.api_calls != 0:
            raise BackfillError("BACKFILL_CONFLICT", "historical analysis must use rule_based without AI API calls")
        analysis_path = workspace / "data" / "analysis" / "cpi" / event_id / "cpi-analysis-v1.json"
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        analysis["backfill"] = {"data_api_called": True, "ai_api_called": False, "cost": "free", "data_origin": "historical_backfill", "vintage_status": "current_api_snapshot", "not_as_released": True}
        analysis_path.write_bytes(json_bytes(analysis))
        report_result = build_cpi_release_report.build_report(workspace, event_id)
        if report_result.status != "REPORT_CREATED":
            raise BackfillError("BACKFILL_CONFLICT", "historical report was not created")
        report = decorate_report((workspace / "docs" / "reports" / f"{event_id}.html").read_text(encoding="utf-8"))
        report_bytes = report.encode("utf-8")
        index = build_index((workspace / "docs" / "index.html").read_text(encoding="utf-8"), event, hashlib.sha256(report_bytes).hexdigest())
        files = {
            "historical_observation.json": json_bytes(observation),
            "canonical.json": json_bytes(canonical),
            "analysis.json": json_bytes(analysis),
            "report.html": report_bytes,
            "index.html": index.encode("utf-8"),
        }
        for name, data in files.items():
            write_new(stage / name, data)
        _changed, missing, _count = repair_preview_links(root, stage, event_id)
        result = BackfillResult("BACKFILL_REHEARSAL_COMPLETED", event_id, event["reference_period"], True, False, "free", tuple(files) + ("result.json",), observation["integrity"]["sha256"], True, missing)
        write_new(stage / "result.json", json_bytes(result.payload()))
        shutil.rmtree(workspace)
        os.replace(stage, event_dir)
        return result
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated CPI historical backfill rehearsal")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--use-live-bls", action="store_true")
    parser.add_argument("--repair-preview-links", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.repair_preview_links and args.use_live_bls:
            raise BackfillError("BACKFILL_INVALID_OUTPUT_ROOT", "repair mode cannot call BLS")
        result = run_backfill(project_root(), args.event_id, Path(args.output_root), use_live_bls=args.use_live_bls)
    except BackfillError as exc:
        print(exc.code)
        print(f"error: {exc}")
        return 1
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"reference_period: {result.reference_period}")
    print(f"data_api_called: {str(result.data_api_called).lower()}")
    print(f"ai_api_called: {str(result.ai_api_called).lower()}")
    print(f"cost: {result.cost}")
    print(f"observation_sha256: {result.observation_sha256 or 'none'}")
    print(f"preview_links_valid: {str(result.preview_links_valid).lower()}")
    print(f"missing_local_links: {list(result.missing_local_links)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
