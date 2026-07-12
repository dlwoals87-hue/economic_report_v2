import contextlib
import io
import json
import socket
import unittest
from decimal import Decimal
from urllib.parse import urlsplit

from scripts.providers import trading_economics_calendar as te


class Headers(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0]


class Response:
    def __init__(self, body=b"[]", *, status=200, content_type="application/json", url=te.ORIGIN):
        self._body = body
        self.status = status
        self.headers = Headers({"Content-Type": content_type})
        self._url = url
        self.read_limit = None

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self, limit):
        self.read_limit = limit
        return self._body


class TradingEconomicsCalendarTests(unittest.TestCase):
    def setUp(self):
        self.kwargs = {
            "event_id": "US_PPI_2026_06",
            "reference_period": "2026-06",
            "release_datetime_utc": "2026-07-15T12:30:00Z",
            "retrieved_at_utc": "2026-07-12T08:00:00Z",
        }

    def row(self, metric="headline_mom", **values):
        row = {
            "Country": "United States",
            "Unit": "%",
            "Metric": metric,
            "ReferencePeriod": "2026-06",
            "ReleaseDate": "2026-07-15T12:30:00Z",
        }
        row.update(values)
        return row

    def assert_status(self, status, action):
        with self.assertRaises(te.ProviderError) as raised:
            action()
        self.assertEqual(raised.exception.status, status)

    def test_fixed_https_scheme_and_host(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

        self.assertEqual(te.fetch_calendar("fake-key", opener=opener), [])
        parsed = urlsplit(captured["url"])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, te.HOST)
        self.assertEqual(captured["timeout"], te.DEFAULT_TIMEOUT_SECONDS)

    def test_unsafe_scheme_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_UNSAFE_ENDPOINT", lambda: te._validate_provider_url("http://api.tradingeconomics.com/x"))

    def test_unsafe_host_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_UNSAFE_ENDPOINT", lambda: te._validate_provider_url("https://example.com/x"))

    def test_redirect_host_change_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_UNSAFE_ENDPOINT", lambda: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: Response(url="https://example.com/x")))

    def test_response_limit_is_enforced(self):
        response = Response(b"[{}]")
        self.assert_status("PPI_CONSENSUS_PROVIDER_RESPONSE_TOO_LARGE", lambda: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: response, max_response_bytes=3))
        self.assertEqual(response.read_limit, 4)

    def test_normal_json_response(self):
        self.assertEqual(te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: Response(json.dumps([{}]).encode())), [{}])

    def test_invalid_json_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_INVALID_JSON", lambda: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: Response(b"not-json")))

    def test_invalid_content_type_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_INVALID_CONTENT_TYPE", lambda: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: Response(content_type="text/html")))

    def test_http_statuses_are_mapped(self):
        cases = {401: "PPI_CONSENSUS_PROVIDER_AUTH_ERROR", 403: "PPI_CONSENSUS_PROVIDER_AUTH_ERROR", 429: "PPI_CONSENSUS_PROVIDER_RATE_LIMITED", 500: "PPI_CONSENSUS_PROVIDER_SERVER_ERROR"}
        for code, status in cases.items():
            with self.subTest(code=code):
                self.assert_status(status, lambda code=code: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: Response(status=code)))

    def test_timeout_is_mapped(self):
        self.assert_status("PPI_CONSENSUS_PROVIDER_TIMEOUT", lambda: te.fetch_calendar("fake-key", opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout())))

    def test_key_missing_does_not_open_transport_or_leak(self):
        calls = []
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assert_status("CONSENSUS_PROVIDER_KEY_MISSING", lambda: te.fetch_calendar(None, opener=lambda *_args, **_kwargs: calls.append(True)))
        self.assertEqual(calls, [])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")

    def test_whitespace_key_does_not_open_transport(self):
        calls = []
        self.assert_status("CONSENSUS_PROVIDER_KEY_MISSING", lambda: te.fetch_calendar("   ", opener=lambda *_args, **_kwargs: calls.append(True)))
        self.assertEqual(calls, [])

    def test_fake_key_is_not_exposed_in_error(self):
        secret = "fake-key-must-not-leak"
        with self.assertRaises(te.ProviderError) as raised:
            te.fetch_calendar(secret, opener=lambda *_args, **_kwargs: Response(status=401))
        self.assertNotIn(secret, str(raised.exception))

    def test_forecast_value_is_primary(self):
        self.assertEqual(te.forecast_value(self.row(ForecastValue="0.2")), "0.2")

    def test_forecast_is_only_a_fallback(self):
        self.assertEqual(te.forecast_value(self.row(Forecast="-0.1 %")), "-0.1")

    def test_equal_forecast_fields_use_forecast_value(self):
        self.assertEqual(te.forecast_value(self.row(ForecastValue=Decimal("0.20"), Forecast="0.2%")), "0.2")

    def test_conflicting_forecast_fields_are_rejected(self):
        self.assert_status("PPI_CONSENSUS_FORECAST_CONFLICT", lambda: te.forecast_value(self.row(ForecastValue="0.2", Forecast="0.3")))

    def test_teforecast_only_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROHIBITED_TEFORECAST", lambda: te.forecast_value(self.row(TEForecast="0.2")))

    def test_teforecastvalue_only_is_rejected(self):
        self.assert_status("PPI_CONSENSUS_PROHIBITED_TEFORECAST", lambda: te.forecast_value(self.row(TEForecastValue="0.2")))

    def test_actual_and_previous_are_never_substituted(self):
        self.assertIsNone(te.forecast_value(self.row(Actual="0.2", Previous="0.1")))
        self.assertEqual(te.normalize([self.row(Actual="0.2", Previous="0.1")], **self.kwargs)["status"], "unavailable")

    def test_invalid_number_forms_are_rejected(self):
        for value in ("NaN", "Infinity", True, "", "0.2 and 0.3", "1,2", {"value": "0.2"}, ["0.2"], "pct 0.2"):
            with self.subTest(value=repr(value)):
                self.assert_status("PPI_CONSENSUS_INVALID_FORECAST", lambda value=value: te.forecast_value(self.row(Forecast=value)))

    def test_complete_normalization_uses_decimal_values(self):
        rows = [self.row(metric, ForecastValue="0.20") for metric in te.METRICS]
        result = te.normalize(rows, **self.kwargs)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["metrics"]["headline_mom"]["expected"], "0.2")


if __name__ == "__main__":
    unittest.main()
