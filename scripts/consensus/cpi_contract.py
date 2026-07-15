"""Strict, offline contract for pre-release CPI consensus evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4


CPI_METRICS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
OBSERVATION_SCHEMA = "cpi-consensus-observation-v1"
SNAPSHOT_SCHEMA = "cpi-consensus-snapshot-v1"
EVENT_RE = re.compile(r"US_CPI_(\d{4})_(0[1-9]|1[0-2])\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
SECRET_RE = re.compile(r"api[ _-]?key|token|password|secret|authorization", re.IGNORECASE)
MOM_METRICS = {"headline_mom", "core_mom"}


class CpiConsensusContractError(Exception):
    """Raised when a consensus artifact fails the contract."""


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CpiConsensusContractError(f"{field}: timezone-aware ISO 8601 value is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CpiConsensusContractError(f"{field}: invalid ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise CpiConsensusContractError(f"{field}: timezone is required")
    return parsed.astimezone(timezone.utc)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def parse_expected(value: Any, metric: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str) or not value or value != value.strip():
        raise CpiConsensusContractError(f"{metric}: expected_raw must be a plain Decimal string")
    if any(token in value for token in ("%", ",", "_")):
        raise CpiConsensusContractError(f"{metric}: locale or unit characters are not allowed")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise CpiConsensusContractError(f"{metric}: expected_raw must be Decimal") from exc
    if not parsed.is_finite():
        raise CpiConsensusContractError(f"{metric}: expected_raw must be finite")
    lower, upper = (Decimal("-10"), Decimal("10")) if metric in MOM_METRICS else (Decimal("-20"), Decimal("30"))
    if parsed < lower or parsed > upper:
        raise CpiConsensusContractError(f"{metric}: expected_raw is outside the safety range")
    return parsed


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_sha256(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload)
    integrity = value.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("sha256", None)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CpiConsensusContractError("input must be a regular non-symlink JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CpiConsensusContractError("input JSON is invalid") from exc
    if not isinstance(value, dict):
        raise CpiConsensusContractError("input JSON root must be an object")
    return value


def safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise CpiConsensusContractError("path must stay inside the project root") from exc


def safe_under(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return ".." not in path.parts and not any(item.is_symlink() for item in (path, *path.parents) if item.exists())


def _require_keys(value: dict[str, Any], required: set[str], field: str) -> None:
    if set(value) != required:
        raise CpiConsensusContractError(f"{field}: unknown or missing fields")


def find_event(calendar: dict[str, Any], event_id: str) -> dict[str, Any]:
    match = EVENT_RE.fullmatch(event_id)
    if not match:
        raise CpiConsensusContractError("event_id is invalid")
    events = calendar.get("events")
    if not isinstance(events, list):
        raise CpiConsensusContractError("calendar events must be an array")
    matches = [item for item in events if isinstance(item, dict) and item.get("event_id") == event_id]
    if len(matches) != 1:
        raise CpiConsensusContractError("event_id must appear exactly once")
    event = matches[0]
    if event.get("indicator_type") != "CPI" or event.get("country") != "US":
        raise CpiConsensusContractError("target event must be US CPI")
    if event.get("reference_period") != f"{match.group(1)}-{match.group(2)}":
        raise CpiConsensusContractError("event reference period does not match event_id")
    parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")
    metrics = event.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(CPI_METRICS):
        raise CpiConsensusContractError("calendar CPI metrics are invalid")
    return event


def observation_path(root: Path, event_id: str, observation_sha256: str) -> Path:
    return root / "data" / "consensus" / "cpi" / event_id / "provider_observations" / f"{observation_sha256}.json"


def snapshot_path(root: Path, event_id: str) -> Path:
    return root / "data" / "consensus" / "cpi" / event_id / "consensus_snapshot.json"


def _validate_metric(value: Any, metric: str, *, allow_null: bool) -> Decimal | None:
    if not isinstance(value, dict):
        raise CpiConsensusContractError(f"metrics.{metric}: object is required")
    _require_keys(value, {"expected_raw", "expected_display", "unit", "provider_metric_label", "mapping_version"}, f"metrics.{metric}")
    if value.get("unit") != "%" or not isinstance(value.get("provider_metric_label"), str) or not value["provider_metric_label"].strip():
        raise CpiConsensusContractError(f"metrics.{metric}: unit or provider label is invalid")
    if not isinstance(value.get("mapping_version"), str) or not value["mapping_version"].strip():
        raise CpiConsensusContractError(f"metrics.{metric}: mapping_version is required")
    raw = value.get("expected_raw")
    display = value.get("expected_display")
    if raw is None and allow_null:
        if display is not None:
            raise CpiConsensusContractError(f"metrics.{metric}: display must be null when expected is null")
        return None
    parsed = parse_expected(raw, metric)
    expected_display = f"{parsed.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%"
    if display != expected_display:
        raise CpiConsensusContractError(f"metrics.{metric}: expected_display is invalid")
    return parsed


def validate_observation(payload: dict[str, Any], event: dict[str, Any] | None = None) -> str:
    required = {
        "schema_version", "provider_id", "provider_name", "retrieved_at_utc", "observed_at_utc",
        "source_url", "source_reference", "source_document_sha256", "raw_response_path",
        "raw_response_sha256", "response_version", "event_id", "indicator_type", "country",
        "reference_period", "release_datetime_utc", "status", "metrics", "integrity",
    }
    _require_keys(payload, required, "observation")
    if payload.get("schema_version") != OBSERVATION_SCHEMA:
        raise CpiConsensusContractError("observation schema_version is invalid")
    if payload.get("indicator_type") != "CPI" or payload.get("country") != "US":
        raise CpiConsensusContractError("observation must be US CPI")
    if not isinstance(payload.get("provider_id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", payload["provider_id"]):
        raise CpiConsensusContractError("provider_id is invalid")
    for field in ("provider_name", "source_url", "source_reference", "response_version"):
        if not isinstance(payload.get(field), str) or not payload[field].strip() or SECRET_RE.search(payload[field]):
            raise CpiConsensusContractError(f"{field} is invalid or contains credentials")
    for field in ("source_document_sha256", "raw_response_sha256"):
        if not isinstance(payload.get(field), str) or SHA_RE.fullmatch(payload[field]) is None:
            raise CpiConsensusContractError(f"{field} must be a SHA-256")
    raw_path = payload.get("raw_response_path")
    if not isinstance(raw_path, str) or not raw_path.startswith("data/") or ".." in Path(raw_path).parts or "\\" in raw_path:
        raise CpiConsensusContractError("raw_response_path must be a safe repository-relative path")
    retrieved = parse_utc(payload.get("retrieved_at_utc"), "retrieved_at_utc")
    observed = parse_utc(payload.get("observed_at_utc"), "observed_at_utc")
    release = parse_utc(payload.get("release_datetime_utc"), "release_datetime_utc")
    if observed > retrieved:
        raise CpiConsensusContractError("observed_at_utc must not be after retrieved_at_utc")
    if event is not None:
        for field in ("event_id", "reference_period", "release_datetime_utc"):
            expected = event[field]
            actual = payload[field]
            if field == "release_datetime_utc":
                expected, actual = iso_utc(parse_utc(expected, field)), iso_utc(release)
            if actual != expected:
                raise CpiConsensusContractError(f"observation {field} does not match calendar")
    if retrieved >= release:
        return "AFTER_RELEASE"
    status = payload.get("status")
    if status not in {"COMPLETE", "INCOMPLETE", "UNAVAILABLE", "INVALID", "STALE"}:
        raise CpiConsensusContractError("observation status is invalid")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(CPI_METRICS):
        raise CpiConsensusContractError("observation must contain exactly four metrics")
    values = {metric: _validate_metric(metrics[metric], metric, allow_null=True) for metric in CPI_METRICS}
    populated = [value for value in values.values() if value is not None]
    expected_status = "COMPLETE" if len(populated) == 4 else "UNAVAILABLE" if not populated else "INCOMPLETE"
    if status in {"COMPLETE", "INCOMPLETE", "UNAVAILABLE"} and status != expected_status:
        raise CpiConsensusContractError("observation status does not match metric completeness")
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("immutable") is not True or integrity.get("sha256") != stable_sha256(payload):
        raise CpiConsensusContractError("observation integrity is invalid")
    return status


def build_snapshot(observation: dict[str, Any], event: dict[str, Any], captured_at_utc: datetime) -> dict[str, Any]:
    status = validate_observation(observation, event)
    if status != "COMPLETE":
        raise CpiConsensusContractError(f"observation is not complete: {status}")
    release = parse_utc(event["release_datetime_utc"], "release_datetime_utc")
    if captured_at_utc.tzinfo is None or captured_at_utc.astimezone(timezone.utc) >= release:
        raise CpiConsensusContractError("snapshot must be captured before release")
    observation_sha = observation["integrity"]["sha256"]
    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA,
        "snapshot_id": f"cpi-{event['event_id'].lower()}-{observation_sha[:16]}",
        "event_id": event["event_id"], "indicator_type": "CPI", "country": "US",
        "reference_period": event["reference_period"], "release_datetime_utc": iso_utc(release),
        "captured_at_utc": iso_utc(captured_at_utc), "cutoff_before_release": True,
        "provider": {"id": observation["provider_id"], "name": observation["provider_name"]},
        "source": {"url": observation["source_url"], "reference": observation["source_reference"], "document_sha256": observation["source_document_sha256"], "response_version": observation["response_version"]},
        "observation": {"sha256": observation_sha, "retrieved_at_utc": observation["retrieved_at_utc"], "observed_at_utc": observation["observed_at_utc"], "raw_response_path": observation["raw_response_path"], "raw_response_sha256": observation["raw_response_sha256"]},
        "metrics": copy.deepcopy(observation["metrics"]),
        "completeness": "COMPLETE", "validation": {"status": "VALID", "all_metrics_complete": True},
        "integrity": {"immutable": True, "sha256": None},
    }
    payload["integrity"]["sha256"] = stable_sha256(payload)
    return payload


def validate_snapshot(payload: dict[str, Any], event: dict[str, Any] | None = None) -> None:
    required = {"schema_version", "snapshot_id", "event_id", "indicator_type", "country", "reference_period", "release_datetime_utc", "captured_at_utc", "cutoff_before_release", "provider", "source", "observation", "metrics", "completeness", "validation", "integrity"}
    _require_keys(payload, required, "snapshot")
    if payload.get("schema_version") != SNAPSHOT_SCHEMA or not isinstance(payload.get("snapshot_id"), str) or not payload["snapshot_id"]:
        raise CpiConsensusContractError("snapshot schema or id is invalid")
    if payload.get("indicator_type") != "CPI" or payload.get("country") != "US" or payload.get("completeness") != "COMPLETE":
        raise CpiConsensusContractError("snapshot must be complete US CPI")
    release = parse_utc(payload.get("release_datetime_utc"), "snapshot.release_datetime_utc")
    captured = parse_utc(payload.get("captured_at_utc"), "snapshot.captured_at_utc")
    if payload.get("cutoff_before_release") is not True or captured >= release:
        raise CpiConsensusContractError("snapshot cutoff must be before release")
    provider = payload.get("provider")
    source = payload.get("source")
    observation = payload.get("observation")
    validation = payload.get("validation")
    if not isinstance(provider, dict) or set(provider) != {"id", "name"} or not all(isinstance(provider.get(key), str) and provider[key].strip() for key in provider):
        raise CpiConsensusContractError("snapshot provider is invalid")
    if not isinstance(source, dict) or set(source) != {"url", "reference", "document_sha256", "response_version"} or SHA_RE.fullmatch(str(source.get("document_sha256"))) is None:
        raise CpiConsensusContractError("snapshot source is invalid")
    for field in ("url", "reference", "response_version"):
        if not isinstance(source.get(field), str) or not source[field].strip() or SECRET_RE.search(source[field]):
            raise CpiConsensusContractError("snapshot source contains invalid or credential data")
    if not isinstance(observation, dict) or set(observation) != {"sha256", "retrieved_at_utc", "observed_at_utc", "raw_response_path", "raw_response_sha256"}:
        raise CpiConsensusContractError("snapshot observation is invalid")
    if SHA_RE.fullmatch(str(observation.get("sha256"))) is None or SHA_RE.fullmatch(str(observation.get("raw_response_sha256"))) is None:
        raise CpiConsensusContractError("snapshot observation SHA is invalid")
    raw_path = observation.get("raw_response_path")
    if not isinstance(raw_path, str) or not raw_path.startswith("data/") or ".." in Path(raw_path).parts or "\\" in raw_path:
        raise CpiConsensusContractError("snapshot raw_response_path is unsafe")
    if parse_utc(observation.get("retrieved_at_utc"), "snapshot.observation.retrieved_at_utc") >= release:
        raise CpiConsensusContractError("snapshot observation must precede release")
    if not isinstance(validation, dict) or validation != {"status": "VALID", "all_metrics_complete": True}:
        raise CpiConsensusContractError("snapshot validation is invalid")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(CPI_METRICS):
        raise CpiConsensusContractError("snapshot metrics are invalid")
    for metric in CPI_METRICS:
        if _validate_metric(metrics[metric], metric, allow_null=False) is None:
            raise CpiConsensusContractError("snapshot metrics must be complete")
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("immutable") is not True or integrity.get("sha256") != stable_sha256(payload):
        raise CpiConsensusContractError("snapshot integrity is invalid")
    if event is not None:
        for field in ("event_id", "reference_period"):
            if payload.get(field) != event.get(field):
                raise CpiConsensusContractError(f"snapshot {field} does not match calendar")
        if iso_utc(release) != iso_utc(parse_utc(event.get("release_datetime_utc"), "release_datetime_utc")):
            raise CpiConsensusContractError("snapshot release_datetime_utc does not match calendar")


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(item.is_symlink() for item in (path.parent, *path.parent.parents) if item.exists()):
        raise CpiConsensusContractError("output path must not traverse a symlink")
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError as exc:
            if exc.errno not in {getattr(os, "EXDEV", 18), 18, 95} and getattr(exc, "winerror", None) not in {1, 50}:
                raise CpiConsensusContractError("exclusive snapshot link failed") from exc
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
    finally:
        if temporary.exists():
            temporary.unlink()
