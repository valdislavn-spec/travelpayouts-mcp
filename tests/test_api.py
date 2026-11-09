"""Tests for the Travelpayouts API client (offline, mock HTTP server)."""

from __future__ import annotations

import json
import os
import unittest

from travelpayouts_mcp.api import (
    MARKER_ENV,
    TOKEN_ENV,
    TRS_ENV,
    TravelpayoutsAPIError,
    TravelpayoutsAuthError,
    TravelpayoutsClient,
    TravelpayoutsConfigError,
)

from mock_api import VALID_TOKEN, MockTravelpayoutsAPI


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            key: os.environ.get(key)
            for key in (TOKEN_ENV, MARKER_ENV, TRS_ENV, "TRAVELPAYOUTS_API_BASE")
        }
        os.environ.pop(TOKEN_ENV, None)
        os.environ.pop(MARKER_ENV, None)
        os.environ.pop(TRS_ENV, None)
        os.environ.pop("TRAVELPAYOUTS_API_BASE", None)

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_prices_for_dates_sends_token_and_params(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            payload = client.prices_for_dates(
                origin="MOW", destination="IST", departure_at="2026-07-16", limit=2
            )
            self.assertTrue(payload["success"])
            self.assertEqual(len(payload["data"]), 2)
            request = api.last_request()
            self.assertIsNotNone(request)
            assert request is not None
            self.assertEqual(request["path"], "/aviasales/v3/prices_for_dates")
            self.assertEqual(request["headers"].get("X-Access-Token"), VALID_TOKEN)
            self.assertEqual(request["query"]["origin"], "MOW")
            self.assertEqual(request["query"]["destination"], "IST")
            self.assertEqual(request["query"]["one_way"], "true")
            self.assertNotIn("token", request["query"])

    def test_missing_token_raises_config_error(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token="", api_base=api.base_url)
            with self.assertRaises(TravelpayoutsConfigError):
                client.prices_for_dates(origin="MOW")

    def test_bad_token_raises_auth_error(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token="bad", api_base=api.base_url)
            with self.assertRaises(TravelpayoutsAuthError):
                client.prices_for_dates(origin="MOW")

    def test_http_500_raises_api_error(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            with self.assertRaises(TravelpayoutsAPIError) as caught:
                client.prices_for_dates(origin="ERR500")
            self.assertEqual(caught.exception.status, 500)

    def test_non_json_response_raises_api_error(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            with self.assertRaises(TravelpayoutsAPIError):
                client.prices_for_dates(origin="ERRJSON")

    def test_calendar_and_month_matrix(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            calendar = client.calendar("MOW", "IST", departure_date="2026-07")
            self.assertIn("2026-07-01", calendar["data"])
            matrix = client.month_matrix("MOW", "IST", month="2026-07-01")
            self.assertEqual(len(matrix["data"]), 2)

    def test_find_places_works_without_token(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token="", api_base=api.base_url)
            matches = client.find_places("mos")
            codes = [item["code"] for item in matches]
            self.assertIn("MOW", codes)
            self.assertEqual(matches[0]["name"], "Moscow")

    def test_create_partner_links(self) -> None:
        with MockTravelpayoutsAPI() as api:
            os.environ[MARKER_ENV] = "674170"
            os.environ[TRS_ENV] = "597672"
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            payload = client.create_partner_links(
                ["https://www.aviasales.com/?params=MOWIST1"], sub_id="seo_en"
            )
            self.assertEqual(payload["result"]["marker"], 674170)
            self.assertEqual(payload["result"]["trs"], 597672)
            self.assertEqual(len(payload["result"]["links"]), 1)
            request = api.last_request()
            assert request is not None
            self.assertEqual(request["method"], "POST")
            self.assertEqual(request["path"], "/links/v1/create")
            body = json.loads(request["body"])
            self.assertEqual(body["marker"], 674170)
            self.assertEqual(body["trs"], 597672)
            self.assertTrue(body["shorten"])
            self.assertEqual(body["links"][0]["sub_id"], "seo_en")

    def test_create_partner_links_requires_project_settings(self) -> None:
        with MockTravelpayoutsAPI() as api:
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            with self.assertRaises(TravelpayoutsConfigError):
                client.create_partner_links(["https://www.aviasales.com/"])

    def test_create_partner_links_limit(self) -> None:
        with MockTravelpayoutsAPI() as api:
            os.environ[MARKER_ENV] = "674170"
            os.environ[TRS_ENV] = "597672"
            client = TravelpayoutsClient(token=VALID_TOKEN, api_base=api.base_url)
            with self.assertRaises(TravelpayoutsConfigError):
                client.create_partner_links(["https://example.com/{}".format(i) for i in range(11)])

    def test_api_base_override_from_env(self) -> None:
        with MockTravelpayoutsAPI() as api:
            os.environ["TRAVELPAYOUTS_API_BASE"] = api.base_url
            os.environ[TOKEN_ENV] = VALID_TOKEN
            client = TravelpayoutsClient()
            payload = client.latest_prices(origin="MOW")
            self.assertTrue(payload["success"])


if __name__ == "__main__":
    unittest.main()
