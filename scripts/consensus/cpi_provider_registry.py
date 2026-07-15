"""Validate the offline CPI consensus provider qualification registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATUSES = {
    "APPROVED", "REJECTED_PAID", "REJECTED_TRIAL_ONLY", "REJECTED_NO_PUBLIC_DISPLAY",
    "REJECTED_NO_REDISTRIBUTION", "REJECTED_NO_STORAGE", "REJECTED_INCOMPLETE_METRICS",
    "REJECTED_NO_PRE_RELEASE_VALUES", "REJECTED_UNDOCUMENTED_API", "REVIEW_REQUIRED", "UNAVAILABLE",
}
REQUIRED = {
    "provider_id", "status", "evaluated_at_utc", "contract_version", "supports_metrics",
    "supports_pre_release", "allows_snapshot_storage", "allows_public_display",
    "allows_derived_results", "requires_paid_plan", "requires_display_license",
    "official_documentation_urls",
}


class ProviderRegistryError(ValueError):
    pass


def validate_registry(payload: dict[str, Any]) -> None:
    if set(payload) != {"schema_version", "providers"} or payload.get("schema_version") != "cpi-consensus-provider-registry-v1":
        raise ProviderRegistryError("registry schema is invalid")
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ProviderRegistryError("providers must be a non-empty array")
    identifiers: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict) or set(provider) != REQUIRED:
            raise ProviderRegistryError("provider fields are invalid")
        provider_id = provider.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id or provider_id in identifiers:
            raise ProviderRegistryError("provider_id is invalid or duplicate")
        identifiers.add(provider_id)
        if provider.get("status") not in STATUSES:
            raise ProviderRegistryError("provider status is invalid")
        if not isinstance(provider.get("evaluated_at_utc"), str) or not provider["evaluated_at_utc"].endswith("Z"):
            raise ProviderRegistryError("evaluated_at_utc is invalid")
        if provider.get("contract_version") != "cpi-consensus-observation-v1":
            raise ProviderRegistryError("contract version is invalid")
        for key in REQUIRED - {"provider_id", "status", "evaluated_at_utc", "contract_version", "official_documentation_urls"}:
            if not isinstance(provider.get(key), bool):
                raise ProviderRegistryError(f"{key} must be boolean")
        urls = provider.get("official_documentation_urls")
        if not isinstance(urls, list) or not urls or not all(isinstance(url, str) and url.startswith("https://") for url in urls):
            raise ProviderRegistryError("official_documentation_urls are invalid")
        if provider["status"] == "APPROVED" and not all((provider["supports_metrics"], provider["supports_pre_release"], provider["allows_snapshot_storage"], provider["allows_public_display"], provider["allows_derived_results"], not provider["requires_paid_plan"], not provider["requires_display_license"])):
            raise ProviderRegistryError("APPROVED provider does not satisfy hard gates")


def approved_providers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    validate_registry(payload)
    return [provider for provider in payload["providers"] if provider["status"] == "APPROVED"]


def qualification_status(payload: dict[str, Any]) -> str:
    return "APPROVED_PROVIDER_AVAILABLE" if approved_providers(payload) else "NO_APPROVED_PROVIDER"


def load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderRegistryError("registry JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ProviderRegistryError("registry root must be an object")
    validate_registry(payload)
    return payload
