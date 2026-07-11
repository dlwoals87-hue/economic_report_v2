from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis import generate_cpi_analysis  # noqa: E402
from scripts.automation import process_cpi_release, run_pending_cpi_processing  # noqa: E402
from scripts.pipelines import capture_cpi_release  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402


EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
REQUIRED_FILES = (
    "scripts/collectors/bls_cpi.py",
    "scripts/pipelines/capture_cpi_release.py",
    "scripts/automation/run_due_cpi_capture.py",
    "scripts/pipelines/build_cpi_release_canonical.py",
    "scripts/analysis/generate_cpi_analysis.py",
    "scripts/providers/rule_based.py",
    "scripts/automation/process_cpi_release.py",
    "scripts/pipelines/build_cpi_release_report.py",
    "scripts/automation/update_report_index.py",
    "scripts/automation/run_pending_cpi_processing.py",
    "data/calendar/events.json",
    "templates/report.html",
    "docs/index.html",
)
PRODUCTION_FILES = (
    "data/calendar/events.json",
    "templates/sample_report_v11.html",
    "templates/report.html",
    "docs/index.html",
    ".github/workflows/capture-cpi-release.yml",
    ".github/workflows/process-cpi-release.yml",
)
PRODUCTION_DIRECTORIES = (
    "data/releases",
    "data/generated",
    "data/analysis",
    "docs/reports",
)


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    event_id: str
    reference_period: str | None
    release_datetime_utc: str | None
    release_datetime_kst: str | None
    calendar: str
    capture_workflow: str
    processing_workflow: str
    free_mode: bool
    external_api_required: bool
    full_offline_dry_run: str
    production_files_modified: bool
    errors: tuple[str, ...]
    offline: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["errors"] = list(self.errors)
        return payload


