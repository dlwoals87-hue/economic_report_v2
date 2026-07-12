from __future__ import annotations

from typing import Any


SKIP = {"NO_PENDING_PPI_EVENT", "ALREADY_PROCESSED"}
SUCCESS = {"PROCESSED_AND_INDEXED", "INDEX_ONLY_RESUMED"}


def build_manual_dispatch_notification() -> dict[str, Any]:
    return {
        "status": "NOTIFICATION_SKIPPED",
        "upstream_status": "MANUAL_DISPATCH_NO_UPSTREAM",
        "event_id": None,
        "notification_action": "none",
        "issue_created": False,
        "issue_updated": False,
        "issue_number": None,
        "external_ai_api_called": False,
        "cost": "free",
    }


def build_notification(
    result: dict[str, Any],
    *,
    workflow_conclusion: str = "success",
    workflow_run_id: int | str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    status = (
        str(result.get("status") or "ARTIFACT_MISSING")
        if workflow_conclusion == "success"
        else "UPSTREAM_WORKFLOW_FAILURE"
    )
    event_id = result.get("event_id") or "UNKNOWN"

    if status in SKIP:
        return {
            "status": "NOTIFICATION_SKIPPED",
            "upstream_status": status,
            "event_id": result.get("event_id"),
            "notification_action": "none",
            "issue_created": False,
            "issue_updated": False,
            "issue_number": None,
            "external_ai_api_called": False,
            "cost": "free",
        }

    category = "success" if status in SUCCESS else "failure"
    dedupe_key = f"ppi-processing:{event_id}:{category}"
    body_lines = [
        f"<!-- {dedupe_key} -->",
        f"status: {status}",
        f"event_id: {event_id}",
        f"reference_period: {result.get('reference_period')}",
        f"provider: {result.get('provider')}",
        f"external_api_called: {result.get('external_api_called', False)}",
        "external_ai_api_called: false",
        f"cost: {result.get('cost_mode', 'free')}",
        f"commit_paths: {result.get('commit_paths', [])}",
    ]
    if workflow_run_id is not None:
        body_lines.append(f"upstream_workflow_run_id: {workflow_run_id}")
        if repository:
            body_lines.append(
                f"upstream_workflow_run: https://github.com/{repository}/actions/runs/{workflow_run_id}"
            )
    body_lines.append("Not investment advice.")

    return {
        "status": "NOTIFICATION_READY",
        "upstream_status": status,
        "event_id": event_id,
        "category": category,
        "dedupe_key": dedupe_key,
        "title": f"[PPI Processing {'Success' if category == 'success' else 'Failure'}] {event_id}",
        "body": "\n".join(body_lines),
        "labels": ["ppi-processing", "automation", category],
        "external_ai_api_called": False,
        "cost": "free",
    }


def decide_issue_action(notification: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    if notification["status"] == "NOTIFICATION_SKIPPED":
        return notification | {
            "notification_action": "none",
            "issue_created": False,
            "issue_updated": False,
            "issue_number": None,
        }

    marker = f"<!-- automation-key: {notification['dedupe_key']} -->"
    matches = [issue for issue in issues if marker in str(issue.get("body", ""))]
    if len(matches) > 1:
        return notification | {
            "status": "DUPLICATE_ISSUE_CONFLICT",
            "notification_action": "none",
            "issue_created": False,
            "issue_updated": False,
            "issue_number": None,
        }

    body = marker + "\n" + notification["body"]
    if not matches:
        return notification | {
            "notification_action": "created",
            "issue_created": True,
            "issue_updated": False,
            "issue_number": None,
            "body": body,
        }

    issue = matches[0]
    unchanged = issue.get("body") == body
    return notification | {
        "notification_action": "unchanged" if unchanged else "updated",
        "issue_created": False,
        "issue_updated": not unchanged,
        "issue_number": issue.get("number"),
        "body": body,
    }
