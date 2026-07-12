from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis import generate_cpi_analysis  # noqa: E402
from scripts.pipelines import build_cpi_release_report  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402


RESULT_SCHEMA_VERSION = "1.0"
START_MARKER = "<!-- AUTO_REAL_REPORTS_START -->"
END_MARKER = "<!-- AUTO_REAL_REPORTS_END -->"
EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
ARTICLE_RE = re.compile(
    r'<article class="auto-real-report"(?P<attrs>[^>]*)>(?P<body>.*?)</article>',
    re.DOTALL,
)
ATTR_RE = re.compile(r'\s([a-z0-9_-]+)="([^"]*)"')
SHA_COMMENT_RE = re.compile(r"<!-- report-sha256: ([0-9a-f]{64}) -->")
UNSAFE_SEGMENT_RE = re.compile(r"<\s*(script|iframe|object|embed)\b", re.IGNORECASE)
EVENT_HANDLER_RE = re.compile(r"<[^>]+\s+on[a-z0-9_-]+\s*=", re.IGNORECASE)
JAVASCRIPT_URL_RE = re.compile(r"(?:href|src)\s*=\s*['\"]\s*javascript:", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


class ReportIndexError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ReportEntry:
    event_id: str
    indicator_name: str
    reference_period: str
    release_datetime_kst: str
    report_href: str
    report_sha256: str


@dataclass(frozen=True)
class IndexUpdateResult:
    status: str
    event_id: str | None
    reference_period: str | None
    report: dict[str, Any]
    index: dict[str, Any]
    index_changed: bool
    report_sha256: str | None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = RESULT_SCHEMA_VERSION
        return {"schema_version": payload.pop("schema_version"), **payload}


def project_root() -> Path:
    return PROJECT_ROOT


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _empty_artifact() -> dict[str, Any]:
    return {"status": None, "path": None, "sha256": None}


def _artifact(status: str, path: Path, root: Path) -> dict[str, Any]:
    if not path.exists() or path.is_symlink():
        return {"status": status, "path": path.relative_to(root).as_posix(), "sha256": None}
    return {
        "status": status,
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": _sha256_file(path),
    }


def _result(
    status: str,
    *,
    event_id: str | None = None,
    reference_period: str | None = None,
    report: dict[str, Any] | None = None,
    index: dict[str, Any] | None = None,
    index_changed: bool = False,
    report_sha256: str | None = None,
) -> IndexUpdateResult:
    return IndexUpdateResult(
        status=status,
        event_id=event_id,
        reference_period=reference_period,
        report=report or _empty_artifact(),
        index=index or _empty_artifact(),
        index_changed=index_changed,
        report_sha256=report_sha256,
    )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", f"{label} must be a JSON object")
    return payload


def _resolve_project_file(
    root: Path,
    value: str | None,
    default: Path,
    expected: Path,
    label: str,
) -> Path:
    candidate = default if value is None else Path(value)
    if ".." in PurePath(candidate).parts:
        raise ReportIndexError("INVALID_PATH", f"{label} cannot contain parent traversal")
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ReportIndexError("INVALID_PATH", f"{label} must stay inside the project") from exc
    if resolved != expected.resolve(strict=False):
        raise ReportIndexError("INVALID_PATH", f"{label} is not the expected event path")
    return resolved


def _resolve_result_path(root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise ReportIndexError("INVALID_PATH", "result path cannot contain parent traversal")
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved.exists() and resolved.is_symlink():
        raise ReportIndexError("INVALID_PATH", "result path cannot be a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    if relative.parts and relative.parts[0] in {"data", "docs", "scripts", "templates", ".github", "tests"}:
        raise ReportIndexError("INVALID_PATH", "result path cannot replace a project artifact")
    return resolved


def _calendar_event(root: Path, event_id: str) -> dict[str, Any]:
    try:
        payload = validate_calendar_events.read_json(root / "data" / "calendar" / "events.json")
        validation = validate_calendar_events.validate_events_payload(payload)
    except ValueError as exc:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "calendar is unreadable") from exc
    if not validation.valid:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "calendar validation failed")
    events = payload.get("events")
    matches = [
        event
        for event in events
        if isinstance(event, dict) and event.get("event_id") == event_id
    ] if isinstance(events, list) else []
    if len(matches) != 1 or matches[0].get("indicator_type") != "CPI":
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "calendar CPI event is not unique")
    return matches[0]


def _parse_release_kst(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "release_datetime_kst is invalid") from exc
    if parsed.tzinfo is None:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "release_datetime_kst has no timezone")
    return parsed


def _display_release_kst(value: str) -> str:
    parsed = _parse_release_kst(value)
    return parsed.strftime("%Y-%m-%d %H:%M KST")