def project_root() -> Path:
    return PROJECT_ROOT


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, Any]:
    files = {
        value: _sha256_file(root / value) if (root / value).is_file() else None
        for value in PRODUCTION_FILES
    }
    directories: dict[str, tuple[tuple[str, str], ...]] = {}
    for value in PRODUCTION_DIRECTORIES:
        directory = root / value
        entries: list[tuple[str, str]] = []
        if directory.exists():
            for path in sorted(item for item in directory.rglob("*") if item.is_file()):
                entries.append((path.relative_to(root).as_posix(), _sha256_file(path)))
        directories[value] = tuple(entries)
    return {"files": files, "directories": directories}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path.as_posix()}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path.as_posix()}")
    return payload


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _calendar_contract(root: Path, event_id: str) -> tuple[dict[str, Any], str, str]:
    payload = validate_calendar_events.read_json(root / "data" / "calendar" / "events.json")
    events = payload.get("events")
    matches = [
        event for event in events
        if isinstance(event, dict) and event.get("event_id") == event_id
    ] if isinstance(events, list) else []
    if len(matches) != 1:
        raise ValueError("calendar event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise ValueError("calendar event must be US CPI")
    reference_period = event.get("reference_period")
    if not isinstance(reference_period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", reference_period):
        raise ValueError("calendar reference_period is invalid")
    if event_id == "US_CPI_2026_06" and reference_period != "2026-06":
        raise ValueError("calendar reference_period must be 2026-06 for US_CPI_2026_06")
    release_utc = _parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    metrics = event.get("metrics")
    expected_metrics = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
    if not isinstance(metrics, dict) or set(metrics) != set(expected_metrics):
        raise ValueError("calendar expected metrics are invalid")
    for metric in expected_metrics:
        value = metrics[metric]
        if not isinstance(value, dict) or value.get("unit") != "%" or "expected" not in value:
            raise ValueError(f"calendar expected structure is invalid: {metric}")
    if event.get("consensus_status") not in {"not_entered", "partial", "complete"}:
        raise ValueError("calendar consensus_status is invalid")
    validation = validate_calendar_events.validate_events_payload(payload)
    if not validation.valid:
        raise ValueError("calendar validation failed")
    return event, release_utc.isoformat().replace("+00:00", "Z"), release_utc.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def _workflow_contracts(root: Path) -> None:
    capture = (root / ".github" / "workflows" / "capture-cpi-release.yml").read_text(encoding="utf-8")
    processing = (root / ".github" / "workflows" / "process-cpi-release.yml").read_text(encoding="utf-8")
    capture_required = (
        "name: Capture CPI Release",
        "workflow_dispatch:",
        "schedule:",
        'timezone: "America/New_York"',
        "contents: write",
        "concurrency:",
        "scripts/validators/validate_calendar_events.py",
        "scripts/automation/run_due_cpi_capture.py",
        "Validate capture result",
        "status == 'CAPTURED'",
    )
    for value in capture_required:
        if value not in capture:
            raise ValueError(f"capture workflow missing {value}")
    for value in ("git add .", "git add -A", "--force", "PERSONAL_ACCESS_TOKEN", "GH_PAT", "secrets.PAT"):
        if value in capture:
            raise ValueError(f"capture workflow contains forbidden {value}")

    processing_required = (
        "name: Process CPI Release",
        "workflow_run:",
        '"Capture CPI Release"',
        "branches:",
        "- main",
        "github.event.workflow_run.conclusion == 'success'",
        "rule_based",
        "scripts/automation/run_pending_cpi_processing.py",
        "1 <= len(commit_paths) <= 4",
        "git diff --cached --name-only",
        "git diff --cached --name-status",
    )
    for value in processing_required:
        if value not in processing:
            raise ValueError(f"process workflow missing {value}")
    for value in (
        "BLS_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "GITHUB_MODELS",
        "${{ secrets.",
        "git add .",
        "git add -A",
        "--force",
        "PERSONAL_ACCESS_TOKEN",
        "GH_PAT",
        "secrets.PAT",
    ):
        if value in processing:
            raise ValueError(f"process workflow contains forbidden {value}")
    runner = (root / "scripts" / "automation" / "run_pending_cpi_processing.py").read_text(encoding="utf-8")
    sequence = (
        runner.find("processed = process_func"),
        runner.find("rendered = report_func"),
        runner.find("indexed = index_func"),
    )
    if min(sequence) < 0 or sequence != tuple(sorted(sequence)):
        raise ValueError("processing order must be canonical, analysis, HTML, index")


def _required_files_contract(root: Path) -> None:
    missing = [value for value in REQUIRED_FILES if not (root / value).is_file()]
    if missing:
        raise ValueError(f"required file missing: {missing[0]}")
    sample = root / "templates" / "sample_report_v11.html"
    if not sample.is_file() or not _sha256_file(sample):
        raise ValueError("sample_report_v11.html SHA-256 is unavailable")
    report_template = (root / "templates" / "report.html").read_text(encoding="utf-8")
    if not STYLE_RE.search(report_template):
        raise ValueError("report template style block is missing")
    index = (root / "docs" / "index.html").read_text(encoding="utf-8")
    starts = index.count("<!-- AUTO_REAL_REPORTS_START -->")
    ends = index.count("<!-- AUTO_REAL_REPORTS_END -->")
    if (starts, ends) not in {(0, 0), (1, 1)}:
        raise ValueError("index marker structure is invalid")
    if starts == 0 and "</body>" not in index.lower():
        raise ValueError("index marker insertion is not possible")
    if starts == 1 and index.index("<!-- AUTO_REAL_REPORTS_START -->") > index.index("<!-- AUTO_REAL_REPORTS_END -->"):
        raise ValueError("index marker order is invalid")


def _free_mode_contract(root: Path) -> None:
    process_source = (root / "scripts" / "automation" / "process_cpi_release.py").read_text(encoding="utf-8")
    pending_source = (root / "scripts" / "automation" / "run_pending_cpi_processing.py").read_text(encoding="utf-8")
    if 'DEFAULT_PROVIDER = "rule_based"' not in process_source:
        raise ValueError("rule_based is not the process default")
    if 'DEFAULT_PROVIDER = "rule_based"' not in pending_source:
        raise ValueError("rule_based is not the pending-processing default")
    if process_cpi_release.DEFAULT_PROVIDER != "rule_based":
        raise ValueError("rule_based is not the process default")
    if run_pending_cpi_processing.DEFAULT_PROVIDER != "rule_based":
        raise ValueError("rule_based is not the pending-processing default")
    if generate_cpi_analysis.select_provider("rule_based") != "rule_based":
        raise ValueError("rule_based provider is not selectable")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _offline_event() -> dict[str, Any]:
    return {
        "event_id": "US_CPI_2026_06",
        "indicator_type": "CPI",
        "country": "US",
        "reference_period": "2026-06",
        "release_datetime_utc": "2026-07-14T12:30:00Z",
        "metrics": {
            key: {"expected": None, "unit": "%"}
            for key in ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
        },
        "consensus_source": None,
        "consensus_status": "not_entered",
        "entered_at_utc": None,
    }


def _offline_root(root: Path) -> None:
    _write_json(root / "data" / "calendar" / "events.json", {"version": 1, "events": [_offline_event()]})
    _write_json(
        root / "data" / "indicator_profiles.json",
        {"CPI": {"display_name": "US Consumer Price Index", "country": "US"}},
    )
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "index.html").write_text(
        "<!DOCTYPE html>\n<html lang=\"ko\"><head><title>경제지표 리포트</title></head>\n"
        "<body><a href=\"reports/sample-report.html\">sample</a>\n</body></html>\n",
        encoding="utf-8",
    )


def _collector_result(root: Path, reference_period: str) -> dict[str, Any]:
    metrics = {
        "headline_mom": ("0.3", "0.3%", "0.5", "0.5%"),
        "headline_yoy": ("2.9", "2.9%", "3.0", "3.0%"),
        "core_mom": ("0.2", "0.2%", "0.3", "0.3%"),
        "core_yoy": ("3.1", "3.1%", "3.2", "3.2%"),
    }
    return {
        "reference_period": reference_period,
        "raw_snapshot_path": root / "data" / "raw" / "bls" / "cpi" / reference_period / "retrieved.json",
        "processed_path": root / "data" / "processed" / "bls" / "cpi_latest.json",
        "processed_payload": {
            "reference_period": reference_period,
            "retrieved_at_utc": "2026-07-14T12:31:00Z",
            "request_mode": "offline_mock",
            "metrics": {
                name: {
                    "actual_current_raw": actual,
                    "actual_current_display": actual_display,
                    "previous_current_raw": previous,
                    "previous_current_display": previous_display,
                }
                for name, (actual, actual_display, previous, previous_display) in metrics.items()
            },
        },
        "fetch_result": SimpleNamespace(request_count=0),
    }


def _fresh_offline_capture(root: Path) -> tuple[Any, Any, datetime]:
    _offline_root(root)
    release_dt = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
    capture = capture_cpi_release.capture_release(
        root,
        "US_CPI_2026_06",
        now_utc=release_dt + timedelta(minutes=1),
        collector=lambda temp_root, _now: _collector_result(temp_root, "2026-06"),
    )
    pending, code = run_pending_cpi_processing.run_pending_processing(
        root,
        event_id="US_CPI_2026_06",
        now=release_dt + timedelta(minutes=2),
    )
    return capture, pending, release_dt


def run_offline_dry_run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="cpi-readiness-") as temp:
        root = Path(temp)
        _offline_root(root)
        release_dt = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
        waiting = capture_cpi_release.capture_release(
            root,
            "US_CPI_2026_06",
            now_utc=release_dt - timedelta(minutes=1),
            collector=lambda *_args: (_ for _ in ()).throw(AssertionError("collector must not run")),
        )
        stale = capture_cpi_release.capture_release(
            root,
            "US_CPI_2026_06",
            now_utc=release_dt + timedelta(minutes=1),
            collector=lambda temp_root, _now: _collector_result(temp_root, "2026-05"),
        )
        capture = capture_cpi_release.capture_release(
            root,
            "US_CPI_2026_06",
            now_utc=release_dt + timedelta(minutes=2),
            collector=lambda temp_root, _now: _collector_result(temp_root, "2026-06"),
        )
        pending, pending_code = run_pending_cpi_processing.run_pending_processing(
            root,
            event_id="US_CPI_2026_06",
            now=release_dt + timedelta(minutes=3),
        )
        derived = {
            "canonical": (root / "data" / "generated" / "cpi" / "US_CPI_2026_06" / "canonical_release.json").is_file(),
            "analysis": (root / "data" / "analysis" / "cpi" / "US_CPI_2026_06" / "cpi-analysis-v1.json").is_file(),
            "report": (root / "docs" / "reports" / "US_CPI_2026_06.html").is_file(),
            "index": "reports/US_CPI_2026_06.html" in (root / "docs" / "index.html").read_text(encoding="utf-8"),
        }
        captured = (
            capture.status == "CAPTURED"
            and capture.api_call_count == 0
            and capture.as_released_path is not None
            and (root / capture.as_released_path).is_file()
        )
        tracked = (
            root / "data" / "releases" / "cpi" / "US_CPI_2026_06" / "as_released.json",
            root / "data" / "generated" / "cpi" / "US_CPI_2026_06" / "canonical_release.json",
            root / "data" / "analysis" / "cpi" / "US_CPI_2026_06" / "cpi-analysis-v1.json",
            root / "docs" / "reports" / "US_CPI_2026_06.html",
            root / "docs" / "index.html",
        )
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in tracked]
        recapture = capture_cpi_release.capture_release(
            root,
            "US_CPI_2026_06",
            now_utc=release_dt + timedelta(minutes=4),
            collector=lambda *_args: (_ for _ in ()).throw(AssertionError("collector must not run")),
        )
        rerun, rerun_code = run_pending_cpi_processing.run_pending_processing(
            root,
            event_id="US_CPI_2026_06",
            now=release_dt + timedelta(minutes=5),
        )
        immutable = before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in tracked]

    def tamper_release() -> bool:
        with tempfile.TemporaryDirectory(prefix="cpi-readiness-tamper-") as temp:
            root = Path(temp)
            capture, _pending, release_dt = _fresh_offline_capture(root)
            del capture
            release = root / "data" / "releases" / "cpi" / "US_CPI_2026_06" / "as_released.json"
            payload = _read_json(release)
            payload["integrity"]["sha256"] = "0" * 64
            _write_json(release, payload)
            result, _ = run_pending_cpi_processing.run_pending_processing(root, event_id="US_CPI_2026_06", now=release_dt)
            return result.status == "INTEGRITY_CHECK_FAILED" and not result.commit_paths

    def tamper_canonical() -> bool:
        with tempfile.TemporaryDirectory(prefix="cpi-readiness-tamper-") as temp:
            root = Path(temp)
            _capture, _pending, release_dt = _fresh_offline_capture(root)
            canonical = root / "data" / "generated" / "cpi" / "US_CPI_2026_06" / "canonical_release.json"
            payload = _read_json(canonical)
            payload["source"]["release_capture_sha256"] = "f" * 64
            _write_json(canonical, payload)
            result, _ = run_pending_cpi_processing.run_pending_processing(root, event_id="US_CPI_2026_06", now=release_dt)
            return result.status == "INTEGRITY_CHECK_FAILED" and not result.commit_paths

    def tamper_report() -> bool:
        with tempfile.TemporaryDirectory(prefix="cpi-readiness-tamper-") as temp:
            root = Path(temp)
            _capture, _pending, release_dt = _fresh_offline_capture(root)
            report = root / "docs" / "reports" / "US_CPI_2026_06.html"
            report.write_text(report.read_text(encoding="utf-8").replace("0.3%", "9.9%", 1), encoding="utf-8")
            before_report = report.read_bytes()
            result, _ = run_pending_cpi_processing.run_pending_processing(root, event_id="US_CPI_2026_06", now=release_dt)
            return (
                result.status == "INTEGRITY_CHECK_FAILED"
                and not result.commit_paths
                and report.read_bytes() == before_report
            )

    checks = {
        "waiting": (
            waiting.status == "WAITING_FOR_RELEASE"
            and waiting.api_call_count == 0
            and waiting.as_released_path is None
        ),
        "stale": stale.status == "DATA_NOT_AVAILABLE_YET" and stale.as_released_path is None,
        "capture": captured,
        "processing": (
            pending.status == "PROCESSED_AND_INDEXED"
            and pending_code == 0
            and pending.provider == "rule_based"
            and not pending.external_api_called
            and pending.cost_mode == "free"
            and 1 <= len(pending.commit_paths) <= 4
        ),
        **derived,
        "rerun": (
            recapture.status == "ALREADY_CAPTURED"
            and rerun.status in {"ALREADY_PROCESSED", "INDEX_ALREADY_UP_TO_DATE"}
            and rerun_code == 0
            and not rerun.commit_paths
            and immutable
        ),
        "tamper_release": tamper_release(),
        "tamper_canonical": tamper_canonical(),
        "tamper_report": tamper_report(),
    }
    checks["passed"] = all(checks.values())
    return checks


