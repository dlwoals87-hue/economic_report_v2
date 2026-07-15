from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "analysis" / "generate_cpi_analysis.py"
SPEC = importlib.util.spec_from_file_location("generate_cpi_analysis_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load generate_cpi_analysis.py")
generate_cpi_analysis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_cpi_analysis
SPEC.loader.exec_module(generate_cpi_analysis)


EVENT_ID = "US_CPI_2026_06"


def decimal_plain(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def metric(actual, previous, expected=None):
    actual_decimal = Decimal(actual)
    payload = {
        "actual_as_released_raw": actual,
        "actual_as_released_display": f"{actual}%",
        "previous_as_released_raw": previous,
        "previous_as_released_display": f"{previous}%",
        "expected": expected,
        "unit": "%",
        "surprise": None,
    }
    if expected is not None:
        surprise = actual_decimal - Decimal(expected)
        direction = "above" if surprise > 0 else "below" if surprise < 0 else "inline"
        payload["surprise"] = {
            "raw": decimal_plain(surprise),
            "display": f"{surprise.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%p",
            "unit": "percentage_point",
            "direction": direction,
            "actual_raw": decimal_plain(actual_decimal),
            "expected_raw": decimal_plain(Decimal(expected)),
            "formula": "actual - expected",
        }
    return payload


def canonical_payload(expected_values=None):
    expected_values = expected_values or {}
    return {
        "schema_version": "1.0",
        "meta": {
            "event_id": EVENT_ID,
            "indicator_type": "CPI",
            "indicator_name": "미국 소비자물가지수",
            "country": "US",
            "reference_period": "2026-06",
            "release_datetime_utc": "2026-07-14T12:30:00Z",
            "release_datetime_kst": "2026-07-14T21:30:00+09:00",
            "is_sample": False,
            "data_origin": "bls_release_capture",
            "data_status": "release_captured",
            "analysis_status": "pending",
        },
        "event": {
            "headline": {
                "mom": metric("0.3", "0.5", expected_values.get("headline_mom")),
                "yoy": metric("2.9", "3.0", expected_values.get("headline_yoy")),
            },
            "core": {
                "mom": metric("0.2", "0.3", expected_values.get("core_mom")),
                "yoy": metric("3.1", "3.2", expected_values.get("core_yoy")),
            },
            "consensus": {"source": None, "status": "not_entered", "entered_at_utc": None},
        },
        "source": {
            "provider": "U.S. Bureau of Labor Statistics",
            "release_capture_path": f"data/releases/cpi/{EVENT_ID}/as_released.json",
            "release_capture_sha256": "release-sha-256-test",
            "release_vintage": "first_observed_after_release",
        },
        "analysis": {
            "status": "pending",
            "provider": None,
            "model": None,
            "generated_at_utc": None,
            "summary_html": None,
            "key_points": [],
        },
    }


def valid_analysis():
    return {
        "language": "ko",
        "executive_summary": {
            "one_line": "물가 흐름은 직전 발표보다 완만해졌다.",
            "detail": "헤드라인과 근원 흐름을 함께 보면 둔화 방향이다.",
        },
        "inflation_interpretation": {
            "headline": "헤드라인 물가는 직전 발표보다 둔화했다.",
            "core": "근원 물가도 직전 발표보다 둔화했다.",
            "momentum": "네 지표의 직전 발표 대비 방향이 모두 완만해졌다.",
        },
        "policy_implication": {
            "signal": "dovish",
            "explanation": "물가 압력 완화 방향이지만 예상치 정보가 없어 판단에는 한계가 있다.",
            "evidence_paths": ["facts.metrics.core_mom.momentum_direction"],
        },
        "key_points": [
            {
                "title": "헤드라인 월간 흐름",
                "detail": "직전 발표 대비 둔화 방향이다.",
                "evidence_paths": ["facts.metrics.headline_mom.momentum_direction"],
            },
            {
                "title": "헤드라인 연간 흐름",
                "detail": "직전 발표 대비 둔화 방향이다.",
                "evidence_paths": ["facts.metrics.headline_yoy.momentum_direction"],
            },
            {
                "title": "근원 흐름",
                "detail": "근원 지표도 직전 발표 대비 둔화 방향이다.",
                "evidence_paths": ["facts.metrics.core_mom.momentum_direction"],
            },
        ],
        "risks_and_caveats": ["예상치와 세부 구성 항목이 제공되지 않았다."],
        "unsupported_sections": [
            {"section": "market_reaction", "reason": "시장 가격 데이터가 없어 알 수 없음"}
        ],
        "confidence": "medium",
    }


def provider_result(analysis=None):
    return generate_cpi_analysis.openai_responses.OpenAIResponseResult(
        output=copy.deepcopy(analysis or valid_analysis()),
        response_id="resp_mock_123",
        model_requested="gpt-5.6-sol",
        model_returned="gpt-5.6-sol-2026-07-01",
        usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        api_calls=1,
    )


def canonical_path(root):
    return root / "data" / "generated" / "cpi" / EVENT_ID / "canonical_release.json"


def analysis_path(root):
    return root / "data" / "analysis" / "cpi" / EVENT_ID / "cpi-analysis-v1.json"


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class GenerateCpiAnalysisTests(unittest.TestCase):
    def run_temp(self, callback, *, canonical=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if canonical is not False:
                write_json(canonical_path(root), canonical or canonical_payload())
            return callback(root)

    def run_analysis(self, root, provider=None, **kwargs):
        provider = provider or mock.Mock(return_value=provider_result())
        provider_name = kwargs.pop("provider_name", "openai")
        allow_rule_fallback = kwargs.pop("allow_rule_fallback", False)
        result = generate_cpi_analysis.analyze_from_files(
            root,
            EVENT_ID,
            provider_name=provider_name,
            allow_rule_fallback=allow_rule_fallback,
            provider_call=provider,
            now_fn=lambda: datetime(2026, 7, 14, 12, 35, tzinfo=timezone.utc),
            **kwargs,
        )
        return result, provider

    def read_output(self, root):
        return json.loads(analysis_path(root).read_text(encoding="utf-8"))

    def test_missing_canonical_returns_not_found(self):
        def case(root):
            result, _ = self.run_analysis(root)
            self.assertEqual(result.status, "CANONICAL_RELEASE_NOT_FOUND")
            self.assertFalse(result.canonical_exists)
            self.assertFalse(analysis_path(root).exists())

        self.run_temp(case, canonical=False)

    def test_missing_canonical_calls_provider_zero_times(self):
        def case(root):
            provider = mock.Mock(return_value=provider_result())
            self.run_analysis(root, provider)
            provider.assert_not_called()

        self.run_temp(case, canonical=False)

    def test_missing_canonical_does_not_check_api_key(self):
        def case(root):
            def guarded_get(name, default=None):
                if name == "OPENAI_API_KEY":
                    raise AssertionError("API key must not be checked")
                return default

            with mock.patch.object(
                generate_cpi_analysis.openai_responses.os.environ,
                "get",
                side_effect=guarded_get,
            ):
                result = generate_cpi_analysis.analyze_from_files(root, EVENT_ID)
            self.assertFalse(result.api_key_checked)

        self.run_temp(case, canonical=False)

    def test_invalid_canonical_calls_provider_zero_times(self):
        payload = canonical_payload()
        payload["meta"]["country"] = "CA"

        def case(root):
            provider = mock.Mock(return_value=provider_result())
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError):
                self.run_analysis(root, provider)
            provider.assert_not_called()

        self.run_temp(case, canonical=payload)

    def test_event_id_mismatch_fails(self):
        payload = canonical_payload()
        payload["meta"]["event_id"] = "US_CPI_OTHER"

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError):
                self.run_analysis(root)

        self.run_temp(case, canonical=payload)

    def test_is_sample_true_fails(self):
        payload = canonical_payload()
        payload["meta"]["is_sample"] = True

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError):
                self.run_analysis(root)

        self.run_temp(case, canonical=payload)

    def test_data_origin_mismatch_fails(self):
        payload = canonical_payload()
        payload["meta"]["data_origin"] = "sample"

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError):
                self.run_analysis(root)

        self.run_temp(case, canonical=payload)

    def test_missing_one_metric_fails(self):
        payload = canonical_payload()
        del payload["event"]["core"]["yoy"]

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError):
                self.run_analysis(root)

        self.run_temp(case, canonical=payload)

    def test_actual_and_previous_map_exactly_to_facts(self):
        def case(root):
            _, provider = self.run_analysis(root)
            facts = provider.call_args.kwargs["facts"]
            self.assertEqual(facts["metrics"]["headline_mom"]["actual"], "0.3")
            self.assertEqual(facts["metrics"]["headline_mom"]["previous"], "0.5")
            self.assertEqual(facts["metrics"]["core_yoy"]["actual_display"], "3.1%")
            self.assertEqual(facts["metrics"]["core_yoy"]["previous_display"], "3.2%")

        self.run_temp(case)

    def test_change_from_previous_is_calculated_by_python(self):
        def case(root):
            _, provider = self.run_analysis(root)
            facts = provider.call_args.kwargs["facts"]
            self.assertEqual(facts["metrics"]["headline_mom"]["change_from_previous_raw"], "-0.2")
            self.assertEqual(facts["metrics"]["core_yoy"]["change_from_previous_raw"], "-0.1")

        self.run_temp(case)

    def test_momentum_direction_is_calculated(self):
        payload = canonical_payload()
        payload["event"]["headline"]["mom"] = metric("0.7", "0.5")
        payload["event"]["headline"]["yoy"] = metric("3.0", "3.0")

        def case(root):
            _, provider = self.run_analysis(root)
            metrics = provider.call_args.kwargs["facts"]["metrics"]
            self.assertEqual(metrics["headline_mom"]["momentum_direction"], "accelerating")
            self.assertEqual(metrics["headline_yoy"]["momentum_direction"], "unchanged")
            self.assertEqual(metrics["core_mom"]["momentum_direction"], "decelerating")

        self.run_temp(case, canonical=payload)

    def test_all_expected_values_make_consensus_available_true(self):
        payload = canonical_payload(
            {
                "headline_mom": "0.3",
                "headline_yoy": "2.9",
                "core_mom": "0.2",
                "core_yoy": "3.1",
            }
        )

        def case(root):
            analysis = valid_analysis()
            analysis["confidence"] = "high"
            _, provider = self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertTrue(provider.call_args.kwargs["facts"]["consensus_available"])

        self.run_temp(case, canonical=payload)

    def test_partial_expected_values_make_consensus_available_false(self):
        payload = canonical_payload({"headline_mom": "0.3"})

        def case(root):
            _, provider = self.run_analysis(root)
            self.assertFalse(provider.call_args.kwargs["facts"]["consensus_available"])

        self.run_temp(case, canonical=payload)

    def test_canonical_surprise_is_preserved_after_recalculation(self):
        payload = canonical_payload({"headline_mom": "0.1"})

        def case(root):
            _, provider = self.run_analysis(root)
            surprise = provider.call_args.kwargs["facts"]["metrics"]["headline_mom"]["surprise"]
            self.assertEqual(surprise, payload["event"]["headline"]["mom"]["surprise"])

        self.run_temp(case, canonical=payload)

    def test_surprise_mismatch_fails_without_provider_call(self):
        payload = canonical_payload({"headline_mom": "0.1"})
        payload["event"]["headline"]["mom"]["surprise"]["raw"] = "9.9"

        def case(root):
            provider = mock.Mock(return_value=provider_result())
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, provider)
            self.assertEqual(caught.exception.code, "CANONICAL_SURPRISE_MISMATCH")
            provider.assert_not_called()

        self.run_temp(case, canonical=payload)

    def test_normal_mock_response_is_saved(self):
        def case(root):
            result, _ = self.run_analysis(root)
            self.assertEqual(result.status, "ANALYSIS_GENERATED")
            self.assertTrue(result.analysis_created)
            output = self.read_output(root)
            self.assertEqual(output["analysis"]["language"], "ko")
            self.assertEqual(output["provider"]["response_id"], "resp_mock_123")

        self.run_temp(case)

    def test_provider_cannot_mutate_saved_facts(self):
        def case(root):
            def provider(**kwargs):
                kwargs["facts"]["metrics"]["headline_mom"]["actual"] = "999"
                return provider_result()

            self.run_analysis(root, provider)
            self.assertEqual(self.read_output(root)["facts"]["metrics"]["headline_mom"]["actual"], "0.3")

        self.run_temp(case)

    def test_valid_evidence_paths_pass(self):
        def case(root):
            self.run_analysis(root)
            self.assertTrue(self.read_output(root)["validation"]["evidence_paths_valid"])

        self.run_temp(case)

    def test_nonexistent_evidence_path_is_rejected(self):
        analysis = valid_analysis()
        analysis["key_points"][0]["evidence_paths"] = ["facts.metrics.headline_mom.not_real"]

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "INVALID_EVIDENCE_PATH")
            self.assertFalse(analysis_path(root).exists())

        self.run_temp(case)

    def test_allowed_percentage_token_passes(self):
        analysis = valid_analysis()
        analysis["executive_summary"]["one_line"] = "헤드라인 월간 실제값은 0.3%다."

        def case(root):
            self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertTrue(analysis_path(root).exists())

        self.run_temp(case)

    def test_unsupported_percentage_token_is_rejected(self):
        analysis = valid_analysis()
        analysis["executive_summary"]["one_line"] = "헤드라인 월간 실제값은 9.9%다."

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "UNSUPPORTED_NUMERIC_CLAIM")

        self.run_temp(case)

    def test_allowed_percentage_point_token_passes(self):
        payload = canonical_payload({"headline_mom": "0.1"})
        analysis = valid_analysis()
        analysis["executive_summary"]["one_line"] = "입력상 차이는 0.2%p다."

        def case(root):
            self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertTrue(analysis_path(root).exists())

        self.run_temp(case, canonical=payload)

    def test_unsupported_percentage_point_token_is_rejected(self):
        analysis = valid_analysis()
        analysis["executive_summary"]["one_line"] = "입력상 차이는 8.8%p다."

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "UNSUPPORTED_NUMERIC_CLAIM")

        self.run_temp(case)

    def test_consensus_claim_without_expected_is_rejected(self):
        analysis = valid_analysis()
        analysis["executive_summary"]["one_line"] = "물가가 예상 상회했다."

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "UNSUPPORTED_CONSENSUS_CLAIM")

        self.run_temp(case)

    def test_unsupported_stock_rise_claim_is_rejected(self):
        analysis = valid_analysis()
        analysis["key_points"][0]["detail"] = "발표 뒤 주가가 상승했다."

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "UNSUPPORTED_MARKET_CLAIM")

        self.run_temp(case)

    def test_unsupported_treasury_yield_fall_claim_is_rejected(self):
        analysis = valid_analysis()
        analysis["inflation_interpretation"]["momentum"] = "미국 국채금리가 하락했다."

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "UNSUPPORTED_MARKET_CLAIM")

        self.run_temp(case)

    def test_data_absence_explanation_in_unsupported_sections_is_allowed(self):
        analysis = valid_analysis()
        analysis["unsupported_sections"][0]["reason"] = "주가가 상승했는지는 데이터가 없어 알 수 없음"

        def case(root):
            self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertTrue(analysis_path(root).exists())

        self.run_temp(case)

    def test_refusal_creates_no_file(self):
        def case(root):
            provider = mock.Mock(
                side_effect=generate_cpi_analysis.openai_responses.OpenAIResponsesError(
                    "MODEL_REFUSAL", "the model refused", attempts=1
                )
            )
            with self.assertRaises(generate_cpi_analysis.AnalysisProviderError):
                self.run_analysis(root, provider, allow_rule_fallback=False)
            self.assertFalse(analysis_path(root).exists())

        self.run_temp(case)

    def test_api_error_creates_no_file(self):
        def case(root):
            provider = mock.Mock(
                side_effect=generate_cpi_analysis.openai_responses.OpenAIResponsesError(
                    "RATE_LIMITED", "rate limited", attempts=2
                )
            )
            with self.assertRaises(generate_cpi_analysis.AnalysisProviderError):
                self.run_analysis(root, provider, allow_rule_fallback=False)
            self.assertFalse(analysis_path(root).exists())

        self.run_temp(case)

    def test_output_outside_project_is_rejected(self):
        def case(root):
            outside = Path(tempfile.gettempdir()) / "outside-cpi-analysis.json"
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, output_path=str(outside))
            self.assertEqual(caught.exception.code, "INVALID_PATH")

        self.run_temp(case)

    def test_parent_directory_output_is_rejected(self):
        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, output_path="../outside.json")
            self.assertEqual(caught.exception.code, "INVALID_PATH")

        self.run_temp(case)

    def test_existing_output_returns_already_analyzed(self):
        def case(root):
            write_json(analysis_path(root), {"existing": True})
            provider = mock.Mock(return_value=provider_result())
            result, _ = self.run_analysis(root, provider)
            self.assertEqual(result.status, "ALREADY_ANALYZED")
            provider.assert_not_called()

        self.run_temp(case)

    def test_existing_output_is_not_overwritten(self):
        def case(root):
            write_json(analysis_path(root), {"existing": True})
            before = analysis_path(root).read_bytes()
            self.run_analysis(root)
            self.assertEqual(before, analysis_path(root).read_bytes())

        self.run_temp(case)

    def test_api_key_is_not_saved_to_output(self):
        def case(root):
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "SECRET_ANALYSIS_KEY"}, clear=False):
                self.run_analysis(root)
            self.assertNotIn("SECRET_ANALYSIS_KEY", analysis_path(root).read_text(encoding="utf-8"))

        self.run_temp(case)

    def test_windows_absolute_path_is_not_saved(self):
        def case(root):
            self.run_analysis(root)
            serialized = analysis_path(root).read_text(encoding="utf-8")
            self.assertNotIn(str(root), serialized)
            self.assertEqual(
                self.read_output(root)["input"]["canonical_path"],
                f"data/generated/cpi/{EVENT_ID}/canonical_release.json",
            )

        self.run_temp(case)

    def test_prompt_sha256_is_saved(self):
        def case(root):
            self.run_analysis(root)
            expected = hashlib.sha256((ROOT / "prompts" / "cpi_analysis_v1.md").read_bytes()).hexdigest()
            self.assertEqual(self.read_output(root)["versions"]["prompt_sha256"], expected)

        self.run_temp(case)

    def test_schema_sha256_is_saved(self):
        def case(root):
            self.run_analysis(root)
            expected = hashlib.sha256(
                (ROOT / "schemas" / "cpi_analysis_v1.schema.json").read_bytes()
            ).hexdigest()
            self.assertEqual(self.read_output(root)["versions"]["schema_sha256"], expected)

        self.run_temp(case)

    def test_canonical_sha256_is_saved(self):
        def case(root):
            expected = hashlib.sha256(canonical_path(root).read_bytes()).hexdigest()
            self.run_analysis(root)
            self.assertEqual(self.read_output(root)["input"]["canonical_sha256"], expected)

        self.run_temp(case)

    def test_raw_chain_of_thought_is_not_saved(self):
        def case(root):
            self.run_analysis(root)
            serialized = analysis_path(root).read_text(encoding="utf-8").lower()
            self.assertNotIn("chain-of-thought", serialized)
            self.assertNotIn("raw reasoning", serialized)
            self.assertNotIn("reasoning_content", serialized)

        self.run_temp(case)

    def test_no_fixture_is_left_in_project_data_analysis(self):
        event_id = "US_CPI_TEST_FIXTURE_3_7"

        def case(root):
            self.run_analysis(root)
            self.assertFalse((ROOT / "data" / "analysis" / "cpi" / event_id).exists())

        self.run_temp(case)

    def test_schema_rejects_additional_properties(self):
        analysis = valid_analysis()
        analysis["unexpected"] = "not allowed"

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "ANALYSIS_SCHEMA_INVALID")

        self.run_temp(case)

    def test_duplicate_evidence_paths_are_rejected_within_one_array(self):
        analysis = valid_analysis()
        path = "facts.metrics.core_mom.momentum_direction"
        analysis["policy_implication"]["evidence_paths"] = [path, path]

        def case(root):
            with self.assertRaises(generate_cpi_analysis.CpiAnalysisError) as caught:
                self.run_analysis(root, mock.Mock(return_value=provider_result(analysis)))
            self.assertEqual(caught.exception.code, "INVALID_EVIDENCE_PATH")

        self.run_temp(case)


if __name__ == "__main__":
    unittest.main()
