from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.pipelines import build_ppi_historical_canonical as canonical_module


class PpiAnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _direction(raw: str) -> str:
    value = Decimal(raw)
    return "positive" if value > 0 else "negative" if value < 0 else "flat"


def build_analysis(canonical: dict[str, Any], event_id: str, now: datetime) -> dict[str, Any]:
    canonical_module.validate_canonical(canonical, event_id)
    metrics = canonical["metrics"]
    headline_mom = metrics["headline_mom"]
    headline_yoy = metrics["headline_yoy"]
    core_mom = metrics["core_mom"]
    core_yoy = metrics["core_yoy"]
    summary = (
        f"PPI headline MoM {headline_mom['actual_display']} and YoY {headline_yoy['actual_display']}; "
        f"core MoM {core_mom['actual_display']} and YoY {core_yoy['actual_display']} in this current API historical snapshot."
    )
    analysis = {
        "summary": summary,
        "headline": f"Headline PPI is { _direction(headline_mom['actual_raw']) } MoM and { _direction(headline_yoy['actual_raw']) } YoY.",
        "core": "Core PPI is final demand less foods, energy, and trade services; it is reported separately from headline PPI.",
        "pressure": "The headline-core difference is descriptive producer-price information, not a complete measure of inflation transmission.",
        "limitations": [
            "No consensus snapshot is available, so above- or below-expectations judgement is unavailable.",
            "Market, rate, and asset-reaction data are unavailable in this rehearsal.",
            "PPI alone does not establish a CPI outcome or a Federal Reserve decision.",
            "This is a current API historical snapshot, not a release-time captured value and may reflect revisions.",
        ],
    }
    return {
        "schema_version": "1.0", "event_id": event_id, "indicator_type": "PPI",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input": {"canonical_sha256": canonical["integrity"]["sha256"], "historical_observation_sha256": canonical["source"]["historical_observation_sha256"]},
        "provider": {"name": "rule_based", "external_ai_api_called": False},
        "usage": {"cost": "free", "api_calls": 0}, "analysis": analysis,
    }


def analyze_file(canonical_path: Path, output_path: Path, event_id: str, now: datetime) -> dict[str, Any]:
    try:
        data = canonical_path.read_bytes()
        canonical = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PpiAnalysisError("PPI_CANONICAL_INVALID", "canonical JSON is unreadable") from exc
    if not isinstance(canonical, dict):
        raise PpiAnalysisError("PPI_CANONICAL_INVALID", "canonical JSON must be an object")
    result = build_analysis(canonical, event_id, now)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if output_path.exists():
        if output_path.read_bytes() == encoded:
            return result
        raise PpiAnalysisError("PPI_ANALYSIS_CONFLICT", "analysis output differs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    return result