def _display_reference_period(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", value)
    if match is None:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "reference_period is invalid")
    return f"{match.group(1)}년 {int(match.group(2))}월"


def _validate_report_entry(
    *,
    root: Path,
    event_id: str,
    report_file: Path,
    canonical_file: Path,
) -> ReportEntry:
    if report_file.is_symlink():
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "report must not be a symlink")
    if report_file.suffix.lower() != ".html" or not report_file.is_file():
        raise ReportIndexError("REPORT_NOT_FOUND", "report HTML is not available")
    if canonical_file.is_symlink() or not canonical_file.is_file():
        raise ReportIndexError("CANONICAL_RELEASE_NOT_FOUND", "canonical release is not available")
    canonical = _read_json(canonical_file, "canonical release")
    try:
        generate_cpi_analysis.validate_canonical_release(canonical, event_id)
    except generate_cpi_analysis.CpiAnalysisError as exc:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "canonical release validation failed") from exc
    meta = canonical.get("meta")
    if not isinstance(meta, dict) or meta.get("event_id") != event_id:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "canonical event_id does not match")
    indicator_name = meta.get("indicator_name")
    reference_period = meta.get("reference_period")
    release_kst = meta.get("release_datetime_kst")
    if not all(isinstance(value, str) and value.strip() for value in (indicator_name, reference_period, release_kst)):
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "canonical display metadata is missing")
    _display_reference_period(reference_period)
    _parse_release_kst(release_kst)

    report_relative = report_file.resolve().relative_to(root.resolve()).as_posix()
    canonical_relative = canonical_file.resolve().relative_to(root.resolve()).as_posix()
    try:
        rendered = build_cpi_release_report.build_report(
            root,
            event_id,
            canonical=canonical_relative,
            output=report_relative,
        )
    except build_cpi_release_report.CpiReportError as exc:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "report validation failed") from exc
    if rendered.status != "ALREADY_UP_TO_DATE" or rendered.html_created:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "report is not immutable and current")

    report_text = report_file.read_text(encoding="utf-8")
    if event_id not in report_text or reference_period not in report_text:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "report identity is not visible")
    report_sha = _sha256_file(report_file)
    if rendered.report_sha256 != report_sha:
        raise ReportIndexError("REPORT_INTEGRITY_FAILED", "report SHA-256 does not match renderer")
    return ReportEntry(
        event_id=event_id,
        indicator_name=indicator_name,
        reference_period=reference_period,
        release_datetime_kst=release_kst,
        report_href=f"reports/{event_id}.html",
        report_sha256=report_sha,
    )


def _marker_bounds(index_text: str) -> tuple[str, str, str]:
    start_count = index_text.count(START_MARKER)
    end_count = index_text.count(END_MARKER)
    if start_count == 0 and end_count == 0:
        body_end = index_text.lower().find("</body>")
        if body_end < 0:
            raise ReportIndexError("INDEX_UPDATE_FAILED", "index body closing tag is missing")
        return index_text[:body_end], "", index_text[body_end:]
    if start_count != 1 or end_count != 1:
        raise ReportIndexError("INDEX_UPDATE_FAILED", "index markers must appear exactly once")
    start = index_text.index(START_MARKER)
    end = index_text.index(END_MARKER, start)
    if end < start:
        raise ReportIndexError("INDEX_UPDATE_FAILED", "index marker order is invalid")
    return index_text[:start], index_text[start + len(START_MARKER):end], index_text[end + len(END_MARKER):]


def _parse_entries(managed: str) -> list[ReportEntry]:
    if UNSAFE_SEGMENT_RE.search(managed) or EVENT_HANDLER_RE.search(managed) or JAVASCRIPT_URL_RE.search(managed):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "managed index region contains unsafe HTML")
    entries: list[ReportEntry] = []
    for match in ARTICLE_RE.finditer(managed):
        attrs = {key: html.unescape(value) for key, value in ATTR_RE.findall(match.group("attrs"))}
        required = {
            "data-event-id",
            "data-indicator-name",
            "data-reference-period",
            "data-release-kst",
            "data-report-href",
        }
        if set(attrs) != required:
            raise ReportIndexError("INDEX_UPDATE_FAILED", "managed report entry attributes are invalid")
        report_sha_match = SHA_COMMENT_RE.search(match.group("body"))
        if report_sha_match is None:
            raise ReportIndexError("INDEX_UPDATE_FAILED", "managed report entry SHA-256 is missing")
        entry = ReportEntry(
            event_id=attrs["data-event-id"],
            indicator_name=attrs["data-indicator-name"],
            reference_period=attrs["data-reference-period"],
            release_datetime_kst=attrs["data-release-kst"],
            report_href=attrs["data-report-href"],
            report_sha256=report_sha_match.group(1),
        )
        _validate_entry_shape(entry)
        entries.append(entry)
    if len(entries) != len({entry.event_id for entry in entries}):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "duplicate event_id in managed index region")
    return entries


