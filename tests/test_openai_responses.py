from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import urllib.error
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "providers" / "openai_responses.py"
SPEC = importlib.util.spec_from_file_location("openai_responses_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load openai_responses.py")
openai_responses = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = openai_responses
SPEC.loader.exec_module(openai_responses)


class FakeResponse:
    def __init__(self, payload, *, raw=False):
        self.data = payload if raw else json.dumps(payload).encode("utf-8")

    def read(self):
        return self.data


def api_payload(output=None, *, status="completed"):
    return {
        "id": "resp_test_123",
        "model": "gpt-test-returned",
        "status": status,
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"language": "ko"}),
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    }


def http_error(status, body=b"error"):
    return urllib.error.HTTPError(
        openai_responses.RESPONSES_ENDPOINT,
        status,
        "error",
        None,
        io.BytesIO(body),
    )


class OpenAIResponsesTests(unittest.TestCase):
    def setUp(self):
        self.facts = {"event_id": "US_CPI_TEST"}
        self.schema = {
            "type": "object",
            "properties": {"language": {"type": "string"}},
            "required": ["language"],
            "additionalProperties": False,
        }
        self.instructions = "facts only"

    def call(self, opener, sleep_fn=None):
        kwargs = {
            "facts": self.facts,
            "instructions": self.instructions,
            "schema": self.schema,
            "opener": opener,
        }
        if sleep_fn is not None:
            kwargs["sleep_fn"] = sleep_fn
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-secret-key", "OPENAI_MODEL": "gpt-test-requested"},
            clear=True,
        ):
            return openai_responses.generate_structured_analysis(**kwargs)

    def capture_request(self):
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return FakeResponse(api_payload())

        result = self.call(opener)
        return result, captured[0]

    def test_responses_api_endpoint_is_used(self):
        _, (request, _) = self.capture_request()
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")

    def test_post_request_is_used(self):
        _, (request, _) = self.capture_request()
        self.assertEqual(request.get_method(), "POST")

    def test_authorization_bearer_header_is_set(self):
        _, (request, _) = self.capture_request()
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret-key")

    def test_api_key_is_not_in_payload_or_result(self):
        result, (request, _) = self.capture_request()
        self.assertNotIn(b"test-secret-key", request.data)
        self.assertNotIn("test-secret-key", repr(result))

    def test_store_is_false(self):
        _, (request, _) = self.capture_request()
        payload = json.loads(request.data)
        self.assertIs(payload["store"], False)

    def test_reasoning_effort_is_high(self):
        _, (request, _) = self.capture_request()
        payload = json.loads(request.data)
        self.assertEqual(payload["reasoning"], {"effort": "high"})

    def test_text_format_is_json_schema(self):
        _, (request, _) = self.capture_request()
        payload = json.loads(request.data)
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(payload["text"]["format"]["schema"], self.schema)

    def test_strict_is_true(self):
        _, (request, _) = self.capture_request()
        payload = json.loads(request.data)
        self.assertIs(payload["text"]["format"]["strict"], True)

    def test_no_tools_are_requested(self):
        _, (request, _) = self.capture_request()
        payload = json.loads(request.data)
        self.assertNotIn("tools", payload)
        self.assertNotIn("web_search", json.dumps(payload))
        self.assertNotIn("file_search", json.dumps(payload))

    def test_normal_output_text_is_extracted(self):
        result = self.call(lambda request, timeout: FakeResponse(api_payload()))
        self.assertEqual(result.output, {"language": "ko"})
        self.assertEqual(result.response_id, "resp_test_123")
        self.assertEqual(result.model_returned, "gpt-test-returned")

    def test_refusal_is_detected(self):
        output = [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]
        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(lambda request, timeout: FakeResponse(api_payload(output)))
        self.assertEqual(caught.exception.code, "MODEL_REFUSAL")

    def test_incomplete_response_is_detected(self):
        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(lambda request, timeout: FakeResponse(api_payload(status="incomplete")))
        self.assertEqual(caught.exception.code, "INCOMPLETE_RESPONSE")

    def test_missing_output_text_is_detected(self):
        output = [{"type": "message", "content": []}]
        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(lambda request, timeout: FakeResponse(api_payload(output)))
        self.assertEqual(caught.exception.code, "STRUCTURED_OUTPUT_MISSING")

    def test_conflicting_output_text_is_detected(self):
        output = [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"language":"ko"}'},
                    {"type": "output_text", "text": '{"language":"en"}'},
                ],
            }
        ]
        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(lambda request, timeout: FakeResponse(api_payload(output)))
        self.assertEqual(caught.exception.code, "STRUCTURED_OUTPUT_MISSING")

    def test_malformed_api_json_is_detected(self):
        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(lambda request, timeout: FakeResponse(b"not-json", raw=True))
        self.assertEqual(caught.exception.code, "INVALID_API_RESPONSE")

    def test_http_401_is_authentication_failed(self):
        def opener(request, timeout):
            raise http_error(401)

        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(opener)
        self.assertEqual(caught.exception.code, "AUTHENTICATION_FAILED")
        self.assertEqual(caught.exception.attempts, 1)

    def test_http_429_retries_at_most_once(self):
        calls = []
        sleep = mock.Mock()

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise http_error(429)
            return FakeResponse(api_payload())

        result = self.call(opener, sleep)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.api_calls, 2)
        sleep.assert_called_once()

    def test_http_500_retries_at_most_once(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise http_error(500)

        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(opener, mock.Mock())
        self.assertEqual(caught.exception.code, "TRANSIENT_API_ERROR")
        self.assertEqual(len(calls), 2)

    def test_http_400_is_not_retried(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise http_error(400)

        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(opener, mock.Mock())
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertEqual(len(calls), 1)

    def test_total_calls_never_exceed_two(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise http_error(503)

        with self.assertRaises(openai_responses.OpenAIResponsesError):
            self.call(opener, mock.Mock())
        self.assertEqual(len(calls), 2)

    def test_api_key_in_error_message_is_redacted(self):
        def opener(request, timeout):
            raise http_error(401, b"rejected test-secret-key Authorization: Bearer test-secret-key")

        with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
            self.call(opener)
        message = str(caught.exception)
        self.assertNotIn("test-secret-key", message)
        self.assertIn("[REDACTED]", message)

    def test_missing_api_key_has_classified_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(openai_responses.OpenAIResponsesError) as caught:
                openai_responses.generate_structured_analysis(
                    facts=self.facts,
                    instructions=self.instructions,
                    schema=self.schema,
                    opener=mock.Mock(),
                )
        self.assertEqual(caught.exception.code, "OPENAI_API_KEY_MISSING")
        self.assertEqual(caught.exception.attempts, 0)

    def test_common_provider_adapter_preserves_openai_metadata(self):
        legacy = openai_responses.OpenAIResponseResult(
            output={"language": "ko"},
            response_id="resp_adapter_test",
            model_requested="gpt-test-requested",
            model_returned="gpt-test-returned",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            api_calls=1,
        )
        with mock.patch.object(
            openai_responses,
            "generate_structured_analysis",
            return_value=legacy,
        ):
            result = openai_responses.generate_analysis(
                facts=self.facts,
                instructions=self.instructions,
                schema=self.schema,
            )
        self.assertEqual(result.provider_name, "openai")
        self.assertEqual(result.analysis, {"language": "ko"})
        self.assertTrue(result.external_api_called)
        self.assertEqual(result.response_id, "resp_adapter_test")


if __name__ == "__main__":
    unittest.main()
