from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


EVENT_ID_RE = re.compile(r"[A-Z0-9_]+\Z")
SUCCESS_STATUSES = {"PROCESSED_AND_INDEXED", "INDEX_ONLY_RESUMED"}


class NotificationEventError(Exception):
    pass


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
    report_path = f"docs/reports/{event_id}.html"
    pure = PurePosixPath(report_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise NotificationEventError("report path is unsafe")
    report = result.get("report")
    if not isinstance(report, dict) or report.get("path") != report_path:
        raise NotificationEventError("success result report path is invalid")
    report_file = root / report_path
    index_file = root / "docs" / "index.html"
    if not report_file.is_file() or report_file.is_symlink():
        raise NotificationEventError("success result report file is missing")
    if not index_file.is_file() or report_path not in index_file.read_text(encoding="utf-8"):
        raise NotificationEventError("success result is not registered in index")
    reference_period = result.get("reference_period")
    if not isinstance(reference_period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", reference_period):
        raise NotificationEventError("success result reference_period is invalid")
    key = f"cpi:{event_id}:report-published"
    return NotificationEvent("NOTIFICATION_READY", True, event_id, "CPI", reference_period, str(status), "rule_based", False, "free", report_path, pages_url(repository, report_path), key)


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
