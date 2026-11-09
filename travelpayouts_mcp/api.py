"""Travelpayouts API client (stdlib only, no external dependencies).

Two APIs are used:

* **Data API** (Aviasales prices cache, ~7 days TTL) —
  https://support.travelpayouts.com/hc/ru/articles/203956163
* **Partner Links API** — ``POST /links/v1/create``
  https://support.travelpayouts.com/hc/en-us/articles/25289759198226

Auth: partner API token from https://app.travelpayouts.com/profile/api-token
is passed in the ``X-Access-Token`` header. The token is never written to
disk, logs or tool output.

The client is intentionally small: it returns parsed JSON payloads and lets
the MCP tool layer decide which fields to expose to the model.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_API_BASE = "https://api.travelpayouts.com"
DEFAULT_DOMAIN = "www.aviasales.ru"
USER_AGENT = "travelpayouts-mcp/0.1.0"

TOKEN_ENV = "TRAVELPAYOUTS_TOKEN"
MARKER_ENV = "TRAVELPAYOUTS_MARKER"
TRS_ENV = "TRAVELPAYOUTS_TRS"
BASE_ENV = "TRAVELPAYOUTS_API_BASE"
TIMEOUT_ENV = "TRAVELPAYOUTS_TIMEOUT"
CURRENCY_ENV = "TRAVELPAYOUTS_CURRENCY"
MARKET_ENV = "TRAVELPAYOUTS_MARKET"
LOCALE_ENV = "TRAVELPAYOUTS_LOCALE"
DOMAIN_ENV = "TRAVELPAYOUTS_DOMAIN"

DEFAULT_CURRENCY = "rub"
DEFAULT_MARKET = "ru"
DEFAULT_LOCALE = "ru"
MAX_LINKS_PER_REQUEST = 10


class TravelpayoutsError(Exception):
    """Base class for all client errors."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class TravelpayoutsConfigError(TravelpayoutsError):
    """Missing/invalid local configuration (token, project id, ...)."""


class TravelpayoutsAuthError(TravelpayoutsError):
    """API rejected the token (HTTP 401/403)."""


class TravelpayoutsAPIError(TravelpayoutsError):
    """Network error, rate limit or unexpected API response."""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bool(value: Any) -> str:
    """Data API expects lowercase ``true``/``false`` strings."""
    return "true" if bool(value) else "false"


def _clean(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None and v != ""}


