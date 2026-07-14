from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any


EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
SUCCESS_STATUSES = {
    "PROCESSED_AND_INDEXED",
    "REPORT_ONLY_RESUMED_AND_INDEXED",
    "REPORT_ONLY_RESUMED",
    "INDEX_ONLY_RESUMED",
    "ALREADY_PROCESSED",
}
INDEX_START_MARKER = "<!-- AUTO_REAL_REPORTS_START -->"
INDEX_END_MARKER = "<!-- AUTO_REAL_REPORTS_END -->"


class NotificationEventError(Exception):
    pass


class _IndexRegistrationParser(HTMLParser):
    def __init__(self, event_id: str, report_href: str) -> None:
        super().__init__(convert_charrefs=True)
        self.event_id = event_id
        self.report_href = report_href
        self.article_depth = 0
        self.article_attrs: list[tuple[str, str | None]] | None = None
        self.matches = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.article_depth:
            if tag.lower() == "article":
                self.article_depth += 1
            return
        if tag.lower() == "article":
            self.article_depth = 1
            self.article_attrs = attrs

    def handle_endtag(self, tag: str) -> None:
        if not self.article_depth or tag.lower() != "article":
            return
        self.article_depth -= 1
        if self.article_depth:
            return
        attrs = self.article_attrs or []
        classes = [value for name, value in attrs if name.lower() == "class"]
        event_ids = [value for name, value in attrs if name.lower() == "data-event-id"]
        hrefs = [value for name, value in attrs if name.lower() == "data-report-href"]
        if (
            len(classes) == 1
            and "auto-real-report" in (classes[0] or "").split()
            and event_ids == [self.event_id]
            and hrefs == [self.report_href]
        ):
            self.matches += 1
        self.article_attrs = None


@dataclass(frozen=True)
class NotificationEvent:
    status: str
    should_notify: bool
    event_id: str | None
    indicator_type: str | None
    reference_period: str | None
    processing_status: str | None
    provider: str | None
    external_api_called: bool
    cost: str | None
    report_relative_path: str | None
    report_url: str | None
    notification_key: str | None

    def payload(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema_version"] = "1.0"
        return result


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotificationEventError("notification input JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise NotificationEventError("notification input JSON must be an object")
    return payload


def pages_url(repository: str, relative_path: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise NotificationEventError("repository is invalid")
    owner, name = repository.split("/", 1)
    return f"https://{owner}.github.io/{name}/{relative_path}"


def index_has_registration(index_text: str, event_id: str, report_href: str) -> bool:
    if index_text.count(INDEX_START_MARKER) != 1 or index_text.count(INDEX_END_MARKER) != 1:
        return False
    start = index_text.index(INDEX_START_MARKER) + len(INDEX_START_MARKER)
    end = index_text.index(INDEX_END_MARKER, start)
    if end < start:
        return False
    parser = _IndexRegistrationParser(event_id, report_href)
    try:
        parser.feed(index_text[start:end])
        parser.close()
    except Exception:
        return False
    return parser.matches == 1 and parser.article_depth == 0


def skipped(status: str) -> NotificationEvent:
    return NotificationEvent("NOTIFICATION_SKIPPED", False, None, None, None, status, None, False, None, None, None, None)


def build_event(root: Path, result: dict[str, Any], repository: str) -> NotificationEvent:
    status = result.get("status")
    if status not in SUCCESS_STATUSES:
        return skipped(str(status) if status is not None else "unknown")
    event_id = result.get("event_id")
    if not isinstance(event_id, str) or EVENT_ID_RE.fullmatch(event_id) is None:
        raise NotificationEventError("success result has invalid event_id")
    if result.get("provider") != "rule_based" or result.get("external_api_called") is not False or result.get("cost_mode") != "free":
        raise NotificationEventError("success result has unsafe provider metadata")
    repository_report_path = f"docs/reports/{event_id}.html"
    pages_report_href = f"reports/{event_id}.html"
    pure = PurePosixPath(repository_report_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise NotificationEventError("report path is unsafe")
    report = result.get("report")
    if not isinstance(report, dict) or report.get("path") != repository_report_path:
        raise NotificationEventError("success result report path is invalid")
    report_file = root / repository_report_path
    index_file = root / "docs" / "index.html"
    if not report_file.is_file() or report_file.is_symlink():
        raise NotificationEventError("success result report file is missing")
    if not index_file.is_file() or index_file.is_symlink():
        raise NotificationEventError("success result index file is missing")
    if not index_has_registration(index_file.read_text(encoding="utf-8"), event_id, pages_report_href):
        raise NotificationEventError("success result is not registered in index")
    reference_period = result.get("reference_period")
    if not isinstance(reference_period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", reference_period):
        raise NotificationEventError("success result reference_period is invalid")
    key = f"cpi:{event_id}:report-published"
    return NotificationEvent("NOTIFICATION_READY", True, event_id, "CPI", reference_period, str(status), "rule_based", False, "free", repository_report_path, pages_url(repository, pages_report_href), key)


def write_payload(path: Path, event: NotificationEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event.payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized CPI GitHub notification event")
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        event = build_event(root, read_json(Path(args.result_json)), args.repository)
        write_payload(Path(args.output), event)
    except NotificationEventError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(event.status)
    print(f"should_notify: {str(event.should_notify).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
