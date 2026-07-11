from __future__ import annotations

import argparse
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

from scripts.analysis import generate_ppi_analysis  # noqa: E402
from scripts.automation import update_report_index  # noqa: E402
from scripts.collectors import bls_ppi  # noqa: E402
from scripts.common import preview as common_preview  # noqa: E402
from scripts.pipelines import build_ppi_historical_canonical as canonical_module  # noqa: E402
from scripts.pipelines import build_ppi_release_report  # noqa: E402


EVENT_RE = re.compile(r"US_PPI_(\d{4})_(0[1-9]|1[0-2])\Z")
REF_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
HREF_RE = re.compile(r'''\b(?:href|src)=["']([^"']+)["']''', re.I)


class PpiBackfillError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class BackfillResult:
    status: str
    event_id: str
    reference_period: str
    data_api_called: bool
    ai_api_called: bool
    cost: str
    observation_sha256: str | None
    missing_local_links: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["missing_local_links"] = list(self.missing_local_links)
        value["schema_version"] = "1.0"
        return value


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def file_sha(path: Path) -> str:
    return common_preview.file_sha256(path)


def write_new(path: Path, data: bytes) -> None:
    try:
        common_preview.write_immutable_bytes(path, data)
    except common_preview.ImmutableWriteConflict as exc:
        raise PpiBackfillError("PPI_BACKFILL_CONFLICT", f"existing output: {path.name}") from exc


def parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PpiBackfillError("PPI_INVALID_RELEASE_TIME", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PpiBackfillError("PPI_INVALID_RELEASE_TIME", f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def validate_request(event_id: str, reference_period: str, release: str, now: datetime) -> None:
    match = EVENT_RE.fullmatch(event_id)
    if match is None or not REF_RE.fullmatch(reference_period) or f"{match.group(1)}-{match.group(2)}" != reference_period:
        raise PpiBackfillError("PPI_EVENT_REFERENCE_MISMATCH", "event_id and reference_period must match")
    if parse_utc(release, "original_release_datetime_utc") >= now:
        raise PpiBackfillError("PPI_RELEASE_NOT_HISTORICAL", "original release must be in the past")


def safe_output_root(root: Path, output_root: Path) -> Path:
    try:
        return common_preview.external_preview_root(root, output_root)
    except common_preview.PreviewSafetyError as exc:
        raise PpiBackfillError("PPI_UNSAFE_OUTPUT_ROOT", str(exc)) from exc


def protected_hashes(root: Path) -> dict[Path, str]:
    paths = (
        root / "data/calendar/events.json", root / "docs/index.html", root / "templates/sample_report_v11.html",
        root / "templates/report.html", root / "scripts/collectors/bls_cpi.py",
        root / ".github/workflows/capture-cpi-release.yml", root / ".github/workflows/process-cpi-release.yml",
    )
    return {path: file_sha(path) for path in paths}


def ensure_protected(before: dict[Path, str]) -> None:
    if any(file_sha(path) != value for path, value in before.items()):
        raise PpiBackfillError("PPI_OPERATIONAL_FILE_CHANGED", "a protected production file changed")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PpiBackfillError("PPI_BACKFILL_CONFLICT", f"invalid {path.name}") from exc
    if not isinstance(value, dict):
        raise PpiBackfillError("PPI_BACKFILL_CONFLICT", f"invalid {path.name}")
    return value


def build_observation(processed: dict[str, Any], event_id: str, release: str, retrieved: datetime) -> dict[str, Any]:
    reference = processed.get("reference_period")
    if not isinstance(reference, str):
        raise PpiBackfillError("PPI_PROCESSED_INVALID", "processed reference period missing")
    try:
        canonical_module.validate_processed(processed, reference)
    except canonical_module.PpiCanonicalError as exc:
        raise PpiBackfillError(exc.code, str(exc)) from exc
    result = {
        "schema_version": "1.0", "event_id": event_id, "indicator_type": "PPI", "country": "US",
        "reference_period": reference, "original_release_datetime_utc": release,
        "retrieved_at_utc": retrieved.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provenance": {"data_origin": "historical_backfill", "source_lookup_origin": "historical_lookup", "vintage_status": "current_api_snapshot", "not_as_released": True, "immutable": True},
        "series_ids": [canonical_module.SERIES[name] for name in canonical_module.METRICS],
        "core_definition": "final demand less foods, energy, and trade services",
        "processed": processed, "integrity": {"sha256": None},
    }
    result["integrity"]["sha256"] = canonical_module.sha256_payload(result)
    common_preview.validate_historical_provenance(result["provenance"], result["retrieved_at_utc"], result["integrity"]["sha256"])
    return result


def observation_fingerprint(observation: dict[str, Any]) -> str:
    return canonical_module.sha256_payload({
        "event_id": observation["event_id"], "reference_period": observation["reference_period"],
        "original_release_datetime_utc": observation["original_release_datetime_utc"],
        # Retrieval timestamps and transport metadata differ per lookup. The
        # immutable preview outcome depends on the validated PPI metrics and
        # their explicit series contract, not on those volatile fields.
        "metrics": observation["processed"]["metrics"], "series_ids": observation["series_ids"],
    })


def collect_processed(root: Path, stage: Path, reference: str, now: datetime, use_live_bls: bool, response: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    try:
        result = bls_ppi.collect_ppi(reference, stage / "collector", root=root, response=response, use_live_bls=use_live_bls, api_key=os.environ.get("BLS_API_KEY"), now=now)
    except bls_ppi.PpiError as exc:
        raise PpiBackfillError(exc.code, str(exc)) from exc
    return read_json(stage / "collector" / "processed_ppi.json"), bool(result["data_api_called"])


def local_path(value: str) -> Path | None:
    try:
        return common_preview.local_preview_reference(value)
    except common_preview.PreviewSafetyError as exc:
        raise PpiBackfillError("PPI_PREVIEW_LINKS_INVALID", str(exc)) from exc


def repair_local_links(docs: Path, preview: Path) -> tuple[str, ...]:
    queue = [Path("index.html"), Path("report.html")]
    visited: set[Path] = set()
    missing: list[str] = []
    while queue:
        relative = queue.pop(0)
        if relative in visited:
            continue
        visited.add(relative)
        target = preview / relative
        if not target.is_file():
            missing.append(relative.as_posix())
            continue
        if target.suffix.lower() not in {".html", ".htm"}:
            continue
        for href in HREF_RE.findall(target.read_text(encoding="utf-8")):
            linked = local_path(href)
            if linked is None or linked in visited:
                continue
            destination = preview / linked
            if not destination.exists():
                source = docs / linked
                if not source.is_file() or source.is_symlink():
                    missing.append(linked.as_posix())
                    continue
                write_new(destination, source.read_bytes())
            if linked.suffix.lower() in {".html", ".htm"}:
                queue.append(linked)
    return tuple(sorted(set(missing)))


def build_index(source: str, event_id: str, reference: str, release: str, report_sha: str) -> str:
    try:
        prefix, managed, suffix = update_report_index._marker_bounds(source)
        entries = update_report_index._parse_entries(managed)
        entry = update_report_index.ReportEntry(event_id, "US Producer Price Index", reference, parse_utc(release, "original_release_datetime_utc").astimezone(ZoneInfo("Asia/Seoul")).isoformat(), "report.html", report_sha)
        if any(item.event_id == event_id for item in entries):
            raise PpiBackfillError("PPI_BACKFILL_CONFLICT", "duplicate index event")
        rendered = update_report_index._render_managed_region(entries + [entry])
        candidate = prefix + rendered + suffix
        update_report_index._validate_final_index(source, candidate, rendered)
        return candidate
    except update_report_index.ReportIndexError as exc:
        raise PpiBackfillError("PPI_INDEX_INVALID", str(exc)) from exc


def existing_complete(event_dir: Path) -> dict[str, Any] | None:
    required = ("historical_observation.json", "canonical.json", "analysis.json", "report.html", "index.html", "result.json")
    if not all((event_dir / name).is_file() for name in required):
        return None
    result = read_json(event_dir / "result.json")
    return result if result.get("status") == "PPI_BACKFILL_REHEARSAL_COMPLETED" else None


def run_backfill(root: Path, event_id: str, reference_period: str, release: str, output_root: Path, *, use_live_bls: bool, now: datetime | None = None, response_fetcher: Callable[[], dict[str, Any]] | None = None) -> BackfillResult:
    root = root.resolve()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    validate_request(event_id, reference_period, release, now)
    output_root = safe_output_root(root, output_root)
    protected = protected_hashes(root)
    event_dir = output_root / event_id
    stage = output_root / f".{event_id}.{uuid4().hex}.tmp"
    output_root.mkdir(parents=True, exist_ok=True)
    stage.mkdir()
    try:
        response = response_fetcher() if response_fetcher is not None else None
        if response is None and not use_live_bls:
            raise PpiBackfillError("PPI_LIVE_FLAG_REQUIRED", "live BLS requires --use-live-bls")
        processed, called = collect_processed(root, stage, reference_period, now, use_live_bls, response)
        observation = build_observation(processed, event_id, release, now)
        if event_dir.exists():
            prior = existing_complete(event_dir)
            if prior is None:
                return BackfillResult("PPI_BACKFILL_CONFLICT", event_id, reference_period, called, False, "free", None, ())
            existing = read_json(event_dir / "historical_observation.json")
            status = "PPI_BACKFILL_ALREADY_COMPLETE" if observation_fingerprint(existing) == observation_fingerprint(observation) else "PPI_BACKFILL_CONFLICT"
            return BackfillResult(status, event_id, reference_period, called, False, "free", existing.get("integrity", {}).get("sha256"), tuple(prior.get("missing_local_links") or ()))
        canonical = canonical_module.build_canonical(event_id, reference_period, release, observation)
        canonical_path = stage / "canonical.json"
        observation_path = stage / "historical_observation.json"
        write_new(observation_path, json_bytes(observation))
        write_new(canonical_path, json_bytes(canonical))
        analysis_path = stage / "analysis.json"
        analysis = generate_ppi_analysis.analyze_file(canonical_path, analysis_path, event_id, now)
        report_path = stage / "report.html"
        report_sha = build_ppi_release_report.build_report_file(canonical_path, analysis_path, report_path, event_id, root / "templates/report.html")
        index = build_index((root / "docs/index.html").read_text(encoding="utf-8"), event_id, reference_period, release, report_sha)
        write_new(stage / "index.html", index.encode("utf-8"))
        missing = repair_local_links(root / "docs", stage)
        if missing:
            raise PpiBackfillError("PPI_PREVIEW_LINKS_INVALID", ", ".join(missing))
        shutil.rmtree(stage / "collector")
        result = BackfillResult("PPI_BACKFILL_REHEARSAL_COMPLETED", event_id, reference_period, called, False, "free", observation["integrity"]["sha256"], missing)
        write_new(stage / "result.json", json_bytes(result.payload()))
        ensure_protected(protected)
        os.replace(stage, event_dir)
        return result
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    finally:
        ensure_protected(protected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an isolated PPI historical backfill rehearsal")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--reference-period", required=True)
    parser.add_argument("--original-release-datetime-utc", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--use-live-bls", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_backfill(PROJECT_ROOT, args.event_id, args.reference_period, args.original_release_datetime_utc, Path(args.output_root), use_live_bls=args.use_live_bls)
    except PpiBackfillError as exc:
        print(exc.code)
        print(f"error: {exc}")
        return 1
    print(result.status)
    print(json.dumps(result.payload(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