class TravelpayoutsClient:
    """Minimal synchronous client for the Travelpayouts public APIs."""

    def __init__(
        self,
        token: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        currency: Optional[str] = None,
        market: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> None:
        self.token = (token if token is not None else _env(TOKEN_ENV)).strip()
        self.api_base = (api_base or _env(BASE_ENV) or DEFAULT_API_BASE).rstrip("/")
        self.currency = (currency or _env(CURRENCY_ENV) or DEFAULT_CURRENCY).lower()
        self.market = (market or _env(MARKET_ENV) or DEFAULT_MARKET).lower()
        self.locale = (locale or _env(LOCALE_ENV) or DEFAULT_LOCALE).lower()
        if timeout is None:
            try:
                timeout = float(_env(TIMEOUT_ENV) or "20")
            except ValueError:
                timeout = 20.0
        self.timeout = timeout
        self._places_cache: Dict[str, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------ HTTP
    @property
    def has_token(self) -> bool:
        return bool(self.token)

    def _require_token(self) -> None:
        if not self.token:
            raise TravelpayoutsConfigError(
                "Не задан API-токен Travelpayouts. Получите его в кабинете "
                "(https://app.travelpayouts.com/profile/api-token) и передайте "
                "в переменной окружения TRAVELPAYOUTS_TOKEN."
            )

    def _request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
        expect: str = "object",
    ) -> Any:
        if auth:
            self._require_token()
        query = urllib.parse.urlencode(_clean(params or {}), doseq=True)
        url = "{}{}{}".format(self.api_base, path, "?" + query if query else "")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["X-Access-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:  # noqa: BLE001 - best-effort diagnostics
                pass
            if exc.code in (401, 403):
                raise TravelpayoutsAuthError(
                    "Travelpayouts отклонил токен (HTTP {}). Проверьте "
                    "TRAVELPAYOUTS_TOKEN и доступ к API.".format(exc.code),
                    status=exc.code,
                )
            if exc.code == 429:
                raise TravelpayoutsAPIError(
                    "Превышен лимит запросов Travelpayouts (HTTP 429). "
                    "Подождите и повторите.",
                    status=429,
                )
            raise TravelpayoutsAPIError(
                "Travelpayouts API вернул HTTP {}. {}".format(exc.code, detail).strip(),
                status=exc.code,
            )
        except urllib.error.URLError as exc:  # type: ignore[attr-defined]
            raise TravelpayoutsAPIError(
                "Не удалось соединиться с Travelpayouts API: {}".format(exc.reason)
            )
        except (TimeoutError, OSError) as exc:
            raise TravelpayoutsAPIError(
                "Таймаут/сетевая ошибка при запросе к Travelpayouts API: {}".format(exc)
            )

        try:
            payload = json.loads(raw)
        except ValueError:
            raise TravelpayoutsAPIError(
                "Travelpayouts API вернул не-JSON ответ: {}".format(raw[:200])
            )

        if expect == "array":
            if not isinstance(payload, list):
                raise TravelpayoutsAPIError("Ожидался JSON-массив данных.")
            return payload

        if not isinstance(payload, dict):
            raise TravelpayoutsAPIError("Неожиданный формат ответа Travelpayouts API.")
        if payload.get("success") is False:
            raise TravelpayoutsAPIError(
                "Travelpayouts API вернул ошибку: {}".format(
                    payload.get("error") or "success=false"
                )
            )
        return payload

    # ------------------------------------------------------------- Data API
    def prices_for_dates(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        departure_at: Optional[str] = None,
        return_at: Optional[str] = None,
        one_way: bool = True,
        direct: bool = False,
        currency: Optional[str] = None,
        limit: int = 30,
        page: int = 1,
        sorting: str = "price",
        unique: bool = False,
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cheapest tickets found during the last 48 hours (cached ~7 days)."""
        return self._request(
            "/aviasales/v3/prices_for_dates",
            {
                "origin": (origin or "").upper() or None,
                "destination": (destination or "").upper() or None,
                "departure_at": departure_at,
                "return_at": return_at,
                "one_way": _bool(one_way),
                "direct": _bool(direct),
                "currency": currency or self.currency,
                "limit": limit,
                "page": page,
                "sorting": sorting,
                "unique": _bool(unique),
                "market": market or self.market,
            },
        )

    def grouped_prices(
        self,
        origin: str,
        destination: str,
        group_by: str = "departure_at",
        departure_at: Optional[str] = None,
        return_at: Optional[str] = None,
        direct: bool = False,
        currency: Optional[str] = None,
        market: Optional[str] = None,
        min_trip_duration: Optional[int] = None,
        max_trip_duration: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Prices grouped by departure date or month (calendar-like)."""
        return self._request(
            "/aviasales/v3/grouped_prices",
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "group_by": group_by,
                "departure_at": departure_at,
                "return_at": return_at,
                "direct": _bool(direct),
                "currency": currency or self.currency,
                "market": market or self.market,
                "min_trip_duration": min_trip_duration,
                "max_trip_duration": max_trip_duration,
            },
        )

    def month_matrix(
        self,
        origin: str,
        destination: str,
        month: Optional[str] = None,
        one_way: bool = True,
        currency: Optional[str] = None,
        limit: int = 31,
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cheapest price per day of a month (v2/prices/month-matrix)."""
        return self._request(
            "/v2/prices/month-matrix",
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "month": month,
                "one_way": _bool(one_way),
                "currency": currency or self.currency,
                "limit": limit,
                "market": market or self.market,
            },
        )

    def calendar(
        self,
        origin: str,
        destination: str,
        departure_date: Optional[str] = None,
        return_date: Optional[str] = None,
        calendar_type: str = "departure_date",
        currency: Optional[str] = None,
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cheapest ticket for each day of a month (v1/prices/calendar)."""
        return self._request(
            "/v1/prices/calendar",
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_date": departure_date,
                "return_date": return_date,
                "calendar_type": calendar_type,
                "currency": currency or self.currency,
                "market": market or self.market,
            },
        )

    def special_offers(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        currency: Optional[str] = None,
        locale: Optional[str] = None,
        airline: Optional[str] = None,
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Abnormally cheap deals (v3/get_special_offers)."""
        return self._request(
            "/aviasales/v3/get_special_offers",
            {
                "origin": (origin or "").upper() or None,
                "destination": (destination or "").upper() or None,
                "currency": currency or self.currency,
                "locale": locale or self.locale,
                "airline": (airline or "").upper() or None,
                "market": market or self.market,
            },
        )

    def popular_directions(
        self,
        destination: str,
        locale: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
    ) -> Dict[str, Any]:
        """Where people fly from to ``destination`` (v3/get_popular_directions)."""
        return self._request(
            "/aviasales/v3/get_popular_directions",
            {
                "destination": destination.upper(),
                "locale": locale or self.locale,
                "currency": currency or self.currency,
                "limit": max(1, min(int(limit), 30)),
                "page": page,
            },
        )

    def city_directions(
        self, origin: str, currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """Popular destinations from a city (v1/city-directions)."""
        return self._request(
            "/v1/city-directions",
            {"origin": origin.upper(), "currency": currency or self.currency},
        )

    def latest_prices(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        period_type: str = "year",
        beginning_of_period: Optional[str] = None,
        group_by: str = "directions",
        one_way: bool = True,
        currency: Optional[str] = None,
        page: int = 1,
        sorting: str = "price",
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recently found prices for a period (v3/get_latest_prices)."""
        return self._request(
            "/aviasales/v3/get_latest_prices",
            {
                "origin": (origin or "").upper() or None,
                "destination": (destination or "").upper() or None,
                "period_type": period_type,
                "beginning_of_period": beginning_of_period,
                "group_by": group_by,
                "one_way": _bool(one_way),
                "currency": currency or self.currency,
                "page": page,
                "sorting": sorting,
                "market": market or self.market,
            },
        )

    # -------------------------------------------------------- Partner Links
    def create_partner_links(
        self,
        urls: Sequence[str],
        trs: Optional[str] = None,
        marker: Optional[str] = None,
        sub_id: Optional[str] = None,
        shorten: bool = True,
    ) -> Dict[str, Any]:
        """Convert brand URLs into Travelpayouts partner links.

        Docs: ``POST /links/v1/create`` with
        ``{"trs": <project id>, "marker": <marker>, "shorten": true,
        "links": [{"url": "...", "sub_id": "..."}]}``.
        Limit: max 10 links per request, 100 requests/min per marker.
        """
        clean_urls = [u.strip() for u in urls if u and u.strip()]
        if not clean_urls:
            raise TravelpayoutsConfigError("Передайте хотя бы один URL.")
        if len(clean_urls) > MAX_LINKS_PER_REQUEST:
            raise TravelpayoutsConfigError(
                "Links API принимает не более {} ссылок за запрос.".format(
                    MAX_LINKS_PER_REQUEST
                )
            )
        project = (trs or _env(TRS_ENV)).strip()
        partner_marker = (marker or _env(MARKER_ENV)).strip()
        if not project or not partner_marker:
            raise TravelpayoutsConfigError(
                "Для создания партнёрских ссылок нужны ID проекта (trs) и "
                "маркер. Задайте TRAVELPAYOUTS_TRS и TRAVELPAYOUTS_MARKER "
                "(значения — в кабинете Travelpayouts: projects и marker)."
            )
        links = []
        for url in clean_urls:
            entry: Dict[str, Any] = {"url": url}
            if sub_id:
                entry["sub_id"] = str(sub_id)
            links.append(entry)
        body = {
            "trs": int(project) if project.isdigit() else project,
            "marker": int(partner_marker) if partner_marker.isdigit() else partner_marker,
            "shorten": bool(shorten),
            "links": links,
        }
        return self._request("/links/v1/create", method="POST", body=body)

    # ------------------------------------------------------------- Directory
    def _places(self, locale: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cities + airports directory, cached in memory per locale."""
        loc = (locale or self.locale or DEFAULT_LOCALE).lower()
        if loc in self._places_cache:
            return self._places_cache[loc]
        places: List[Dict[str, Any]] = []
        for kind, path in (
            ("city", "/data/{}/cities.json".format(loc)),
            ("airport", "/data/{}/airports.json".format(loc)),
        ):
            try:
                raw = self._request(path, auth=False, expect="array")
            except TravelpayoutsError:
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                code = item.get("code") or item.get("iata") or item.get("city_code")
                name = item.get("name") or item.get("city_name") or item.get("title")
                if not code or not name:
                    continue
                places.append(
                    {
                        "code": str(code).upper(),
                        "name": str(name),
                        "country": item.get("country_name")
                        or item.get("country_code")
                        or "",
                        "type": kind,
                    }
                )
        self._places_cache[loc] = places
        return places

    def find_places(
        self,
        query: str,
        locale: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Resolve an IATA code or a city name to IATA codes."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        places = self._places(locale)
        exact: List[Dict[str, Any]] = []
        prefix: List[Dict[str, Any]] = []
        contains: List[Dict[str, Any]] = []
        for place in places:
            code = place["code"].lower()
            name = place["name"].lower()
            if code == needle:
                exact.append(place)
            elif name == needle or name.startswith(needle):
                prefix.append(place)
            elif needle in name:
                contains.append(place)
        ordered = exact + prefix + contains
        # Prefer cities over airports, keep deterministic order for equal names.
        ordered.sort(key=lambda p: (p["type"] != "city",))
        result: List[Dict[str, Any]] = []
        seen = set()
        for place in ordered:
            key = (place["code"], place["type"])
            if key in seen:
                continue
            seen.add(key)
            result.append(place)
            if len(result) >= max(1, min(int(limit), 20)):
                break
        return result
