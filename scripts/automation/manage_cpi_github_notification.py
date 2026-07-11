from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out"}


@dataclass(frozen=True)
class ManagedNotification:
    status: str
    notification_key: str | None
    title: str | None
    body: str | None


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("notification payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("notification payload must be an object")
    return payload


def success_issue(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    if payload.get("should_notify") is not True:
        return None
    event_id = payload.get("event_id")
    period = payload.get("reference_period")
    key = payload.get("notification_key")
    if not isinstance(event_id, str) or not isinstance(period, str) or key != f"cpi:{event_id}:report-published":
        raise ValueError("notification payload is invalid")
    if payload.get("provider") != "rule_based" or payload.get("external_api_called") is not False or payload.get("cost") != "free":
        raise ValueError("notification payload is invalid")
    url = payload.get("report_url")
    if not isinstance(url, str) or not url.startswith("https://") or "file:" in url:
        raise ValueError("notification report URL is invalid")
    title = f"[CPI] {period} report published"
    body = f"<!-- notification-key:{key} -->\n\n- event_id: `{event_id}`\n- reference period: `{period}`\n- processing status: `{payload.get('processing_status')}`\n- provider: `rule_based`\n- external AI API: `false`\n- cost: `free`\n- report: {url}\n\nPages deployment may take a few minutes. This is not investment advice."
    return key, title, body


def failure_issue(run: dict[str, Any]) -> tuple[str, str, str] | None:
    conclusion = run.get("conclusion")
    if conclusion not in FAILURE_CONCLUSIONS:
        return None
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise ValueError("workflow run id is invalid")
    key = f"cpi:process-failure:{run_id}"
    name = run.get("name") or "Process CPI Release"
    branch = run.get("head_branch") or "unknown"
    sha = str(run.get("head_sha") or "unknown")[:7]
    actor = (run.get("actor") or {}).get("login") if isinstance(run.get("actor"), dict) else "unknown"
    url = run.get("html_url") or ""
    title = f"[CPI] Process workflow {conclusion}"
    body = f"<!-- notification-key:{key} -->\n\n- workflow: `{name}`\n- conclusion: `{conclusion}`\n- branch: `{branch}`\n- head SHA: `{sha}`\n- actor: `{actor}`\n- started: `{run.get('run_started_at') or 'unknown'}`\n- Actions run: {url}\n\nDo not manually modify production files. Review the Actions logs first."
    return key, title, body


def api_json(url: str, token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", **({"Content-Type": "application/json"} if data else {})})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def marker_exists(repository: str, token: str, marker: str, api=api_json) -> bool:
    for page in range(1, 101):
        issues = api(f"https://api.github.com/repos/{repository}/issues?state=all&per_page=100&page={page}", token)
        if not isinstance(issues, list):
            raise ValueError("issues API response is invalid")
        if any(isinstance(issue, dict) and marker in str(issue.get("body") or "") for issue in issues):
            return True
        if len(issues) < 100:
            return False
    raise ValueError("issues pagination limit exceeded")


def manage(repository: str, key: str | None, title: str | None, body: str | None, *, dry_run: bool, apply: bool, api=api_json, environment: dict[str, str] | None = None) -> ManagedNotification:
    if key is None:
        return ManagedNotification("NOTIFICATION_SKIPPED", None, None, None)
    if dry_run:
        return ManagedNotification("NOTIFICATION_DRY_RUN", key, title, body)
    env = environment if environment is not None else os.environ
    if not apply or env.get("GITHUB_ACTIONS") != "true" or not env.get("GITHUB_TOKEN"):
        return ManagedNotification("NOTIFICATION_SKIPPED", key, title, body)
    token = env["GITHUB_TOKEN"]
    marker = f"<!-- notification-key:{key} -->"
    try:
        if marker_exists(repository, token, marker, api):
            return ManagedNotification("NOTIFICATION_ALREADY_EXISTS", key, title, body)
        api(f"https://api.github.com/repos/{repository}/issues", token, "POST", {"title": title, "body": body})
    except Exception:
        return ManagedNotification("NOTIFICATION_API_ERROR", key, title, body)
    return ManagedNotification("NOTIFICATION_CREATED", key, title, body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create deduplicated CPI GitHub Issue notifications")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--payload")
    parser.add_argument("--workflow-run-json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if bool(args.payload) == bool(args.workflow_run_json):
            raise ValueError("provide exactly one payload source")
        issue = success_issue(read_json(Path(args.payload))) if args.payload else failure_issue(read_json(Path(args.workflow_run_json)))
        key, title, body = issue if issue else (None, None, None)
        result = manage(args.repository, key, title, body, dry_run=args.dry_run, apply=args.apply)
    except ValueError:
        result = ManagedNotification("NOTIFICATION_INVALID_PAYLOAD", None, None, None)
    print(result.status)
    if result.notification_key:
        print(f"notification_key: {result.notification_key}")
    if result.title:
        print(f"title: {result.title}")
    return 0 if result.status not in {"NOTIFICATION_INVALID_PAYLOAD", "NOTIFICATION_API_ERROR"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
