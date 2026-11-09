"""Stdio MCP server for Travelpayouts / Aviasales (stdlib only).

Protocol: JSON-RPC 2.0 over line-delimited stdin/stdout (MCP stdio transport).
Implemented methods: ``initialize``, ``ping``, ``tools/list``, ``tools/call``,
``resources/list``, ``prompts/list``. Notifications are accepted and ignored.

Environment variables
----------------------
TRAVELPAYOUTS_TOKEN    partner API token (required for API tools)
TRAVELPAYOUTS_MARKER   partner marker, e.g. 674170 (needed for Links API)
TRAVELPAYOUTS_TRS      project id (trs), e.g. 597672 (needed for Links API)
TRAVELPAYOUTS_DOMAIN   Aviasales host for raw search URLs (default www.aviasales.ru)
TRAVELPAYOUTS_CURRENCY default currency (default rub)
TRAVELPAYOUTS_MARKET   Data API market (default ru)
TRAVELPAYOUTS_LOCALE   locale for names/directory (default ru)
TRAVELPAYOUTS_API_BASE override API base (tests/local mock)
TRAVELPAYOUTS_TIMEOUT  HTTP timeout seconds (default 20)
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from .api import (
    DOMAIN_ENV,
    TravelpayoutsAuthError,
    TravelpayoutsClient,
    TravelpayoutsConfigError,
    TravelpayoutsError,
    _env,
)
from .links import (
    LinkBuildError,
    filled_form_url,
    results_url,
    build_search_params,
    search_url_from_api_link,
)

logger = logging.getLogger("travelpayouts_mcp")

SERVER_NAME = "travelpayouts-mcp"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07")

_client_singleton: Optional[TravelpayoutsClient] = None


class ToolInputError(ValueError):
    """Invalid tool arguments (reported to the client as isError)."""


def get_client() -> TravelpayoutsClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = TravelpayoutsClient()
    return _client_singleton


def reset_client() -> None:
    """Drop cached client (used by tests)."""
    global _client_singleton
    _client_singleton = None


def _domain() -> str:
    return _env(DOMAIN_ENV) or "www.aviasales.ru"


# ---------------------------------------------------------------------------
# argument helpers
# ---------------------------------------------------------------------------
def _req_str(args: Dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError("Параметр '{}' обязателен.".format(name))
    return value.strip()


def _opt_str(args: Dict[str, Any], name: str, default: Optional[str] = None) -> Optional[str]:
    value = args.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ToolInputError("Параметр '{}' должен быть строкой.".format(name))
    value = value.strip()
    return value or default


def _opt_int(
    args: Dict[str, Any],
    name: str,
    default: Optional[int] = None,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> Optional[int]:
    value = args.get(name)
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolInputError("Параметр '{}' должен быть целым числом.".format(name))
    if minimum is not None and number < minimum:
        raise ToolInputError("Параметр '{}' должен быть >= {}.".format(name, minimum))
    if maximum is not None and number > maximum:
        raise ToolInputError("Параметр '{}' должен быть <= {}.".format(name, maximum))
    return number


def _opt_bool(args: Dict[str, Any], name: str, default: bool = False) -> bool:
    value = args.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise ToolInputError("Параметр '{}' должен быть boolean.".format(name))


def _opt_list(args: Dict[str, Any], name: str) -> List[str]:
    value = args.get(name)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ToolInputError("Параметр '{}' должен быть массивом строк.".format(name))
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ToolInputError("Параметр '{}' должен содержать только строки.".format(name))
        result.append(item.strip())
    return result


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------
def _safe_search_url(link: Any) -> Optional[str]:
    if not link or not isinstance(link, str):
        return None
    try:
        return search_url_from_api_link(link, _domain())
    except LinkBuildError:
        return None


def _ticket_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "from": item.get("origin"),
        "to": item.get("destination"),
        "departure_at": item.get("departure_at"),
        "return_at": item.get("return_at"),
        "price": item.get("price"),
        "airline": item.get("airline"),
        "flight_number": item.get("flight_number"),
        "transfers": item.get("transfers"),
        "duration_minutes": item.get("duration"),
        "search_url": _safe_search_url(item.get("link")),
    }


def _matrix_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "depart_date": item.get("depart_date"),
        "return_date": item.get("return_date") or None,
        "price": item.get("value"),
        "transfers": item.get("number_of_changes"),
        "airline": item.get("airline"),
        "actual": item.get("actual"),
        "found_at": item.get("found_at"),
    }


# ---------------------------------------------------------------------------
# tool handlers
# ---------------------------------------------------------------------------
def tool_search_cheapest_tickets(args: Dict[str, Any]) -> Dict[str, Any]:
    """Cheapest tickets for a route/dates (v3/prices_for_dates)."""
    origin = _opt_str(args, "origin")
    destination = _opt_str(args, "destination")
    if not origin and not destination:
        raise ToolInputError("Укажите origin и/или destination (IATA-код).")
    limit = _opt_int(args, "limit", 10, 1, 30)
    payload = get_client().prices_for_dates(
        origin=origin,
        destination=destination,
        departure_at=_opt_str(args, "departure_at"),
        return_at=_opt_str(args, "return_at"),
        one_way=_opt_bool(args, "one_way", True),
        direct=_opt_bool(args, "direct", False),
        currency=_opt_str(args, "currency"),
        limit=limit,
        page=_opt_int(args, "page", 1, 1, 100) or 1,
        sorting=_opt_str(args, "sorting", "price") or "price",
        unique=_opt_bool(args, "unique", False),
        market=_opt_str(args, "market"),
    )
    items = payload.get("data") or []
    rows = [_ticket_row(item) for item in items[:limit] if isinstance(item, dict)]
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows),
        "note": "Цены из кэша Aviasales (актуальность до 7 дней). Ссылки — обычные ссылки поиска; для партнёрских используйте create_partner_links.",
        "tickets": rows,
    }


def tool_get_price_calendar(args: Dict[str, Any]) -> Dict[str, Any]:
    """Cheapest ticket for every day of a month (v1/prices/calendar)."""
    origin = _req_str(args, "origin")
    destination = _req_str(args, "destination")
    max_days = _opt_int(args, "max_days", 31, 1, 62) or 31
    payload = get_client().calendar(
        origin=origin,
        destination=destination,
        departure_date=_opt_str(args, "departure_date"),
        return_date=_opt_str(args, "return_date"),
        calendar_type=_opt_str(args, "calendar_type", "departure_date") or "departure_date",
        currency=_opt_str(args, "currency"),
    )
    data = payload.get("data") or {}
    rows = []
    if isinstance(data, dict):
        for day, item in sorted(data.items()):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "date": day,
                    "price": item.get("price"),
                    "airline": item.get("airline"),
                    "transfers": item.get("transfers"),
                    "departure_at": item.get("departure_at"),
                    "return_at": item.get("return_at"),
                }
            )
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows[:max_days]),
        "days": rows[:max_days],
    }


def tool_get_month_matrix(args: Dict[str, Any]) -> Dict[str, Any]:
    """Cheapest price per day of a month (v2/prices/month-matrix)."""
    origin = _req_str(args, "origin")
    destination = _req_str(args, "destination")
    max_days = _opt_int(args, "max_days", 31, 1, 62) or 31
    payload = get_client().month_matrix(
        origin=origin,
        destination=destination,
        month=_opt_str(args, "month"),
        one_way=_opt_bool(args, "one_way", True),
        currency=_opt_str(args, "currency"),
        limit=_opt_int(args, "limit", 31, 1, 62) or 31,
    )
    items = payload.get("data") or []
    rows = [_matrix_row(item) for item in items if isinstance(item, dict)]
    rows.sort(key=lambda row: row.get("depart_date") or "")
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows[:max_days]),
        "days": rows[:max_days],
    }


def tool_get_special_offers(args: Dict[str, Any]) -> Dict[str, Any]:
    """Abnormally cheap flight deals (v3/get_special_offers)."""
    payload = get_client().special_offers(
        origin=_opt_str(args, "origin"),
        destination=_opt_str(args, "destination"),
        currency=_opt_str(args, "currency"),
        locale=_opt_str(args, "locale"),
        airline=_opt_str(args, "airline"),
    )
    limit = _opt_int(args, "limit", 10, 1, 30) or 10
    rows = []
    for item in (payload.get("data") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "from": item.get("origin"),
                "to": item.get("destination"),
                "title": item.get("title"),
                "price": item.get("price"),
                "airline": item.get("airline"),
                "departure_at": item.get("departure_at"),
                "return_at": item.get("return_at"),
                "search_url": _safe_search_url(item.get("link")),
            }
        )
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows),
        "deals": rows,
    }


def tool_get_popular_directions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Cheapest origins to a destination (v3/get_popular_directions)."""
    destination = _req_str(args, "destination")
    limit = _opt_int(args, "limit", 10, 1, 30) or 10
    payload = get_client().popular_directions(
        destination=destination,
        locale=_opt_str(args, "locale"),
        currency=_opt_str(args, "currency"),
        limit=limit,
    )
    data = payload.get("data") or {}
    destination_info = data.get("destination") or {}
    origins = []
    for item in (data.get("origin") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        origins.append(
            {
                "from": item.get("city_iata"),
                "city": item.get("city_name"),
                "price": item.get("price"),
                "departure_at": item.get("departure_at"),
            }
        )
    return {
        "currency": payload.get("currency") or get_client().currency,
        "destination": destination_info.get("city_name") or destination,
        "origins": origins,
    }


def tool_get_city_directions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Popular destinations from a city (v1/city-directions)."""
    origin = _req_str(args, "origin")
    limit = _opt_int(args, "limit", 10, 1, 30) or 10
    payload = get_client().city_directions(
        origin=origin, currency=_opt_str(args, "currency")
    )
    data = payload.get("data") or {}
    rows = []
    if isinstance(data, dict):
        for item in data.values():
            if not isinstance(item, dict):
                continue
            rows.append(_ticket_row(item))
    rows.sort(key=lambda row: row.get("price") or 0)
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows[:limit]),
        "directions": rows[:limit],
    }


def tool_get_latest_prices(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recently found prices for a period (v3/get_latest_prices)."""
    limit = _opt_int(args, "limit", 10, 1, 30) or 10
    payload = get_client().latest_prices(
        origin=_opt_str(args, "origin"),
        destination=_opt_str(args, "destination"),
        period_type=_opt_str(args, "period_type", "year") or "year",
        beginning_of_period=_opt_str(args, "beginning_of_period"),
        group_by=_opt_str(args, "group_by", "directions") or "directions",
        one_way=_opt_bool(args, "one_way", True),
        currency=_opt_str(args, "currency"),
        page=_opt_int(args, "page", 1, 1, 100) or 1,
        sorting=_opt_str(args, "sorting", "price") or "price",
    )
    items = payload.get("data") or []
    rows = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "from": item.get("origin"),
                "to": item.get("destination"),
                "depart_date": item.get("depart_date"),
                "return_date": item.get("return_date") or None,
                "price": item.get("value"),
                "transfers": item.get("number_of_changes"),
                "found_at": item.get("found_at"),
            }
        )
    return {
        "currency": payload.get("currency") or get_client().currency,
        "count": len(rows),
        "prices": rows,
    }


