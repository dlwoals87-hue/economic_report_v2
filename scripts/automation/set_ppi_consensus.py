from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validators import validate_calendar_events  # noqa: E402


PPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
PPI_EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
SOURCE_SECRET_RE = re.compile(r"api[ _-]?key|token|password|secret", re.IGNORECASE)
MOM_METRICS = {"headline_mom", "core_mom"}


class PpiConsensusError(Exception):
    pass


@dataclass(frozen=True)
class ConsensusResult:
    status: str
    event_id: str | None
    reference_period: str | None
    release_datetime_utc: str | None
    release_datetime_kst: str | None
    file_modified: bool
    consensus_status: str | None
    source: str | None
    source_observed_at_utc: str | None
    entered_at_utc: str | None
    metrics: dict[str, dict[str, str]]
    warnings: tuple[str, ...]
    before_sha256: str | None
    after_sha256: str | None
    next_action: str
    external_api_called: bool = False
    external_ai_api_called: bool = False
    cost: str = "free"

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = "1.0"
        value["warnings"] = list(self.warnings)
        return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PpiConsensusError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PpiConsensusError(f"{field} must be timezone-aware ISO 8601") from exc
    if parsed.tzinfo is None:
        raise PpiConsensusError(f"{field} must be timezone-aware ISO 8601")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_kst(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat()


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def parse_metric(value: Any, metric: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PpiConsensusError(f"{metric}: non-empty Decimal value is required")
    text = value.strip()
    if "%" in text or "," in text:
        raise PpiConsensusError(f"{metric}: percent and comma characters are not allowed")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise PpiConsensusError(f"{metric}: Decimal value is required") from exc
    if not parsed.is_finite():
        raise PpiConsensusError(f"{metric}: finite Decimal value is required")
    lower, upper = (Decimal("-10"), Decimal("10")) if metric in MOM_METRICS else (Decimal("-20"), Decimal("30"))
    if parsed < lower or parsed > upper:
        raise PpiConsensusError(f"{metric}: value is outside the input safety range")
    return decimal_text(parsed)


def normalize_source(value: Any) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value.strip():
        raise PpiConsensusError("source is required")
    source = value.strip()
    if "://" in source or SOURCE_SECRET_RE.search(source):
        raise PpiConsensusError("source must be a source name without URL or credentials")
    mixed = any(marker in source.lower() for marker in (";", " and ", " + ", "multiple source", "multiple sources"))
    warnings = ("Confirm all four values come from one source at the same time.",) if mixed else ()
    return source, warnings


def safe_path(path: Path, root: Path) -> bool:
    if ".." in path.parts:
        return False
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    bases = (root.resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(resolved.is_relative_to(base) for base in bases):
        return False
    return not any(parent.is_symlink() for parent in (path, *path.parents) if parent.exists())


def read_calendar(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiConsensusError("calendar JSON is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise PpiConsensusError("calendar events are invalid")
    return value


def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    match = PPI_EVENT_RE.fullmatch(event_id)
    if match is None:
        raise PpiConsensusError("event_id is invalid")
    matches = [event for event in calendar["events"] if isinstance(event, dict) and event.get("event_id") == event_id]
    if len(matches) != 1:
        raise PpiConsensusError("event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "PPI" or event.get("country") != "US":
        raise PpiConsensusError("target event must be US PPI")
    if event.get("reference_period") != f"{match.group(1)}-{match.group(2)}":
        raise PpiConsensusError("event_id and reference_period must match")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    metrics = event.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(PPI_METRICS) or any(not isinstance(metrics[name], dict) for name in PPI_METRICS):
        raise PpiConsensusError("target event PPI metrics are invalid")
    return event


def snapshot_exists(root: Path, event_id: str) -> bool:
    return (root / "data" / "consensus" / "ppi" / event_id / "consensus_snapshot.json").exists()


def all_expected_null(event: dict[str, Any]) -> bool:
    return all(event["metrics"][metric].get("expected") is None for metric in PPI_METRICS)


def matches_existing(event: dict[str, Any], values: dict[str, str], source: str, observed: str) -> bool:
    return event.get("consensus_status") == "complete" and event.get("consensus_source") == source and event.get("entered_at_utc") == observed and all(event["metrics"][metric].get("expected") == values[metric] for metric in PPI_METRICS)


def validate_calendar(payload: dict[str, Any], now: datetime) -> None:
    result = validate_calendar_events.validate_events_payload(payload, now=now)
    if not result.valid:
        raise PpiConsensusError(f"calendar validation failed: {result.errors[0]}")


def canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_result(status: str, event: dict[str, Any] | None = None, *, modified: bool = False, source: str | None = None, observed: str | None = None, metrics: dict[str, dict[str, str]] | None = None, warnings: tuple[str, ...] = (), before: str | None = None, after: str | None = None, next_action: str = "none") -> ConsensusResult:
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc") if event else None
    return ConsensusResult(status, event.get("event_id") if event else None, event.get("reference_period") if event else None, iso_utc(release) if release else None, iso_kst(release) if release else None, modified, "complete" if status in {"PPI_CONSENSUS_PREVIEW", "PPI_CONSENSUS_APPLIED", "PPI_CONSENSUS_ALREADY_APPLIED"} else (event.get("consensus_status") if event else None), source, observed, observed, metrics or {}, warnings, before, after, next_action)


def set_consensus(root: Path, *, event_id: str, metric_values: dict[str, Any], source: Any, source_observed_at_utc: str, mode: str, now_utc: datetime | None = None, events_path: Path | None = None) -> ConsensusResult:
    if mode not in {"preview", "apply"}:
        raise PpiConsensusError("exactly one of preview or apply is required")
    root = root.resolve()
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    path = events_path or root / "data" / "calendar" / "events.json"
    if not safe_path(path, root):
        raise PpiConsensusError("events path is unsafe")
    original = path.read_bytes()
    calendar = read_calendar(path)
    validate_calendar(calendar, now)
    event = find_event(calendar, event_id)
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    if now >= release:
        return build_result("PPI_CONSENSUS_ENTRY_WINDOW_EXPIRED", event)
    values = {metric: parse_metric(metric_values.get(metric), metric) for metric in PPI_METRICS}
    source_name, source_warnings = normalize_source(source)
    observed = parse_utc(source_observed_at_utc, "source_observed_at_utc")
    if observed > now or observed >= release:
        raise PpiConsensusError("source_observed_at_utc is outside the input window")
    observed_text = iso_utc(observed)
    metrics = {metric: {"expected": values[metric]} for metric in PPI_METRICS}
    warnings = source_warnings + ("Consensus locking is a separate 5.3F-2 step and must finish before release.",)
    if snapshot_exists(root, event_id):
        return build_result("PPI_CONSENSUS_LOCKED", event, source=source_name, observed=observed_text, metrics=metrics, warnings=warnings)
    if not all_expected_null(event):
        status = "PPI_CONSENSUS_ALREADY_APPLIED" if matches_existing(event, values, source_name, observed_text) else "PPI_CONSENSUS_CONFLICT"
        return build_result(status, event, source=source_name, observed=observed_text, metrics=metrics, warnings=warnings)
    if event.get("consensus_status") != "not_entered":
        return build_result("PPI_CONSENSUS_CONFLICT", event, source=source_name, observed=observed_text, metrics=metrics, warnings=warnings)
    before = sha256_bytes(original)
    if mode == "preview":
        return build_result("PPI_CONSENSUS_PREVIEW", event, source=source_name, observed=observed_text, metrics=metrics, warnings=warnings, before=before, next_action="review_then_apply")
    updated = copy.deepcopy(calendar)
    target = find_event(updated, event_id)
    for metric in PPI_METRICS:
        target["metrics"][metric]["expected"] = values[metric]
    target["consensus_status"] = "complete"
    target["consensus_source"] = source_name
    target["entered_at_utc"] = observed_text
    validate_calendar(updated, now)
    atomic_write(path, canonical_json(updated))
    return build_result("PPI_CONSENSUS_APPLIED", target, modified=True, source=source_name, observed=observed_text, metrics=metrics, warnings=warnings, before=before, after=sha256_bytes(path.read_bytes()), next_action="5.3F-2")


def write_result(path: Path, root: Path, result: ConsensusResult) -> None:
    if not safe_path(path, root):
        raise PpiConsensusError("result-json path is unsafe")
    atomic_write(path, canonical_json(result.payload()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely preview or apply PPI consensus before release")
    parser.add_argument("--event-id")
    parser.add_argument("--headline-mom")
    parser.add_argument("--headline-yoy")
    parser.add_argument("--core-mom")
    parser.add_argument("--core-yoy")
    parser.add_argument("--source")
    parser.add_argument("--source-observed-at-utc")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--events")
    parser.add_argument("--result-json")
    args = parser.parse_args(argv)
    required = (args.event_id, args.headline_mom, args.headline_yoy, args.core_mom, args.core_yoy, args.source, args.source_observed_at_utc)
    if not any(required) and not args.preview and not args.apply:
        print("PPI_CONSENSUS_INPUT_REQUIRED")
        return 0
    if not all(required) or args.preview == args.apply:
        print("PPI_CONSENSUS_INPUT_REQUIRED")
        return 1
    try:
        root = PROJECT_ROOT
        events = Path(args.events) if args.events else root / "data" / "calendar" / "events.json"
        result = set_consensus(root, event_id=args.event_id, metric_values={"headline_mom": args.headline_mom, "headline_yoy": args.headline_yoy, "core_mom": args.core_mom, "core_yoy": args.core_yoy}, source=args.source, source_observed_at_utc=args.source_observed_at_utc, mode="preview" if args.preview else "apply", events_path=events)
        if args.result_json:
            write_result(Path(args.result_json), root, result)
    except PpiConsensusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(result.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
