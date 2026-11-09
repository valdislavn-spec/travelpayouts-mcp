"""Local mock of the Travelpayouts API for offline tests.

Starts a real HTTP server on 127.0.0.1:<random port> and records requests, so
the client can be exercised end-to-end without network access or a token.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

VALID_TOKEN = "test-token"

PRICES_FOR_DATES = {
    "success": True,
    "currency": "rub",
    "data": [
        {
            "origin": "MOW",
            "destination": "IST",
            "origin_airport": "SVO",
            "destination_airport": "IST",
            "price": 12345,
            "airline": "SU",
            "flight_number": "520",
            "departure_at": "2026-07-16T08:40:00+03:00",
            "return_at": "2026-07-20T16:40:00+04:00",
            "transfers": 0,
            "return_transfers": 0,
            "duration": 660,
            "link": "/search/MOW1607IST2007c321?t=abc&search_date=01072026",
        },
        {
            "origin": "MOW",
            "destination": "IST",
            "price": 15000,
            "airline": "TK",
            "flight_number": "414",
            "departure_at": "2026-07-16T12:00:00+03:00",
            "return_at": None,
            "transfers": 1,
            "duration": 800,
            "link": "/search/MOW1607IST1?t=def",
        },
    ],
}

CALENDAR = {
    "success": True,
    "currency": "rub",
    "data": {
        "2026-07-01": {
            "origin": "MOW",
            "destination": "IST",
            "price": 11111,
            "transfers": 1,
            "airline": "SU",
            "flight_number": "1",
            "departure_at": "2026-07-01T08:00:00Z",
        },
        "2026-07-02": {
            "origin": "MOW",
            "destination": "IST",
            "price": 9999,
            "transfers": 0,
            "airline": "TK",
            "flight_number": "2",
            "departure_at": "2026-07-02T09:00:00Z",
        },
    },
}

MONTH_MATRIX = {
    "success": True,
    "currency": "rub",
    "data": [
        {
            "depart_date": "2026-07-01",
            "return_date": "",
            "value": 11111,
            "number_of_changes": 1,
            "actual": True,
            "found_at": "2026-06-01T10:00:00Z",
        },
        {
            "depart_date": "2026-07-02",
            "return_date": "2026-07-10",
            "value": 22222,
            "number_of_changes": 0,
            "actual": True,
            "found_at": "2026-06-01T10:00:00Z",
        },
    ],
}

SPECIAL_OFFERS = {
    "success": True,
    "currency": "rub",
    "data": [
        {
            "origin": "MOW",
            "destination": "LED",
            "title": "Flight deals from Moscow to Saint Petersburg",
            "price": 1413,
            "airline": "N4",
            "departure_at": "2026-07-14T08:55:00+03:00",
            "return_at": "2026-07-18T18:00:00+03:00",
            "link": "/MOW1407LED1?t=offer",
        }
    ],
}

CITY_DIRECTIONS = {
    "success": True,
    "currency": "rub",
    "data": {
        "AER": {
            "origin": "MOW",
            "destination": "AER",
            "price": 3673,
            "transfers": 0,
            "airline": "WZ",
            "flight_number": 125,
            "departure_at": "2026-07-08T16:35:00Z",
            "return_at": "2026-07-17T16:05:00Z",
            "link": "/MOW0807AER1",
        }
    },
}

POPULAR_DIRECTIONS = {
    "success": True,
    "currency": "rub",
    "data": {
        "destination": {"city_name": "Istanbul", "country_name": "Turkey"},
        "origin": [
            {
                "city_name": "Moscow",
                "city_iata": "MOW",
                "departure_at": "2026-07-16",
                "return_at": "",
                "price": 12345,
            }
        ],
    },
}

LATEST_PRICES = {
    "success": True,
    "currency": "rub",
    "data": [
        {
            "origin": "MOW",
            "destination": "IST",
            "depart_date": "2026-07-16",
            "return_date": "",
            "value": 12345,
            "number_of_changes": 0,
            "found_at": "2026-06-01T10:00:00Z",
        }
    ],
}

CITIES = [
    {"code": "MOW", "name": "Moscow", "country_name": "Russia"},
    {"code": "IST", "name": "Istanbul", "country_name": "Turkey"},
    {"code": "LED", "name": "Saint Petersburg", "country_name": "Russia"},
]

AIRPORTS = [
    {"code": "SVO", "name": "Sheremetyevo", "city_code": "MOW", "country_name": "Russia"},
    {"code": "IST", "name": "Istanbul Airport", "city_code": "IST", "country_name": "Turkey"},
]


def links_response(body: Dict[str, Any]) -> Dict[str, Any]:
    links = []
    for item in body.get("links") or []:
        links.append(
            {
                "url": item.get("url"),
                "code": "success",
                "partner_url": "https://aviasales.tpk.ro/AbCd1234",
            }
        )
    return {
        "result": {
            "marker": body.get("marker"),
            "trs": body.get("trs"),
            "shorten": body.get("shorten"),
            "links": links,
        },
        "code": "success",
        "status": 200,
    }


class MockTravelpayoutsAPI:
    """Context-manager HTTP server emulating Travelpayouts endpoints."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence test output
                pass

            def _record(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                self._body = body
                parsed = urlparse(self.path)
                api.requests.append(
                    {
                        "method": self.command,
                        "path": parsed.path,
                        "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
                        "headers": dict(self.headers),
                        "body": body.decode("utf-8") if body else "",
                    }
                )

            def _send(self, status: int, payload: Any, *, raw: bool = False) -> None:
                data = payload if raw else json.dumps(payload)
                encoded = data.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _authorized(self) -> bool:
                return self.headers.get("X-Access-Token") == VALID_TOKEN

            def _route_get(self) -> None:
                parsed = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                path = parsed.path
                if path.startswith("/data/"):
                    if path.endswith("/cities.json"):
                        return self._send(200, CITIES)
                    if path.endswith("/airports.json"):
                        return self._send(200, AIRPORTS)
                    return self._send(404, {"success": False, "error": "not found"})
                if not self._authorized():
                    return self._send(
                        401, {"success": False, "error": "invalid token", "data": {}}
                    )
                routes: Dict[str, Any] = {
                    "/aviasales/v3/prices_for_dates": PRICES_FOR_DATES,
                    "/aviasales/v3/get_special_offers": SPECIAL_OFFERS,
                    "/aviasales/v3/get_popular_directions": POPULAR_DIRECTIONS,
                    "/aviasales/v3/get_latest_prices": LATEST_PRICES,
                    "/aviasales/v3/grouped_prices": {
                        "success": True,
                        "currency": "rub",
                        "data": {"2026-07-01": {"price": 100}},
                    },
                    "/v2/prices/month-matrix": MONTH_MATRIX,
                    "/v1/prices/calendar": CALENDAR,
                    "/v1/city-directions": CITY_DIRECTIONS,
                }
                if path in ("/aviasales/v3/prices_for_dates", "/v1/city-directions"):
                    origin = query.get("origin", "")
                    if origin == "ERR500":
                        return self._send(500, "boom", raw=True)
                    if origin == "ERRJSON":
                        return self._send(200, "not-json", raw=True)
                payload = routes.get(path)
                if payload is None:
                    return self._send(404, {"success": False, "error": "not found"})
                return self._send(200, payload)

            def _route_post(self) -> None:
                if not self._authorized():
                    return self._send(
                        401, {"success": False, "error": "invalid token", "data": {}}
                    )
                try:
                    body = json.loads(getattr(self, "_body", b"") or b"{}")
                except ValueError:
                    return self._send(422, {"success": False, "error": "bad json"})
                if urlparse(self.path).path == "/links/v1/create":
                    return self._send(200, links_response(body))
                return self._send(404, {"success": False, "error": "not found"})

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
                self._record()
                self._route_get()

            def do_POST(self) -> None:  # noqa: N802
                self._record()
                self._route_post()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return "http://{}:{}".format(host, port)

    def __enter__(self) -> "MockTravelpayoutsAPI":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def last_request(self) -> Optional[Dict[str, Any]]:
        return self.requests[-1] if self.requests else None