def check_readiness(root: Path, event_id: str) -> ReadinessResult:
    root = root.resolve()
    errors: list[str] = []
    reference_period: str | None = None
    release_utc: str | None = None
    release_kst: str | None = None
    calendar_state = "invalid"
    capture_state = "invalid"
    processing_state = "invalid"
    offline: dict[str, Any] = {}
    before = _snapshot(root)
    try:
        if EVENT_ID_RE.fullmatch(event_id) is None:
            raise ValueError("event_id is invalid")
        event, release_utc, release_kst = _calendar_contract(root, event_id)
        reference_period = str(event["reference_period"])
        calendar_state = "valid"
    except (ValueError, OSError) as exc:
        errors.append(str(exc))
    try:
        _workflow_contracts(root)
        capture_state = "ready"
        processing_state = "ready"
    except (ValueError, OSError) as exc:
        errors.append(str(exc))
    try:
        _required_files_contract(root)
    except (ValueError, OSError) as exc:
        errors.append(str(exc))
    try:
        _free_mode_contract(root)
    except ValueError as exc:
        errors.append(str(exc))
    if not errors:
        try:
            offline = run_offline_dry_run()
            if not offline.get("passed"):
                errors.append("full offline dry run failed")
        except Exception as exc:  # Diagnostics must report failures without mutating production.
            errors.append(f"full offline dry run failed: {type(exc).__name__}")
    after = _snapshot(root)
    modified = before != after
    if modified:
        errors.append("production file modified during diagnostics")
    return ReadinessResult(
        status="READINESS_PASS" if not errors else "READINESS_FAIL",
        event_id=event_id,
        reference_period=reference_period,
        release_datetime_utc=release_utc,
        release_datetime_kst=release_kst,
        calendar=calendar_state,
        capture_workflow=capture_state,
        processing_workflow=processing_state,
        free_mode=not any("rule_based" in error for error in errors),
        external_api_required=False,
        full_offline_dry_run="passed" if offline.get("passed") else "failed",
        production_files_modified=modified,
        errors=tuple(errors),
        offline=offline,
    )


def print_result(result: ReadinessResult) -> None:
    print(result.status)
    print(f"event_id: {result.event_id}")
    if result.status == "READINESS_FAIL":
        for error in result.errors:
            print(f"- {error}")
        return
    print(f"reference_period: {result.reference_period}")
    print(f"release_datetime_utc: {result.release_datetime_utc}")
    print(f"release_datetime_kst: {result.release_datetime_kst}")
    print(f"capture_workflow: {result.capture_workflow}")
    print(f"processing_workflow: {result.processing_workflow}")
    print(f"calendar: {result.calendar}")
    print(f"free_mode: {str(result.free_mode).lower()}")
    print(f"external_api_required: {str(result.external_api_required).lower()}")
    print(f"full_offline_dry_run: {result.full_offline_dry_run}")
    print(f"production_files_modified: {str(result.production_files_modified).lower()}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only CPI release-day readiness diagnostic")
    parser.add_argument("--event-id", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = check_readiness(project_root(), args.event_id)
    print_result(result)
    return 0 if result.status == "READINESS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
