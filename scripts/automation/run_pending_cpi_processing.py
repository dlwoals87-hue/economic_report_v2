from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.automation import process_cpi_release  # noqa: E402
from scripts.pipelines import build_cpi_release_canonical  # noqa: E402
from scripts.pipelines import build_cpi_release_report  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402


RESULT_SCHEMA_VERSION = "1.0"
DEFAULT_PROVIDER = "rule_based"
MAX_COMMIT_PATHS = 3
ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
SUCCESS_STATUSES = {
    "NO_PENDING_EVENT",
    "PROCESSED",
    "CANONICAL_ONLY_RESUMED",
    "REPORT_ONLY_RESUMED",
    "ALREADY_PROCESSED",
}
COMMIT_STATUSES = {
    "PROCESSED",
    "CANONICAL_ONLY_RESUMED",
    "REPORT_ONLY_RESUMED",
}
EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
SECRET_VALUE_RE = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
)


class PendingProcessingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PendingProcessingResult:
    status: str
    event_id: str | None
    reference_period: str | None
    provider: str
    external_api_called: bool
    cost_mode: str
    canonical: dict[str, Any]
    analysis: dict[str, Any]
    report: dict[str, Any]
    usage: dict[str, int]
    created_paths: tuple[str, ...]
    commit_paths: tuple[str, ...]
    pending_event_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = RESULT_SCHEMA_VERSION
        payload["created_paths"] = list(self.created_paths)
        payload["commit_paths"] = list(self.commit_paths)
        payload["pending_event_ids"] = list(self.pending_event_ids)
        return {"schema_version": payload.pop("schema_version"), **payload}


def project_root() -> Path:
    return PROJECT_ROOT


def release_path(root: Path, event_id: str) -> Path:
    return root / "data" / "releases" / "cpi" / event_id / "as_released.json"


def canonical_path(root: Path, event_id: str) -> Path:
    return root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"


def analysis_path(root: Path, event_id: str) -> Path:
    return root / "data" / "analysis" / "cpi" / event_id / "cpi-analysis-v1.json"


def report_path(root: Path, event_id: str) -> Path:
    return root / "docs" / "reports" / f"{event_id}.html"


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _empty_artifact() -> dict[str, Any]:
    return {"status": None, "path": None, "sha256": None}


def _artifact(status: str, path: Path, root: Path) -> dict[str, Any]:
    if not path.exists() or path.is_symlink():
        return {
            "status": status,
            "path": path.relative_to(root).as_posix(),
            "sha256": None,
        }
    return {
        "status": status,
        "path": relative_path(path, root),
        "sha256": sha256_file(path),
    }


