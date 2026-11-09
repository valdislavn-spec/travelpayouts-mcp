"""Tests for the MCP stdio server: protocol, tools and end-to-end stdio."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from travelpayouts_mcp import server

from mock_api import VALID_TOKEN, MockTravelpayoutsAPI

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_tool_result(response):
    result = response["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._api = MockTravelpayoutsAPI()
        self._api.__enter__()
        self._env = {
            "TRAVELPAYOUTS_API_BASE": self._api.base_url,
            "TRAVELPAYOUTS_TOKEN": VALID_TOKEN,
            "TRAVELPAYOUTS_MARKER": "674170",
            "TRAVELPAYOUTS_TRS": "597672",
        }
        self._backup = {key: os.environ.get(key) for key in self._env}
        os.environ.update(self._env)
        server.reset_client()

    def tearDown(self) -> None:
        server.reset_client()
        for key, value in self._backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._api.__exit__(None, None, None)

    def call(self, name, arguments=None, request_id=1):
        return server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )

    # ------------------------------------------------------------- protocol
    def test_initialize(self) -> None:
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            }
        )
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(response["result"]["serverInfo"]["name"], "travelpayouts-mcp")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_initialize_unknown_protocol_falls_back(self) -> None:
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "1999-01-01"},
            }
        )
        self.assertEqual(response["result"]["protocolVersion"], server.PROTOCOL_VERSION)

    def test_tools_list(self) -> None:
        response = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(len(tools), 10)
        self.assertIn("search_cheapest_tickets", names)
        self.assertIn("create_partner_links", names)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_notification_returns_none(self) -> None:
        self.assertIsNone(
            server.handle_request(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )

    def test_unknown_method(self) -> None:
        response = server.handle_request(
            {"jsonrpc": "2.0", "id": 4, "method": "haystack"}
        )
        self.assertEqual(response["error"]["code"], -32601)

    def test_unknown_tool(self) -> None:
        response = self.call("nope")
        self.assertEqual(response["error"]["code"], -32602)

    def test_ping(self) -> None:
        response = server.handle_request({"jsonrpc": "2.0", "id": 5, "method": "ping"})
        self.assertEqual(response["result"], {})

    # ---------------------------------------------------------------- tools
    def test_search_cheapest_tickets(self) -> None:
        response = self.call(
            "search_cheapest_tickets",
            {"origin": "MOW", "destination": "IST", "departure_at": "2026-07-16", "limit": 2},
        )
        data = _parse_tool_result(response)
        self.assertEqual(data["currency"], "rub")
        self.assertEqual(data["count"], 2)
        first = data["tickets"][0]
        self.assertEqual(first["price"], 12345)
        self.assertEqual(
            first["search_url"],
            "https://www.aviasales.ru/search/MOW1607IST2007c321?t=abc&search_date=01072026",
        )

    def test_search_requires_origin_or_destination(self) -> None:
        response = self.call("search_cheapest_tickets", {})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("origin", response["result"]["content"][0]["text"])

    def test_price_calendar(self) -> None:
        response = self.call(
            "get_price_calendar", {"origin": "MOW", "destination": "IST", "max_days": 2}
        )
        data = _parse_tool_result(response)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["days"][0]["date"], "2026-07-01")

    def test_month_matrix(self) -> None:
        response = self.call(
            "get_month_matrix", {"origin": "MOW", "destination": "IST"}
        )
        data = _parse_tool_result(response)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["days"][0]["price"], 11111)

    def test_special_offers(self) -> None:
        response = self.call("get_special_offers", {"origin": "MOW"})
        data = _parse_tool_result(response)
        self.assertEqual(data["count"], 1)
        self.assertIn("/search/MOW1407LED1", data["deals"][0]["search_url"])

    def test_popular_directions(self) -> None:
        response = self.call("get_popular_directions", {"destination": "IST"})
        data = _parse_tool_result(response)
        self.assertEqual(data["destination"], "Istanbul")
        self.assertEqual(data["origins"][0]["from"], "MOW")

    def test_city_directions(self) -> None:
        response = self.call("get_city_directions", {"origin": "MOW"})
        data = _parse_tool_result(response)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["directions"][0]["to"], "AER")

    def test_latest_prices(self) -> None:
        response = self.call("get_latest_prices", {"origin": "MOW"})
        data = _parse_tool_result(response)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["prices"][0]["price"], 12345)

    def test_resolve_place(self) -> None:
        response = self.call("resolve_place", {"query": "moscow"})
        data = _parse_tool_result(response)
        self.assertEqual(data["matches"][0]["code"], "MOW")

    def test_build_search_url(self) -> None:
        response = self.call(
            "build_search_url",
            {
                "origin": "MOW",
                "destination": "LED",
                "departure_date": "2026-07-16",
                "adults": 2,
                "travel_class": "business",
            },
        )
        data = _parse_tool_result(response)
        self.assertEqual(data["params"], "MOW1607LEDc2")
        self.assertIn("/search/MOW1607LEDc2", data["results_url"])

    def test_build_search_url_invalid_input(self) -> None:
        response = self.call(
            "build_search_url", {"origin": "MOW", "destination": "LED", "adults": 0}
        )
        self.assertTrue(response["result"]["isError"])

    def test_create_partner_links(self) -> None:
        response = self.call(
            "create_partner_links",
            {"urls": ["https://www.aviasales.com/?params=MOWIST1"], "sub_id": "seo_en"},
        )
        data = _parse_tool_result(response)
        self.assertEqual(data["marker"], 674170)
        self.assertEqual(data["links"][0]["partner_url"], "https://aviasales.tpk.ro/AbCd1234")

    def test_create_partner_links_requires_config(self) -> None:
        os.environ.pop("TRAVELPAYOUTS_MARKER", None)
        os.environ.pop("TRAVELPAYOUTS_TRS", None)
        server.reset_client()
        response = self.call("create_partner_links", {"urls": ["https://example.com/"]})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("trs", response["result"]["content"][0]["text"])

    def test_missing_token_returns_tool_error(self) -> None:
        os.environ.pop("TRAVELPAYOUTS_TOKEN", None)
        server.reset_client()
        response = self.call("search_cheapest_tickets", {"origin": "MOW"})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("токен", response["result"]["content"][0]["text"])

    # ----------------------------------------------------------------- stdio
    def test_serve_loop_handles_lines(self) -> None:
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            + "\n"
            + "not-json\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            + "\n"
        )
        stdout = io.StringIO()
        server.serve(stdin=stdin, stdout=stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["result"], {})
        self.assertEqual(lines[1]["error"]["code"], -32700)
        self.assertEqual(len(lines[2]["result"]["tools"]), 10)


class StdioIntegrationTests(unittest.TestCase):
    """Spawn the real process and speak MCP over stdin/stdout."""

    def test_subprocess_handshake(self) -> None:
        with MockTravelpayoutsAPI() as api:
            env = dict(os.environ)
            env.update(
                {
                    "TRAVELPAYOUTS_API_BASE": api.base_url,
                    "TRAVELPAYOUTS_TOKEN": VALID_TOKEN,
                    "PYTHONPATH": str(PROJECT_ROOT),
                }
            )
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "resolve_place",
                        "arguments": {"query": "Moscow"},
                    },
                },
            ]
            stdin_text = "\n".join(json.dumps(item) for item in requests) + "\n"
            completed = subprocess.run(
                [sys.executable, "-m", "travelpayouts_mcp"],
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(PROJECT_ROOT),
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            lines = [
                json.loads(line)
                for line in completed.stdout.splitlines()
                if line.strip()
            ]
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "travelpayouts-mcp")
            self.assertEqual(len(lines[1]["result"]["tools"]), 10)
            tool_result = lines[2]["result"]
            self.assertFalse(tool_result["isError"])
            payload = json.loads(tool_result["content"][0]["text"])
            self.assertEqual(payload["matches"][0]["code"], "MOW")


if __name__ == "__main__":
    unittest.main()