def _validate_entry_shape(entry: ReportEntry) -> None:
    if EVENT_ID_RE.fullmatch(entry.event_id) is None:
        raise ReportIndexError("INDEX_UPDATE_FAILED", "managed event_id is invalid")
    expected_hrefs = {f"reports/{entry.event_id}.html"}
    if entry.event_id.startswith("US_PPI_"):
        expected_hrefs.add(f"reports/ppi/{entry.event_id}.html")
    if entry.report_href not in expected_hrefs:
        raise ReportIndexError("INDEX_UPDATE_FAILED", "managed report href is invalid")
    if SHA256_RE.fullmatch(entry.report_sha256) is None:
        raise ReportIndexError("INDEX_UPDATE_FAILED", "managed report SHA-256 is invalid")
    if not entry.indicator_name.strip():
        raise ReportIndexError("INDEX_UPDATE_FAILED", "managed indicator_name is empty")
    _display_reference_period(entry.reference_period)
    _parse_release_kst(entry.release_datetime_kst)


def _escape_attribute(value: str) -> str:
    return html.escape(value, quote=True).replace("=", "&#61;")


def _render_entry(entry: ReportEntry) -> str:
    title = f"{entry.indicator_name} — {_display_reference_period(entry.reference_period)}"
    return "\n".join(
        (
            "  <article class=\"auto-real-report\""
            f" data-event-id=\"{_escape_attribute(entry.event_id)}\""
            f" data-indicator-name=\"{_escape_attribute(entry.indicator_name)}\""
            f" data-reference-period=\"{_escape_attribute(entry.reference_period)}\""
            f" data-release-kst=\"{_escape_attribute(entry.release_datetime_kst)}\""
            f" data-report-href=\"{_escape_attribute(entry.report_href)}\">",
            f"    <!-- report-sha256: {entry.report_sha256} -->",
            f"    <h3>{html.escape(title)}</h3>",
            f"    <p>발표: {html.escape(_display_release_kst(entry.release_datetime_kst))}</p>",
            "    <p>분석 방식: 규칙 기반 자동 해석 · 비용: 무료</p>",
            f"    <p><a href=\"{_escape_attribute(entry.report_href)}\">리포트 열기</a></p>",
            "  </article>",
        )
    )


def _render_managed_region(entries: list[ReportEntry]) -> str:
    ordered = sorted(entries, key=lambda item: _parse_release_kst(item.release_datetime_kst), reverse=True)
    if ordered:
        content = "\n".join(_render_entry(entry) for entry in ordered)
    else:
        content = "  <p class=\"auto-real-report-empty\">아직 자동 생성된 실제 발표 리포트가 없습니다.</p>"
    return "\n".join(
        (
            START_MARKER,
            "<section class=\"auto-real-reports\">",
            "  <h2>실제 발표 리포트</h2>",
            "  <div class=\"auto-real-report-list\">",
            content,
            "  </div>",
            "</section>",
            END_MARKER,
        )
    )


def _sample_hrefs(index_text: str) -> set[str]:
    hrefs = set(re.findall(r'href=["\']([^"\']+)["\']', index_text, flags=re.IGNORECASE))
    return {href for href in hrefs if "sample" in href.lower()}


def _validate_final_index(before: str, after: str, managed_region: str) -> None:
    if STYLE_RE.findall(before) != STYLE_RE.findall(after):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "index style blocks changed")
    if SCRIPT_RE.findall(before) != SCRIPT_RE.findall(after):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "index script blocks changed")
    for href in _sample_hrefs(before):
        if href not in after:
            raise ReportIndexError("INDEX_UPDATE_FAILED", "existing sample report link was removed")
    if UNSAFE_SEGMENT_RE.search(managed_region):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "generated region contains unsafe HTML")
    if EVENT_HANDLER_RE.search(managed_region) or JAVASCRIPT_URL_RE.search(managed_region):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "generated region contains unsafe URL or handler")
    if SECRET_VALUE_RE.search(managed_region) or re.search(r"[A-Za-z]:\\", managed_region):
        raise ReportIndexError("INDEX_UPDATE_FAILED", "generated region exposes a secret-like value or Windows path")


def _write_atomic(path: Path, data: bytes) -> None:
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