def _result(
    status: str,
    *,
    event: dict[str, Any] | None = None,
    canonical: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    created_paths: list[str] | tuple[str, ...] = (),
    commit_paths: list[str] | tuple[str, ...] = (),
    pending_event_ids: list[str] | tuple[str, ...] = (),
) -> PendingProcessingResult:
    event_id = event.get("event_id") if isinstance(event, dict) else None
    reference_period = event.get("reference_period") if isinstance(event, dict) else None
    return PendingProcessingResult(
        status=status,
        event_id=event_id if isinstance(event_id, str) else None,
        reference_period=reference_period if isinstance(reference_period, str) else None,
        provider=DEFAULT_PROVIDER,
        external_api_called=False,
        cost_mode="free",
        canonical=canonical or _empty_artifact(),
        analysis=analysis or _empty_artifact(),
        report=report or _empty_artifact(),
        usage=dict(ZERO_USAGE),
        created_paths=tuple(created_paths),
        commit_paths=tuple(commit_paths),
        pending_event_ids=tuple(pending_event_ids),
    )


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PendingProcessingError(code, f"invalid JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PendingProcessingError(code, f"JSON root must be an object: {path.name}")
    return payload


def _load_calendar(root: Path, now: datetime | None) -> list[dict[str, Any]]:
    calendar_path = root / "data" / "calendar" / "events.json"
    try:
        payload = validate_calendar_events.read_json(calendar_path)
        validation = validate_calendar_events.validate_events_payload(payload, now=now)
    except ValueError as exc:
        raise PendingProcessingError("CALENDAR_INVALID", "calendar is unreadable") from exc
    if not validation.valid:
        raise PendingProcessingError("CALENDAR_INVALID", "calendar validation failed")
    events = payload.get("events")
    if not isinstance(events, list):
        raise PendingProcessingError("CALENDAR_INVALID", "calendar events must be a list")

    cpi_events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or event.get("indicator_type") != "CPI":
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or EVENT_ID_RE.fullmatch(event_id) is None:
            raise PendingProcessingError("CALENDAR_INVALID", "CPI event_id is invalid")
        if event_id in seen:
            raise PendingProcessingError("CALENDAR_INVALID", "duplicate CPI event_id")
        seen.add(event_id)
        cpi_events.append(event)
    return cpi_events


def _validate_release(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    event_id = str(event["event_id"])
    path = release_path(root, event_id)
    if path.is_symlink():
        raise PendingProcessingError("INTEGRITY_CHECK_FAILED", "as_released must not be a symlink")
    release = _read_json(path, "INTEGRITY_CHECK_FAILED")
    try:
        build_cpi_release_canonical.validate_release_payload(release, event)
    except build_cpi_release_canonical.ReleaseCanonicalError as exc:
        raise PendingProcessingError("INTEGRITY_CHECK_FAILED", "as_released validation failed") from exc
    return release


def _paths_for_event(root: Path, event_id: str) -> dict[str, Path]:
    return {
        "canonical": canonical_path(root, event_id),
        "analysis": analysis_path(root, event_id),
        "report": report_path(root, event_id),
    }


def _presence(paths: dict[str, Path]) -> dict[str, bool]:
    return {name: path.exists() for name, path in paths.items()}


def _is_inconsistent(presence: dict[str, bool]) -> bool:
    if presence["analysis"] and not presence["canonical"]:
        return True
    return presence["report"] and not (presence["canonical"] and presence["analysis"])


def _validate_completed_event(
    root: Path,
    event: dict[str, Any],
    *,
    now: datetime | None,
    process_func: Callable[..., Any],
    report_func: Callable[..., Any],
) -> bool:
    event_id = str(event["event_id"])
    try:
        _validate_release(root, event)
        processed = process_func(root, event_id, provider="rule_based", now=now)
        if (
            processed.status != "ALREADY_PROCESSED"
            or processed.external_api_called
            or processed.usage != ZERO_USAGE
            or processed.commit_paths
        ):
            return False
        rendered = report_func(root, event_id)
        return rendered.status == "ALREADY_UP_TO_DATE" and not rendered.html_created
    except (
        PendingProcessingError,
        process_cpi_release.ProcessCpiError,
        build_cpi_release_report.CpiReportError,
        OSError,
        ValueError,
    ):
        return False


def _created_paths(
    root: Path,
    event_id: str,
    before: dict[str, bool],
) -> list[str]:
    paths = _paths_for_event(root, event_id)
    return [
        relative_path(path, root)
        for name, path in paths.items()
        if not before[name] and path.exists()
    ]


def _artifacts(
    root: Path,
    event_id: str,
    before: dict[str, bool],
    *,
    invalid: str | None = None,
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for name, path in _paths_for_event(root, event_id).items():
        if not path.exists():
            values[name] = _empty_artifact()
            continue
        if invalid == name:
            status = "invalid"
        else:
            status = "existing" if before[name] else "created"
        values[name] = _artifact(status, path, root)
    return values


def _allowed_paths(event_id: str) -> set[str]:
    return {
        f"data/generated/cpi/{event_id}/canonical_release.json",
        f"data/analysis/cpi/{event_id}/cpi-analysis-v1.json",
        f"docs/reports/{event_id}.html",
    }


def validate_commit_paths(
    root: Path,
    event_id: str,
    paths: list[str] | tuple[str, ...],
    *,
    newly_created: set[str] | None = None,
) -> None:
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise PendingProcessingError("INVALID_COMMIT_PATH", "event_id is invalid")
    if len(paths) > MAX_COMMIT_PATHS:
        raise PendingProcessingError("INVALID_COMMIT_PATH", "commit_paths may contain at most three paths")
    if len(paths) != len(set(paths)):
        raise PendingProcessingError("INVALID_COMMIT_PATH", "duplicate commit paths are not allowed")
    allowed = _allowed_paths(event_id)
    for value in paths:
        if not isinstance(value, str) or not value or "\\" in value:
            raise PendingProcessingError("INVALID_COMMIT_PATH", "commit path must be POSIX relative")
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise PendingProcessingError("INVALID_COMMIT_PATH", "commit path must stay inside the project")
        if value not in allowed:
            raise PendingProcessingError("INVALID_COMMIT_PATH", "commit path is not an allowed derivative")
        if newly_created is not None and value not in newly_created:
            raise PendingProcessingError("INVALID_COMMIT_PATH", "only newly created files may be committed")
        full_path = root.joinpath(*pure.parts)
        if full_path.is_symlink():
            raise PendingProcessingError("INVALID_COMMIT_PATH", "symlink commit path is forbidden")
        resolved = full_path.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise PendingProcessingError("INVALID_COMMIT_PATH", "commit path escapes the project") from exc
        if not resolved.is_file():
            raise PendingProcessingError("INVALID_COMMIT_PATH", "commit path must be an existing file")
        if SECRET_VALUE_RE.search(resolved.read_bytes()):
            raise PendingProcessingError("INVALID_COMMIT_PATH", "credential-like value found in derivative")


def _failure_result(
    status: str,
    *,
    root: Path,
    event: dict[str, Any],
    before: dict[str, bool],
    invalid: str | None = None,
) -> PendingProcessingResult:
    event_id = str(event["event_id"])
    created = _created_paths(root, event_id, before)
    artifacts = _artifacts(root, event_id, before, invalid=invalid)
    return _result(
        status,
        event=event,
        canonical=artifacts["canonical"],
        analysis=artifacts["analysis"],
        report=artifacts["report"],
        created_paths=created,
        commit_paths=(),
    )


def _process_event(
    root: Path,
    event: dict[str, Any],
    *,
    now: datetime | None,
    process_func: Callable[..., Any],
    report_func: Callable[..., Any],
) -> PendingProcessingResult:
    event_id = str(event["event_id"])
    paths = _paths_for_event(root, event_id)
    before = _presence(paths)
    if _is_inconsistent(before):
        return _failure_result(
            "INCONSISTENT_DERIVED_STATE",
            root=root,
            event=event,
            before=before,
        )
    try:
        _validate_release(root, event)
    except PendingProcessingError:
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
        )

    try:
        processed = process_func(root, event_id, provider="rule_based", now=now)
    except (process_cpi_release.ProcessCpiError, OSError, ValueError):
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
        )
    if processed.status not in {"PROCESSED", "CANONICAL_ONLY_RESUMED", "ALREADY_PROCESSED"}:
        status = (
            "INCONSISTENT_DERIVED_STATE"
            if processed.status == "INCONSISTENT_DERIVED_STATE"
            else "INTEGRITY_CHECK_FAILED"
            if before["canonical"] or before["analysis"]
            else processed.status
        )
        return _failure_result(status, root=root, event=event, before=before)
    if (
        processed.provider != DEFAULT_PROVIDER
        or processed.external_api_called
        or processed.usage != ZERO_USAGE
    ):
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
            invalid="analysis",
        )
    if not paths["canonical"].is_file() or not paths["analysis"].is_file():
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
        )
    if paths["canonical"].is_symlink() or paths["analysis"].is_symlink():
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
        )

    try:
        rendered = report_func(root, event_id)
    except (build_cpi_release_report.CpiReportError, OSError, ValueError):
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
            invalid="report" if before["report"] else None,
        )
    expected_report_status = "ALREADY_UP_TO_DATE" if before["report"] else "REPORT_CREATED"
    if rendered.status != expected_report_status:
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
            invalid="report",
        )
    if not paths["report"].is_file() or paths["report"].is_symlink():
        return _failure_result(
            "INTEGRITY_CHECK_FAILED",
            root=root,
            event=event,
            before=before,
            invalid="report",
        )

    if before == {"canonical": False, "analysis": False, "report": False}:
        status = "PROCESSED"
    elif before == {"canonical": True, "analysis": False, "report": False}:
        status = "CANONICAL_ONLY_RESUMED"
    elif before == {"canonical": True, "analysis": True, "report": False}:
        status = "REPORT_ONLY_RESUMED"
    elif before == {"canonical": True, "analysis": True, "report": True}:
        status = "ALREADY_PROCESSED"
    else:
        return _failure_result(
            "INCONSISTENT_DERIVED_STATE",
            root=root,
            event=event,
            before=before,
        )

    created = _created_paths(root, event_id, before)
    commit = created if status in COMMIT_STATUSES else []
    try:
        validate_commit_paths(root, event_id, commit, newly_created=set(created))
    except PendingProcessingError:
        return _failure_result(
            "INVALID_COMMIT_PATH",
            root=root,
            event=event,
            before=before,
        )
    artifacts = _artifacts(root, event_id, before)
    return _result(
        status,
        event=event,
        canonical=artifacts["canonical"],
        analysis=artifacts["analysis"],
        report=artifacts["report"],
        created_paths=created,
        commit_paths=commit,
    )


