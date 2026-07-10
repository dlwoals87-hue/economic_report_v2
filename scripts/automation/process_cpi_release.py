from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis import generate_cpi_analysis  # noqa: E402
from scripts.pipelines import build_cpi_release_canonical  # noqa: E402
from scripts.providers import rule_based  # noqa: E402
from scripts.validators import validate_calendar_events  # noqa: E402


RESULT_SCHEMA_VERSION = "1.0"
DEFAULT_PROVIDER = "rule_based"
ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
SUCCESS_STATUSES = {
    "RELEASE_NOT_CAPTURED",
    "PROCESSED",
    "ALREADY_PROCESSED",
    "CANONICAL_ONLY_RESUMED",
}


class ProcessCpiError(Exception):
    """A safely classified CPI processing failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ProcessingResult:
    status: str
    event_id: str
    reference_period: str | None
    provider: str
    external_api_called: bool
    canonical: dict[str, Any]
    analysis: dict[str, Any]
    created_paths: tuple[str, ...]
    commit_paths: tuple[str, ...]
    usage: dict[str, int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": self.status,
            "event_id": self.event_id,
            "reference_period": self.reference_period,
            "provider": self.provider,
            "external_api_called": self.external_api_called,
            "cost_mode": "free",
            "canonical": dict(self.canonical),
            "analysis": dict(self.analysis),
            "usage": dict(self.usage),
            "created_paths": list(self.created_paths),
            "commit_paths": list(self.commit_paths),
        }


def project_root() -> Path:
    return PROJECT_ROOT


def release_path(root: Path, event_id: str) -> Path:
    return root / "data" / "releases" / "cpi" / event_id / "as_released.json"


def canonical_path(root: Path, event_id: str) -> Path:
    return root / "data" / "generated" / "cpi" / event_id / "canonical_release.json"


def analysis_path(root: Path, event_id: str) -> Path:
    return root / "data" / "analysis" / "cpi" / event_id / "cpi-analysis-v1.json"


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _empty_artifact() -> dict[str, Any]:
    return {"status": None, "path": None, "sha256": None}


def _artifact(status: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "status": status,
        "path": relative_path(path, root),
        "sha256": sha256_file(path),
    }


def _result(
    *,
    status: str,
    event_id: str,
    reference_period: str | None,
    canonical: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    created_paths: list[str] | None = None,
) -> ProcessingResult:
    created = tuple(created_paths or ())
    validate_commit_paths(created, event_id)
    return ProcessingResult(
        status=status,
        event_id=event_id,
        reference_period=reference_period,
        provider=DEFAULT_PROVIDER,
        external_api_called=False,
        canonical=canonical or _empty_artifact(),
        analysis=analysis or _empty_artifact(),
        created_paths=created,
        commit_paths=created,
        usage=dict(ZERO_USAGE),
    )


def validate_commit_paths(paths: tuple[str, ...] | list[str], event_id: str) -> None:
    if len(paths) > 2:
        raise ProcessCpiError("INVALID_COMMIT_PATH", "commit_paths may contain at most two paths")
    allowed = {
        f"data/generated/cpi/{event_id}/canonical_release.json",
        f"data/analysis/cpi/{event_id}/cpi-analysis-v1.json",
    }
    if len(paths) != len(set(paths)):
        raise ProcessCpiError("INVALID_COMMIT_PATH", "duplicate commit paths are not allowed")
    for value in paths:
        if not isinstance(value, str) or not value:
            raise ProcessCpiError("INVALID_COMMIT_PATH", "commit path must be a non-empty string")
        path = PurePath(value)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise ProcessCpiError("INVALID_COMMIT_PATH", "commit path must be project-relative")
        if value.replace("\\", "/") not in allowed:
            raise ProcessCpiError("INVALID_COMMIT_PATH", "commit path is not an allowed derivative")


def resolve_result_path(root: Path, event_id: str, value: str | None) -> Path | None:
    if value is None:
        return None
    requested = Path(value)
    if requested.is_absolute():
        raise ProcessCpiError("INVALID_RESULT_PATH", "--result-json must be a relative path")
    if any(part == ".." for part in requested.parts):
        raise ProcessCpiError("INVALID_RESULT_PATH", "--result-json cannot contain parent traversal")
    resolved = (root / requested).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ProcessCpiError("INVALID_RESULT_PATH", "--result-json must stay inside the project") from exc
    protected = {
        release_path(root, event_id).resolve(),
        canonical_path(root, event_id).resolve(),
        analysis_path(root, event_id).resolve(),
        (root / "data" / "calendar" / "events.json").resolve(),
    }
    if resolved in protected:
        raise ProcessCpiError("INVALID_RESULT_PATH", "--result-json cannot replace an input or derivative")
    return resolved


def _write_result_json(path: Path | None, result: ProcessingResult) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result.to_payload(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _finish(path: Path | None, result: ProcessingResult) -> ProcessingResult:
    _write_result_json(path, result)
    return result


def _read_object(path: Path, status: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessCpiError(status, "required JSON file is unreadable") from exc
    if not isinstance(payload, dict):
        raise ProcessCpiError(status, "required JSON root must be an object")
    return payload


def _calendar_event(
    root: Path,
    event_id: str,
    *,
    now: datetime | None,
) -> tuple[dict[str, Any] | None, bool]:
    try:
        payload = validate_calendar_events.read_json(root / "data" / "calendar" / "events.json")
    except ValueError:
        return None, False
    validation = validate_calendar_events.validate_events_payload(payload, now=now)
    if not validation.valid:
        return None, False
    events = payload.get("events")
    matches = [
        event
        for event in events
        if isinstance(event, dict) and event.get("event_id") == event_id
    ] if isinstance(events, list) else []
    return (matches[0], True) if len(matches) == 1 else (None, False)


def _validate_release_to_canonical(
    release_file: Path,
    canonical_file: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    release = _read_object(release_file, "INTEGRITY_CHECK_FAILED")
    canonical = _read_object(canonical_file, "INTEGRITY_CHECK_FAILED")
    stored_integrity = release.get("integrity")
    if not isinstance(stored_integrity, dict) or stored_integrity.get("immutable") is not True:
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "release immutable marker is invalid")
    stored_sha = stored_integrity.get("sha256")
    recalculated_sha = build_cpi_release_canonical.stable_sha256(release)
    if not isinstance(stored_sha, str) or stored_sha != recalculated_sha:
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "release SHA-256 is invalid")
    source = canonical.get("source")
    if not isinstance(source, dict) or source.get("release_capture_sha256") != recalculated_sha:
        raise ProcessCpiError(
            "INTEGRITY_CHECK_FAILED",
            "canonical release_capture_sha256 does not match as_released",
        )
    return release, canonical, sha256_file(canonical_file)


def _load_analysis_schema() -> tuple[dict[str, Any], str, str]:
    schema_file = PROJECT_ROOT / "schemas" / "cpi_analysis_v1.schema.json"
    prompt_file = PROJECT_ROOT / "prompts" / "cpi_analysis_v1.md"
    schema = _read_object(schema_file, "ANALYSIS_FAILED")
    return schema, sha256_file(schema_file), sha256_file(prompt_file)


def _validate_analysis_file(
    *,
    root: Path,
    event_id: str,
    canonical_file: Path,
    canonical: dict[str, Any],
    canonical_sha: str,
    release_sha: str,
    analysis_file: Path,
) -> dict[str, Any]:
    wrapper = _read_object(analysis_file, "ANALYSIS_FAILED")
    if wrapper.get("schema_version") != "1.0":
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis schema_version is invalid")
    if wrapper.get("analysis_version") != "cpi-analysis-v1":
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis_version is invalid")
    if wrapper.get("event_id") != event_id or wrapper.get("indicator_type") != "CPI":
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis identity is invalid")

    input_meta = wrapper.get("input")
    expected_canonical_path = relative_path(canonical_file, root)
    if not isinstance(input_meta, dict):
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "analysis input metadata is missing")
    if input_meta.get("canonical_path") != expected_canonical_path:
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "analysis canonical path is inconsistent")
    if input_meta.get("canonical_sha256") != canonical_sha:
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "analysis canonical SHA-256 is inconsistent")
    if input_meta.get("release_capture_sha256") != release_sha:
        raise ProcessCpiError("INTEGRITY_CHECK_FAILED", "analysis release SHA-256 is inconsistent")

    provider = wrapper.get("provider")
    if not isinstance(provider, dict):
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis provider metadata is missing")
    if provider.get("name") != "rule_based" or provider.get("requested_provider") != "rule_based":
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis provider must be rule_based")
    if provider.get("external_api_called") is not False:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis must not call an external API")
    if provider.get("fallback_used") is not False:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis fallback metadata is invalid")
    if any(
        provider.get(key) is not None
        for key in ("model_requested", "model_returned", "response_id", "fallback_reason")
    ):
        raise ProcessCpiError("ANALYSIS_FAILED", "rule_based provider metadata is invalid")

    if wrapper.get("usage") != ZERO_USAGE:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis token usage must be zero")
    generate_cpi_analysis.validate_canonical_release(canonical, event_id)
    facts = generate_cpi_analysis.build_facts(canonical)
    if wrapper.get("facts") != facts:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis facts do not match canonical")

    schema, schema_sha, prompt_sha = _load_analysis_schema()
    versions = wrapper.get("versions")
    if not isinstance(versions, dict):
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis version hashes are missing")
    if versions.get("schema_sha256") != schema_sha or versions.get("prompt_sha256") != prompt_sha:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis prompt or schema hash is stale")
    analysis = wrapper.get("analysis")
    if not isinstance(analysis, dict):
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis payload is missing")
    expected_analysis = rule_based.generate_analysis(facts=facts).analysis
    if analysis != expected_analysis:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis content does not match rule_based output")
    try:
        validation = generate_cpi_analysis.validate_analysis_output(analysis, schema, facts)
    except generate_cpi_analysis.CpiAnalysisError as exc:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis post-validation failed") from exc
    if wrapper.get("validation") != validation:
        raise ProcessCpiError("ANALYSIS_FAILED", "analysis validation metadata is inconsistent")
    return wrapper


def process_release(
    root: Path,
    event_id: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    result_json: str | None = None,
    now: datetime | None = None,
    canonical_builder: Callable[..., Any] | None = None,
    analysis_runner: Callable[..., Any] | None = None,
) -> ProcessingResult:
    root = root.resolve()
    if provider != DEFAULT_PROVIDER:
        raise ProcessCpiError(
            "EXTERNAL_PROVIDER_DISABLED",
            "3.8 integration only permits the rule_based provider",
        )
    result_file = resolve_result_path(root, event_id, result_json)
    event, calendar_valid = _calendar_event(root, event_id, now=now)
    if not calendar_valid or event is None:
        return _finish(
            result_file,
            _result(
                status="CALENDAR_INVALID",
                event_id=event_id,
                reference_period=None,
            ),
        )
    reference_period = event.get("reference_period")
    reference_period = reference_period if isinstance(reference_period, str) else None

    release_file = release_path(root, event_id)
    canonical_file = canonical_path(root, event_id)
    analysis_file = analysis_path(root, event_id)
    canonical_existed = canonical_file.exists()
    analysis_existed = analysis_file.exists()

    if analysis_existed and not canonical_existed:
        return _finish(
            result_file,
            _result(
                status="INCONSISTENT_DERIVED_STATE",
                event_id=event_id,
                reference_period=reference_period,
                analysis=_artifact("existing", analysis_file, root),
            ),
        )
    if not release_file.exists():
        if canonical_existed or analysis_existed:
            return _finish(
                result_file,
                _result(
                    status="INCONSISTENT_DERIVED_STATE",
                    event_id=event_id,
                    reference_period=reference_period,
                    canonical=(
                        _artifact("existing", canonical_file, root)
                        if canonical_existed
                        else _empty_artifact()
                    ),
                    analysis=(
                        _artifact("existing", analysis_file, root)
                        if analysis_existed
                        else _empty_artifact()
                    ),
                ),
            )
        return _finish(
            result_file,
            _result(
                status="RELEASE_NOT_CAPTURED",
                event_id=event_id,
                reference_period=reference_period,
            ),
        )

    created_paths: list[str] = []
    build = canonical_builder or build_cpi_release_canonical.build_from_files
    try:
        build_result = build(root, event_id)
    except build_cpi_release_canonical.ReleaseCanonicalError:
        return _finish(
            result_file,
            _result(
                status="INTEGRITY_CHECK_FAILED",
                event_id=event_id,
                reference_period=reference_period,
            ),
        )
    if build_result.status not in {"CANONICAL_CREATED", "ALREADY_UP_TO_DATE"}:
        return _finish(
            result_file,
            _result(
                status="INTEGRITY_CHECK_FAILED",
                event_id=event_id,
                reference_period=reference_period,
            ),
        )
    if not canonical_existed and build_result.status == "CANONICAL_CREATED":
        created_paths.append(relative_path(canonical_file, root))

    canonical_artifact = _artifact(
        "created" if not canonical_existed else "existing",
        canonical_file,
        root,
    )
    try:
        _, canonical, canonical_sha = _validate_release_to_canonical(
            release_file,
            canonical_file,
        )
    except ProcessCpiError as exc:
        return _finish(
            result_file,
            _result(
                status=exc.code,
                event_id=event_id,
                reference_period=reference_period,
                canonical=canonical_artifact,
                created_paths=created_paths,
            ),
        )
    release_sha = canonical["source"]["release_capture_sha256"]

    if analysis_existed:
        try:
            _validate_analysis_file(
                root=root,
                event_id=event_id,
                canonical_file=canonical_file,
                canonical=canonical,
                canonical_sha=canonical_sha,
                release_sha=release_sha,
                analysis_file=analysis_file,
            )
        except ProcessCpiError as exc:
            return _finish(
                result_file,
                _result(
                    status=exc.code,
                    event_id=event_id,
                    reference_period=reference_period,
                    canonical=canonical_artifact,
                    analysis=_artifact("invalid", analysis_file, root),
                    created_paths=created_paths,
                ),
            )
        return _finish(
            result_file,
            _result(
                status="ALREADY_PROCESSED",
                event_id=event_id,
                reference_period=reference_period,
                canonical=canonical_artifact,
                analysis=_artifact("existing", analysis_file, root),
            ),
        )

    run_analysis = analysis_runner or generate_cpi_analysis.analyze_from_files
    try:
        analysis_result = run_analysis(
            root,
            event_id,
            provider_name="rule_based",
            allow_rule_fallback=False,
        )
    except (
        generate_cpi_analysis.CpiAnalysisError,
        generate_cpi_analysis.AnalysisProviderError,
    ):
        return _finish(
            result_file,
            _result(
                status="ANALYSIS_FAILED",
                event_id=event_id,
                reference_period=reference_period,
                canonical=canonical_artifact,
                created_paths=created_paths,
            ),
        )
    if (
        analysis_result.status != "ANALYSIS_GENERATED"
        or analysis_result.provider_name != "rule_based"
        or analysis_result.external_api_called
        or analysis_result.api_calls != 0
    ):
        return _finish(
            result_file,
            _result(
                status="ANALYSIS_FAILED",
                event_id=event_id,
                reference_period=reference_period,
                canonical=canonical_artifact,
                created_paths=created_paths,
            ),
        )
    created_paths.append(relative_path(analysis_file, root))
    try:
        _validate_analysis_file(
            root=root,
            event_id=event_id,
            canonical_file=canonical_file,
            canonical=canonical,
            canonical_sha=canonical_sha,
            release_sha=release_sha,
            analysis_file=analysis_file,
        )
    except ProcessCpiError:
        return _finish(
            result_file,
            _result(
                status="ANALYSIS_FAILED",
                event_id=event_id,
                reference_period=reference_period,
                canonical=canonical_artifact,
                analysis=_artifact("invalid", analysis_file, root),
                created_paths=created_paths,
            ),
        )

    final_status = "CANONICAL_ONLY_RESUMED" if canonical_existed else "PROCESSED"
    return _finish(
        result_file,
        _result(
            status=final_status,
            event_id=event_id,
            reference_period=reference_period,
            canonical=canonical_artifact,
            analysis=_artifact("created", analysis_file, root),
            created_paths=created_paths,
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process a captured CPI release for free")
    parser.add_argument("--event-id", required=True)
    parser.add_argument(
        "--provider",
        choices=("rule_based", "github_models", "openai"),
        default=DEFAULT_PROVIDER,
    )
    parser.add_argument("--result-json")
    return parser.parse_args(argv)


def print_result(result: ProcessingResult) -> None:
    print(result.status)
    print(f"event_id: {result.event_id}")
    print(f"reference_period: {result.reference_period or 'none'}")
    print(f"provider: {result.provider}")
    print(f"external_api_called: {str(result.external_api_called).lower()}")
    print(f"canonical: {result.canonical['path'] or 'none'}")
    print(f"analysis: {result.analysis['path'] or 'none'}")
    print(f"created_paths: {len(result.created_paths)}")
    print(f"commit_paths: {len(result.commit_paths)}")
    print("cost_mode: free")
    print("API key checked: false")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = process_release(
            project_root(),
            args.event_id,
            provider=args.provider,
            result_json=args.result_json,
        )
    except ProcessCpiError as exc:
        print(exc.code)
        print(f"error: {exc.message}")
        print("external_api_called: false")
        print("API key checked: false")
        return 1
    print_result(result)
    return 0 if result.status in SUCCESS_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