def tool_resolve_place(args: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve city name / IATA code to IATA codes (cities + airports)."""
    query = _req_str(args, "query")
    limit = _opt_int(args, "limit", 5, 1, 20) or 5
    matches = get_client().find_places(
        query, locale=_opt_str(args, "locale"), limit=limit
    )
    return {"query": query, "count": len(matches), "matches": matches}


def tool_build_search_url(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build a raw Aviasales search URL (no tracking; use Links API for affiliate)."""
    origin = _req_str(args, "origin")
    destination = _req_str(args, "destination")
    departure_date = _opt_str(args, "departure_date")
    return_date = _opt_str(args, "return_date")
    adults = _opt_int(args, "adults", 1, 1, 9) or 1
    children = _opt_int(args, "children", 0, 0, 9) or 0
    infants = _opt_int(args, "infants", 0, 0, 9) or 0
    travel_class = _opt_str(args, "travel_class", "economy") or "economy"
    params = build_search_params(
        origin,
        destination,
        departure_date,
        return_date,
        adults,
        children,
        infants,
        travel_class,
    )
    return {
        "params": params,
        "filled_form_url": filled_form_url(
            origin,
            destination,
            departure_date,
            return_date,
            adults,
            children,
            infants,
            travel_class,
            _domain(),
        ),
        "results_url": results_url(
            origin,
            destination,
            departure_date,
            return_date,
            adults,
            children,
            infants,
            travel_class,
            _domain(),
        ),
        "note": "Обычная ссылка Aviasales без трекинга. Для партнёрской ссылки вызовите create_partner_links.",
    }


def tool_create_partner_links(args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert brand URLs to Travelpayouts partner links (Links API)."""
    urls = _opt_list(args, "urls")
    if not urls:
        raise ToolInputError("Передайте параметр 'urls' — массив URL (1–10).")
    if len(urls) > 10:
        raise ToolInputError("Links API принимает не более 10 URL за запрос.")
    payload = get_client().create_partner_links(
        urls,
        trs=_opt_str(args, "trs"),
        marker=_opt_str(args, "marker"),
        sub_id=_opt_str(args, "sub_id"),
        shorten=_opt_bool(args, "shorten", True),
    )
    result = payload.get("result") or {}
    links = result.get("links") if isinstance(result, dict) else None
    rows = []
    for item in links or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "url": item.get("url"),
                "partner_url": item.get("partner_url") or item.get("short_url"),
                "code": item.get("code"),
            }
        )
    return {
        "marker": result.get("marker"),
        "trs": result.get("trs"),
        "shorten": result.get("shorten"),
        "links": rows,
        "note": "Партнёрские ссылки созданы через Links API. Сохраняйте sub_id по каналам для аналитики.",
    }


# ---------------------------------------------------------------------------
# tool schemas
# ---------------------------------------------------------------------------
_CURRENCY = {
    "type": "string",
    "description": "Currency code: rub, usd, eur (default from env TRAVELPAYOUTS_CURRENCY).",
}
_ORIGIN = {"type": "string", "description": "IATA code of departure city/airport, e.g. MOW."}
_DESTINATION = {
    "type": "string",
    "description": "IATA code of destination city/airport, e.g. IST.",
}
_DEPARTURE = {
    "type": "string",
    "description": "Departure date or month: YYYY-MM-DD or YYYY-MM.",
}
_RETURN = {
    "type": "string",
    "description": "Return date/month (YYYY-MM-DD or YYYY-MM); omit for one-way.",
}


def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    return schema


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_cheapest_tickets",
        "description": (
            "Cheapest Aviasales tickets found during the last 48 hours for a route "
            "or dates (Travelpayouts Data API, cached up to 7 days). Returns prices, "
            "airline, transfers and plain search URLs. Use create_partner_links to "
            "turn a URL into a tracked affiliate link."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "departure_at": _DEPARTURE,
                "return_at": _RETURN,
                "one_way": {"type": "boolean", "description": "One-way (default true)."},
                "direct": {"type": "boolean", "description": "Direct flights only."},
                "currency": _CURRENCY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                "page": {"type": "integer", "minimum": 1},
                "sorting": {
                    "type": "string",
                    "enum": ["price", "route"],
                    "description": "Sort by price or route popularity.",
                },
                "unique": {
                    "type": "boolean",
                    "description": "Return unique destinations when only origin is given.",
                },
                "market": {"type": "string", "description": "Data market, e.g. ru, us."},
            }
        ),
    },
    {
        "name": "get_price_calendar",
        "description": (
            "Cheapest ticket for every day of a month for a route "
            "(v1/prices/calendar). Good for 'when is it cheaper to fly' answers."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "departure_date": {
                    "type": "string",
                    "description": "Month to build the calendar for (YYYY-MM).",
                },
                "return_date": {"type": "string", "description": "Optional return month."},
                "calendar_type": {
                    "type": "string",
                    "enum": ["departure_date", "return_date"],
                },
                "currency": _CURRENCY,
                "max_days": {"type": "integer", "minimum": 1, "maximum": 62},
            },
            ["origin", "destination"],
        ),
    },
    {
        "name": "get_month_matrix",
        "description": (
            "Cheapest price per day of a month (v2/prices/month-matrix), "
            "grouped by transfers. Alternative calendar view."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "month": {"type": "string", "description": "First day of month (YYYY-MM-DD)."},
                "one_way": {"type": "boolean"},
                "currency": _CURRENCY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 62},
                "max_days": {"type": "integer", "minimum": 1, "maximum": 62},
            },
            ["origin", "destination"],
        ),
    },
    {
        "name": "get_special_offers",
        "description": (
            "Abnormally cheap flight deals (v3/get_special_offers) — the best "
            "starting point for 'deal of the day' content."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "currency": _CURRENCY,
                "locale": {"type": "string", "description": "ru, en, es..."},
                "airline": {"type": "string", "description": "IATA airline code, e.g. SU."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            }
        ),
    },
    {
        "name": "get_popular_directions",
        "description": (
            "Cheapest origins flying to a destination (v3/get_popular_directions) — "
            "useful for destination landing pages."
        ),
        "inputSchema": _schema(
            {
                "destination": _DESTINATION,
                "locale": {"type": "string"},
                "currency": _CURRENCY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            ["destination"],
        ),
    },
    {
        "name": "get_city_directions",
        "description": "Popular destinations from a city (v1/city-directions).",
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "currency": _CURRENCY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            ["origin"],
        ),
    },
    {
        "name": "get_latest_prices",
        "description": (
            "Recently found prices for a period (v3/get_latest_prices): "
            "dates or directions, sorted by price."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "period_type": {"type": "string", "enum": ["year", "month", "day"]},
                "beginning_of_period": {"type": "string", "description": "YYYY, YYYY-MM-DD."},
                "group_by": {"type": "string", "enum": ["dates", "directions"]},
                "one_way": {"type": "boolean"},
                "currency": _CURRENCY,
                "page": {"type": "integer", "minimum": 1},
                "sorting": {"type": "string", "enum": ["price", "route", "distance_unit_price"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            }
        ),
    },
    {
        "name": "resolve_place",
        "description": (
            "Resolve a city name or IATA code to IATA codes (cities + airports) "
            "using the Travelpayouts directory. Use before search tools."
        ),
        "inputSchema": _schema(
            {
                "query": {"type": "string", "description": "City name or IATA code."},
                "locale": {"type": "string", "description": "ru, en, es (default ru)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ["query"],
        ),
    },
    {
        "name": "build_search_url",
        "description": (
            "Build a plain Aviasales search URL (params string + filled form URL + "
            "results URL). No tracking: for affiliate links call create_partner_links."
        ),
        "inputSchema": _schema(
            {
                "origin": _ORIGIN,
                "destination": _DESTINATION,
                "departure_date": {"type": "string", "description": "YYYY-MM-DD."},
                "return_date": {"type": "string", "description": "YYYY-MM-DD."},
                "adults": {"type": "integer", "minimum": 1, "maximum": 9},
                "children": {"type": "integer", "minimum": 0, "maximum": 9},
                "infants": {"type": "integer", "minimum": 0, "maximum": 9},
                "travel_class": {
                    "type": "string",
                    "enum": ["economy", "comfort", "business", "first"],
                },
            },
            ["origin", "destination"],
        ),
    },
    {
        "name": "create_partner_links",
        "description": (
            "Create Travelpayouts affiliate links from brand URLs via the Partner "
            "Links API (branded short links, tracked by sub_id). Requires "
            "TRAVELPAYOUTS_TOKEN, TRAVELPAYOUTS_MARKER and TRAVELPAYOUTS_TRS. "
            "Limits: max 10 URLs per call, 100 calls/min per marker."
        ),
        "inputSchema": _schema(
            {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                    "description": "Brand URLs (long URLs with UTM tags).",
                },
                "sub_id": {
                    "type": "string",
                    "description": "Tracking label, e.g. tg_en_deals or seo_es.",
                },
                "marker": {"type": "string", "description": "Override partner marker."},
                "trs": {"type": "string", "description": "Override project id (trs)."},
                "shorten": {"type": "boolean", "description": "Return branded short link."},
            },
            ["urls"],
        ),
    },
]

HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "search_cheapest_tickets": tool_search_cheapest_tickets,
    "get_price_calendar": tool_get_price_calendar,
    "get_month_matrix": tool_get_month_matrix,
    "get_special_offers": tool_get_special_offers,
    "get_popular_directions": tool_get_popular_directions,
    "get_city_directions": tool_get_city_directions,
    "get_latest_prices": tool_get_latest_prices,
    "resolve_place": tool_resolve_place,
    "build_search_url": tool_build_search_url,
    "create_partner_links": tool_create_partner_links,
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------
def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(
    request_id: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_error(message: str) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message. Returns ``None`` for notifications."""
    request_id = message.get("id")
    if "id" not in message:  # notification (initialized, cancelled, ...)
        return None
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(request_id, -32602, "params must be an object")
    if not isinstance(method, str):
        return _error(request_id, -32600, "method is required")

    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
        return _result(
            request_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": (
                    "Travelpayouts / Aviasales MCP: flight deals, price calendars, "
                    "popular directions and partner links. Prices come from the "
                    "Aviasales cache (up to 7 days old). Affiliate links are created "
                    "only via create_partner_links (Partner Links API)."
                ),
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "resources/list":
        return _result(request_id, {"resources": []})
    if method == "prompts/list":
        return _result(request_id, {"prompts": []})
    if method == "logging/setLevel":
        return _result(request_id, {})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return _error(request_id, -32602, "tool name is required")
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "tool arguments must be an object")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(request_id, -32602, "unknown tool: {}".format(name))
        try:
            data = handler(arguments)
        except (ToolInputError, LinkBuildError) as exc:
            return _result(request_id, _tool_error(str(exc)))
        except TravelpayoutsConfigError as exc:
            return _result(request_id, _tool_error(str(exc)))
        except TravelpayoutsAuthError as exc:
            return _result(request_id, _tool_error(str(exc)))
        except TravelpayoutsError as exc:
            return _result(request_id, _tool_error(str(exc)))
        except Exception:  # noqa: BLE001 - never crash the server on one tool call
            logger.error("tool %s failed:\n%s", name, traceback.format_exc())
            return _result(
                request_id,
                _tool_error(
                    "Внутренняя ошибка при выполнении {}: {}".format(
                        name, sys.exc_info()[1]
                    )
                ),
            )
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return _result(
            request_id,
            {"content": [{"type": "text", "text": text}], "isError": False},
        )
    return _error(request_id, -32601, "method not found: {}".format(method))


def serve(stdin: Any = None, stdout: Any = None) -> None:
    """Run the stdio loop until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = _error(None, -32700, "parse error")
        else:
            if isinstance(message, dict):
                response = handle_request(message)
            else:
                response = _error(None, -32600, "invalid request")
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if "--version" in argv or "-V" in argv:
        sys.stdout.write("{} {}\n".format(SERVER_NAME, __version__))
        return 0
    if "--help" in argv or "-h" in argv:
        sys.stdout.write(
            "{} {}\n\n"
            "Stdio MCP server for Travelpayouts / Aviasales.\n\n"
            "Environment:\n"
            "  TRAVELPAYOUTS_TOKEN    partner API token (required for API tools)\n"
            "  TRAVELPAYOUTS_MARKER   partner marker (Links API)\n"
            "  TRAVELPAYOUTS_TRS      project id (Links API)\n"
            "  TRAVELPAYOUTS_DOMAIN   Aviasales host (default www.aviasales.ru)\n"
            "  TRAVELPAYOUTS_API_BASE override API base (tests)\n".format(
                SERVER_NAME, __version__
            )
        )
        return 0
    try:
        serve()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