def resolve_result_path(root: Path, value: str | Path) -> Path:
    requested = Path(value)
    if not requested.is_absolute():
        if ".." in requested.parts:
            raise PendingProcessingError("INVALID_RESULT_PATH", "relative result path cannot use ..")
        requested = root / requested
    resolved = requested.resolve(strict=False)
    if resolved.exists() and resolved.is_symlink():
        raise PendingProcessingError("INVALID_RESULT_PATH", "result JSON must not be a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    if relative.parts and relative.parts[0] in {
        ".github",
        "data",
        "docs",
        "prompts",
        "schemas",
        "scripts",
        "templates",
        "tests",
    }:
        raise PendingProcessingError("INVALID_RESULT_PATH", "result JSON cannot replace a project artifact")
    return resolved


def write_result_json(path: Path, result: PendingProcessingResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(result.to_payload(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run_pending_processing(
    root: Path,
    *,
    event_id: str | None = None,
    result_json: str | Path | None = None,
    now: datetime | None = None,
    process_func: Callable[..., Any] | None = None,
    report_func: Callable[..., Any] | None = None,
) -> tuple[PendingProcessingResult, int]:
    root = root.resolve()
    process = process_func or process_cpi_release.process_release
    render = report_func or build_cpi_release_report.build_report
    result_path = resolve_result_path(root, result_json) if result_json is not None else None
    try:
        events = _load_calendar(root, now)
        if event_id is not None:
            if EVENT_ID_RE.fullmatch(event_id) is None:
                raise PendingProcessingError("CALENDAR_INVALID", "manual event_id is invalid")
            matches = [event for event in events if event.get("event_id") == event_id]
            if len(matches) != 1:
                raise PendingProcessingError("CALENDAR_INVALID", "manual event_id is not in the calendar")
            event = matches[0]
            if not release_path(root, event_id).exists():
                result = _result("NO_PENDING_EVENT")
            else:
                result = _process_event(
                    root,
                    event,
                    now=now,
                    process_func=process,
                    report_func=render,
                )
        else:
            pending: list[dict[str, Any]] = []
            for event in events:
                candidate_id = str(event["event_id"])
                if not release_path(root, candidate_id).exists():
                    continue
                paths = _paths_for_event(root, candidate_id)
                presence = _presence(paths)
                if not all(presence.values()) or _is_inconsistent(presence):
                    pending.append(event)
                    continue
                if not _validate_completed_event(
                    root,
                    event,
                    now=now,
                    process_func=process,
                    report_func=render,
                ):
                    pending.append(event)
            if not pending:
                result = _result("NO_PENDING_EVENT")
            elif len(pending) > 1:
                result = _result(
                    "MULTIPLE_PENDING_EVENTS",
                    pending_event_ids=[str(event["event_id"]) for event in pending],
                )
            else:
                result = _process_event(
                    root,
                    pending[0],
                    now=now,
                    process_func=process,
                    report_func=render,
                )
    except PendingProcessingError as exc:
        result = _result(exc.code)

    if result_path is not None:
        write_result_json(result_path, result)
    return result, 0 if result.status in SUCCESS_STATUSES else 1


def print_summary(result: PendingProcessingResult) -> None:
    print(result.status)
    if result.status == "MULTIPLE_PENDING_EVENTS":
        for event_id in result.pending_event_ids:
            print(event_id)
        return
    print(f"event_id: {result.event_id or 'none'}")
    print(f"reference_period: {result.reference_period or 'none'}")
    print(f"provider: {result.provider}")
    print(f"external_api_called: {str(result.external_api_called).lower()}")
    print(f"cost_mode: {result.cost_mode}")
    print(f"created_paths: {len(result.created_paths)}")
    print(f"commit_paths: {len(result.commit_paths)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process one pending CPI release for free")
    parser.add_argument("--event-id")
    parser.add_argument("--result-json", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result, exit_code = run_pending_processing(
            project_root(),
            event_id=args.event_id or None,
            result_json=args.result_json,
        )
    except PendingProcessingError as exc:
        print(exc.code)
        print(f"error: {exc.message}")
        print("external_api_called: false")
        return 1
    print_summary(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