def _write_result_json(path: Path | None, result: IndexUpdateResult) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, (json.dumps(result.to_payload(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def update_report_index(
    root: Path,
    event_id: str,
    *,
    report: str | None = None,
    canonical: str | None = None,
    index: str | None = None,
    result_json: str | None = None,
    apply: bool = True,
) -> IndexUpdateResult:
    root = root.resolve()
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise ReportIndexError("INVALID_EVENT_ID", "event_id must use uppercase letters, digits, and underscores")
    expected_report = root / "docs" / "reports" / f"{event_id}.html"
    expected_canonical = root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"
    expected_index = root / "docs" / "index.html"
    report_file = _resolve_project_file(root, report, expected_report, expected_report, "report path")
    canonical_file = _resolve_project_file(root, canonical, expected_canonical, expected_canonical, "canonical path")
    index_file = _resolve_project_file(root, index, expected_index, expected_index, "index path")
    result_file = _resolve_result_path(root, result_json)

    if not report_file.exists():
        result = _result("REPORT_NOT_FOUND", event_id=event_id)
        _write_result_json(result_file, result)
        return result
    if not canonical_file.exists():
        result = _result("CANONICAL_RELEASE_NOT_FOUND", event_id=event_id)
        _write_result_json(result_file, result)
        return result
    try:
        event = _calendar_event(root, event_id)
        entry = _validate_report_entry(
            root=root,
            event_id=event_id,
            report_file=report_file,
            canonical_file=canonical_file,
        )
        if event.get("reference_period") != entry.reference_period:
            raise ReportIndexError("REPORT_INTEGRITY_FAILED", "calendar reference_period does not match canonical")
    except ReportIndexError as exc:
        result = _result(
            exc.code,
            event_id=event_id,
            report=_artifact("invalid", report_file, root),
            index=_artifact("existing", index_file, root),
        )
        _write_result_json(result_file, result)
        return result

    if not index_file.is_file() or index_file.is_symlink():
        result = _result(
            "INDEX_UPDATE_FAILED",
            event_id=event_id,
            reference_period=entry.reference_period,
            report=_artifact("existing", report_file, root),
            index=_artifact("invalid", index_file, root),
            report_sha256=entry.report_sha256,
        )
        _write_result_json(result_file, result)
        return result
    index_text = index_file.read_text(encoding="utf-8")
    try:
        prefix, managed, suffix = _marker_bounds(index_text)
        entries = _parse_entries(managed)
        existing = next((item for item in entries if item.event_id == event_id), None)
        if existing is not None and existing != entry:
            raise ReportIndexError("INDEX_CONFLICT", "existing event_id has different report metadata")
        if existing is None:
            entries.append(entry)
        managed_region = _render_managed_region(entries)
        candidate = prefix + managed_region + suffix
        _validate_final_index(index_text, candidate, managed_region)
    except ReportIndexError as exc:
        result = _result(
            exc.code,
            event_id=event_id,
            reference_period=entry.reference_period,
            report=_artifact("existing", report_file, root),
            index=_artifact("existing", index_file, root),
            report_sha256=entry.report_sha256,
        )
        _write_result_json(result_file, result)
        return result

    if candidate == index_text:
        result = _result(
            "INDEX_ALREADY_UP_TO_DATE",
            event_id=event_id,
            reference_period=entry.reference_period,
            report=_artifact("existing", report_file, root),
            index=_artifact("existing", index_file, root),
            report_sha256=entry.report_sha256,
        )
        _write_result_json(result_file, result)
        return result
    if not apply:
        result = _result(
            "INDEX_UPDATE_REQUIRED",
            event_id=event_id,
            reference_period=entry.reference_period,
            report=_artifact("existing", report_file, root),
            index=_artifact("existing", index_file, root),
            report_sha256=entry.report_sha256,
        )
        _write_result_json(result_file, result)
        return result
    _write_atomic(index_file, candidate.encode("utf-8"))
    result = _result(
        "INDEX_UPDATED",
        event_id=event_id,
        reference_period=entry.reference_period,
        report=_artifact("existing", report_file, root),
        index=_artifact("updated", index_file, root),
        index_changed=True,
        report_sha256=entry.report_sha256,
    )
    _write_result_json(result_file, result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely register an actual CPI report on the index page")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--report")
    parser.add_argument("--canonical")
    parser.add_argument("--index")
    parser.add_argument("--result-json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = update_report_index(
            project_root(),
            args.event_id,
            report=args.report,
            canonical=args.canonical,
            index=args.index,
            result_json=args.result_json,
        )
    except ReportIndexError as exc:
        print(exc.code)
        print(f"error: {exc.message}")
        return 1
    print(result.status)
    print(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    return 0 if result.status in {"REPORT_NOT_FOUND", "CANONICAL_RELEASE_NOT_FOUND", "INDEX_UPDATED", "INDEX_ALREADY_UP_TO_DATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
