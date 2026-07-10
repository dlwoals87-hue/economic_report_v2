from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.analysis import generate_cpi_analysis
from scripts.providers import github_models
from scripts.providers.base import AnalysisProviderError, AnalysisProviderResult
from tests.test_generate_cpi_analysis import (
    EVENT_ID,
    analysis_path,
    canonical_path,
    canonical_payload,
    valid_analysis,
    write_json,
)
from tests.test_rule_based_analysis import make_facts


class AnalysisProviderSelectionTests(unittest.TestCase):
    def run_temp(self, callback):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(canonical_path(root), canonical_payload())
            return callback(root)

    def analyze(self, root, **kwargs):
        return generate_cpi_analysis.analyze_from_files(
            root,
            EVENT_ID,
            now_fn=lambda: datetime(2026, 7, 14, 12, 35, tzinfo=timezone.utc),
            **kwargs,
        )

    def read_output(self, root):
        return json.loads(analysis_path(root).read_text(encoding="utf-8"))

    def test_unspecified_provider_defaults_to_rule_based(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(generate_cpi_analysis.select_provider(), "rule_based")

    def test_openai_key_does_not_auto_select_openai(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "unused-secret"}, clear=True):
            self.assertEqual(generate_cpi_analysis.select_provider(), "rule_based")

    def test_cli_provider_has_priority_over_environment(self):
        with mock.patch.dict(os.environ, {"ANALYSIS_PROVIDER": "openai"}, clear=True):
            self.assertEqual(
                generate_cpi_analysis.select_provider("github_models"),
                "github_models",
            )

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
            generate_cpi_analysis.select_provider("unknown")
        self.assertEqual(caught.exception.code, "UNKNOWN_ANALYSIS_PROVIDER")

    def test_cli_fallback_defaults_to_true_and_can_be_disabled(self):
        enabled = generate_cpi_analysis.parse_args(["--event-id", EVENT_ID])
        disabled = generate_cpi_analysis.parse_args(
            ["--event-id", EVENT_ID, "--no-rule-fallback"]
        )
        self.assertTrue(enabled.allow_rule_fallback)
        self.assertFalse(disabled.allow_rule_fallback)

    def test_github_models_without_token_has_classified_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AnalysisProviderError) as caught:
                github_models.generate_analysis(
                    facts=make_facts(),
                    instructions="facts only",
                    schema={},
                )
        self.assertEqual(caught.exception.code, "GITHUB_MODELS_TOKEN_MISSING")
        self.assertFalse(caught.exception.external_api_called)

    def test_github_models_missing_token_falls_back_to_rule_based(self):
        def case(root):
            with mock.patch.dict(os.environ, {}, clear=True):
                result = self.analyze(root, provider_name="github_models")
            output = self.read_output(root)
            self.assertEqual(result.provider_name, "rule_based")
            self.assertTrue(result.fallback_used)
            self.assertEqual(result.fallback_reason, "GITHUB_MODELS_TOKEN_MISSING")
            self.assertFalse(result.external_api_called)
            self.assertEqual(output["provider"]["requested_provider"], "github_models")

        self.run_temp(case)

    def test_github_models_rate_limit_falls_back_to_rule_based(self):
        def case(root):
            provider = mock.Mock(
                side_effect=AnalysisProviderError(
                    "RATE_LIMITED",
                    "free quota reached",
                    external_api_called=True,
                    api_calls=1,
                    model_requested="configured-free-model",
                )
            )
            result = self.analyze(
                root,
                provider_name="github_models",
                provider_call=provider,
            )
            metadata = self.read_output(root)["provider"]
            self.assertEqual(result.provider_name, "rule_based")
            self.assertTrue(result.external_api_called)
            self.assertEqual(metadata["fallback_reason"], "RATE_LIMITED")
            self.assertEqual(metadata["model_requested"], "configured-free-model")

        self.run_temp(case)

    def test_github_models_network_error_falls_back_to_rule_based(self):
        def case(root):
            provider = mock.Mock(
                side_effect=AnalysisProviderError(
                    "NETWORK_ERROR",
                    "network unavailable",
                    external_api_called=True,
                    api_calls=1,
                )
            )
            result = self.analyze(
                root,
                provider_name="github_models",
                provider_call=provider,
            )
            self.assertEqual(result.fallback_reason, "NETWORK_ERROR")
            self.assertTrue(analysis_path(root).exists())

        self.run_temp(case)

    def test_invalid_external_response_falls_back_after_post_validation(self):
        invalid = valid_analysis()
        invalid["executive_summary"]["one_line"] = "입력에 없는 값은 9.9%다."
        external_result = AnalysisProviderResult(
            provider_name="github_models",
            model_requested="configured-free-model",
            model_returned="configured-free-model",
            response_id="mock-response",
            analysis=invalid,
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            external_api_called=True,
            api_calls=1,
        )

        def case(root):
            result = self.analyze(
                root,
                provider_name="github_models",
                provider_call=mock.Mock(return_value=external_result),
            )
            self.assertEqual(result.provider_name, "rule_based")
            self.assertEqual(result.fallback_reason, "UNSUPPORTED_NUMERIC_CLAIM")
            self.assertEqual(self.read_output(root)["usage"]["total_tokens"], 0)

        self.run_temp(case)

    def test_fallback_disabled_returns_clear_provider_error(self):
        def case(root):
            provider = mock.Mock(
                side_effect=AnalysisProviderError(
                    "RATE_LIMITED",
                    "free quota reached",
                    external_api_called=True,
                    api_calls=1,
                )
            )
            with self.assertRaises(AnalysisProviderError) as caught:
                self.analyze(
                    root,
                    provider_name="github_models",
                    allow_rule_fallback=False,
                    provider_call=provider,
                )
            self.assertEqual(caught.exception.code, "RATE_LIMITED")
            self.assertFalse(analysis_path(root).exists())

        self.run_temp(case)

    def test_openai_is_not_called_before_explicit_selection(self):
        def case(root):
            with mock.patch.object(
                generate_cpi_analysis.openai_responses,
                "generate_analysis",
                side_effect=AssertionError("OpenAI must not be called"),
            ) as openai_call:
                result = self.analyze(root)
            openai_call.assert_not_called()
            self.assertEqual(result.provider_name, "rule_based")
            self.assertFalse(result.external_api_called)

        self.run_temp(case)

    def test_explicit_openai_without_key_falls_back_to_rule_based(self):
        def case(root):
            with mock.patch.dict(os.environ, {}, clear=True):
                result = self.analyze(root, provider_name="openai")
            self.assertEqual(result.provider_name, "rule_based")
            self.assertEqual(result.requested_provider, "openai")
            self.assertEqual(result.fallback_reason, "OPENAI_API_KEY_MISSING")
            self.assertFalse(result.external_api_called)
            self.assertTrue(result.api_key_checked)

        self.run_temp(case)

    def test_api_keys_and_tokens_are_not_saved(self):
        def case(root):
            values = {
                "OPENAI_API_KEY": "SECRET_OPENAI_VALUE",
                "GITHUB_TOKEN": "SECRET_GITHUB_VALUE",
            }
            with mock.patch.dict(os.environ, values, clear=True):
                self.analyze(root)
            serialized = analysis_path(root).read_text(encoding="utf-8")
            self.assertNotIn("SECRET_OPENAI_VALUE", serialized)
            self.assertNotIn("SECRET_GITHUB_VALUE", serialized)

        self.run_temp(case)

    def test_rule_based_provider_metadata_is_exact(self):
        def case(root):
            result = self.analyze(root, provider_name="rule_based")
            metadata = self.read_output(root)["provider"]
            self.assertEqual(
                metadata,
                {
                    "name": "rule_based",
                    "requested_provider": "rule_based",
                    "model_requested": None,
                    "model_returned": None,
                    "response_id": None,
                    "external_api_called": False,
                    "fallback_used": False,
                    "fallback_reason": None,
                },
            )
            self.assertEqual(result.api_calls, 0)

        self.run_temp(case)

    def test_github_models_has_no_guessed_endpoint_or_model_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(github_models.configured_endpoint())
            self.assertIsNone(github_models.configured_model())

    def test_github_models_mock_transport_builds_and_parses_without_real_network(self):
        transport = mock.Mock(
            return_value={
                "id": "github-models-mock-response",
                "model": "configured-free-model",
                "choices": [
                    {"message": {"content": json.dumps(valid_analysis(), ensure_ascii=False)}}
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }
        )
        env = {
            "GITHUB_TOKEN": "mock-github-token",
            "GITHUB_MODELS_MODEL": "configured-free-model",
            "GITHUB_MODELS_ENDPOINT": "https://configured.invalid/models",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            result = github_models.generate_analysis(
                facts=make_facts(),
                instructions="facts only",
                schema={"type": "object"},
                transport=transport,
            )
        request = transport.call_args.kwargs
        self.assertEqual(result.provider_name, "github_models")
        self.assertTrue(result.external_api_called)
        self.assertNotIn("mock-github-token", json.dumps(request["payload"]))
        self.assertEqual(request["headers"]["Authorization"], "Bearer mock-github-token")

    def test_github_models_transport_error_redacts_token(self):
        token = "SECRET_GITHUB_TRANSPORT_TOKEN"
        env = {
            "GITHUB_TOKEN": token,
            "GITHUB_MODELS_MODEL": "configured-free-model",
            "GITHUB_MODELS_ENDPOINT": "https://configured.invalid/models",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(AnalysisProviderError) as caught:
                github_models.generate_analysis(
                    facts=make_facts(),
                    instructions="facts only",
                    schema={},
                    transport=mock.Mock(side_effect=OSError(f"network failed for {token}")),
                )
        self.assertNotIn(token, str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
