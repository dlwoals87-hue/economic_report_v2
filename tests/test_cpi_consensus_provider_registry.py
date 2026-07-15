from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.consensus import cpi_provider_registry as registry


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "config" / "cpi_consensus_providers.json"


class CpiConsensusProviderRegistryTests(unittest.TestCase):
    def setUp(self): self.payload = registry.load_registry(PATH)
    def test_01_registry_schema_is_valid(self): registry.validate_registry(self.payload)
    def test_02_no_provider_is_approved(self): self.assertEqual(registry.approved_providers(self.payload), [])
    def test_02b_qualification_status_is_no_approved_provider(self): self.assertEqual(registry.qualification_status(self.payload), "NO_APPROVED_PROVIDER")
    def test_03_only_approved_provider_can_be_selected(self):
        for provider in self.payload["providers"]: self.assertNotEqual(provider["status"], "APPROVED")
    def test_04_paid_provider_is_not_approved(self):
        value=copy.deepcopy(self.payload); item=value["providers"][0]; item.update({"status":"APPROVED","requires_paid_plan":True,"supports_metrics":True,"allows_snapshot_storage":True,"allows_public_display":True,"allows_derived_results":True,"requires_display_license":False})
        with self.assertRaises(registry.ProviderRegistryError): registry.validate_registry(value)
    def test_05_display_license_requirement_blocks_approval(self):
        value=copy.deepcopy(self.payload); item=value["providers"][0]; item.update({"status":"APPROVED","supports_metrics":True,"supports_pre_release":True,"allows_snapshot_storage":True,"allows_public_display":True,"allows_derived_results":True,"requires_paid_plan":False,"requires_display_license":True})
        with self.assertRaises(registry.ProviderRegistryError): registry.validate_registry(value)
    def test_06_missing_storage_blocks_approval(self):
        value=copy.deepcopy(self.payload); item=value["providers"][0]; item.update({"status":"APPROVED","supports_metrics":True,"supports_pre_release":True,"allows_snapshot_storage":False,"allows_public_display":True,"allows_derived_results":True,"requires_paid_plan":False,"requires_display_license":False})
        with self.assertRaises(registry.ProviderRegistryError): registry.validate_registry(value)
    def test_07_duplicate_provider_is_rejected(self):
        value=copy.deepcopy(self.payload); value["providers"].append(copy.deepcopy(value["providers"][0]))
        with self.assertRaises(registry.ProviderRegistryError): registry.validate_registry(value)
    def test_08_unknown_status_is_rejected(self):
        value=copy.deepcopy(self.payload); value["providers"][0]["status"]="MAYBE"
        with self.assertRaises(registry.ProviderRegistryError): registry.validate_registry(value)
    def test_09_credentials_are_absent(self):
        text=PATH.read_text(encoding="utf-8").lower()
        for token in ("api_key", "api token", "password", "secret", "authorization"): self.assertNotIn(token,text)
    def test_10_no_adapter_exists_without_approved_provider(self):
        self.assertFalse((ROOT / "scripts/consensus/providers").exists())


if __name__ == "__main__": unittest.main()
