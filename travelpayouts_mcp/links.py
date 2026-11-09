"""Deep-link builders for Aviasales search URLs (stdlib only).

Two URL styles are documented by Travelpayouts (2026):

* filled search form — ``https://www.aviasales.ru/?params=PARAMS``
* search results   — ``https://www.aviasales.ru/search/PARAMS``

``PARAMS`` encodes IATA codes, dates (DDMM) and passenger counts, e.g.
``MOW1607IST2007c321`` = Moscow → Istanbul 16.07, back 20.07, business,
3 adults + 2 children + 1 infant.

Tracking note: a raw search URL is **not** an affiliate link. In 2026
Travelpayouts issues branded short links via the Partner Links API
(``create_partner_links`` MCP tool); the old ``tp.media/r?...`` format is
retired (404). Do not paste raw URLs into content expecting commissions.
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

DEFAULT_DOMAIN = "www.aviasales.ru"

#: Travel class → Aviasales params code.
TRAVEL_CLASSES = {
    "economy": "",
    "comfort": "w",
    "business": "c",
    "first": "f",
    "": "",
    "e": "",
    "w": "w",
    "c": "c",
    "f": "f",
}


class LinkBuildError(ValueError):
    """Invalid route, date, passenger count or travel class."""


def normalize_domain(domain: Optional[str] = None) -> str:
    """Return a bare host, accepting values with or without scheme/slashes."""
    value = (domain or DEFAULT_DOMAIN).strip()
    if "://" in value:
        value = urllib.parse.urlsplit(value).netloc or value.split("://", 1)[1]
    return value.strip("/")


def _iata(value: str, field: str) -> str:
    code = (value or "").strip().upper()
    if not (2 <= len(code) <= 3) or not code.isalpha():
        raise LinkBuildError(
            "{} должен быть IATA-кодом (2–3 латинские буквы), получено: {!r}".format(
                field, value
            )
        )
    return code


def _ddmm(value: str, field: str) -> str:
    """Convert ``YYYY-MM-DD`` to the ``DDMM`` segment used by Aviasales."""
    text = (value or "").strip()
    if not text:
        raise LinkBuildError("Дата {} обязательна (YYYY-MM-DD).".format(field))
    parts = text.split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        raise LinkBuildError(
            "Дата {} должна быть в формате YYYY-MM-DD, получено: {!r}".format(
                field, value
            )
        )
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        raise LinkBuildError("Некорректная дата {}: {!r}".format(field, value))
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        raise LinkBuildError("Некорректная дата {}: {!r}".format(field, value))
    return "{:02d}{:02d}".format(int(day), int(month))


def _passengers(count: int, field: str) -> str:
    try:
        value = int(count)
    except (TypeError, ValueError):
        raise LinkBuildError("{} должен быть числом 0–9.".format(field))
    if not 0 <= value <= 9:
        raise LinkBuildError("{} должен быть в диапазоне 0–9.".format(field))
    return str(value)


def build_search_params(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    travel_class: str = "economy",
) -> str:
    """Build the Aviasales ``params`` string (see module docstring).

    Example: ``build_search_params("MOW", "IST", "2026-07-16", "2026-07-20",
    adults=3, children=2, infants=1, travel_class="business")`` →
    ``MOW1607IST2007c321``.
    """
    origin_code = _iata(origin, "origin")
    destination_code = _iata(destination, "destination")
    if departure_date:
        params = origin_code + _ddmm(departure_date, "departure_date") + destination_code
        if return_date:
            params += _ddmm(return_date, "return_date")
    elif return_date:
        raise LinkBuildError("return_date указан без departure_date.")
    else:
        # Filled-form link without dates: route only, e.g. MOWIST.
        params = origin_code + destination_code

    if adults < 1:
        raise LinkBuildError("Нужен хотя бы один взрослый пассажир (adults >= 1).")
    class_code = TRAVEL_CLASSES.get((travel_class or "").strip().lower())
    if class_code is None:
        raise LinkBuildError(
            "Неизвестный класс: {!r}. Допустимо: economy, comfort, business, first.".format(
                travel_class
            )
        )
    params += class_code
    # Adults are mandatory; children/infants are appended only when needed.
    # Trailing zero counts are omitted (docs: "1" = one adult, "c321" = family),
    # but inner zeros are kept (docs: "w101" = 1 adult + 0 children + 1 infant).
    passenger_digits = [
        _passengers(adults, "adults"),
        _passengers(children, "children"),
        _passengers(infants, "infants"),
    ]
    while len(passenger_digits) > 1 and passenger_digits[-1] == "0":
        passenger_digits.pop()
    params += "".join(passenger_digits)
    return params


def filled_form_url(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    travel_class: str = "economy",
    domain: Optional[str] = None,
) -> str:
    """URL that opens Aviasales with a pre-filled search form."""
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
    host = normalize_domain(domain)
    return "https://{}/?params={}".format(host, params)


def results_url(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    travel_class: str = "economy",
    domain: Optional[str] = None,
) -> str:
    """URL that opens Aviasales search results for the route."""
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
    host = normalize_domain(domain)
    return "https://{}/search/{}".format(host, params)


def search_url_from_api_link(link: str, domain: Optional[str] = None) -> str:
    """Turn the ``link`` field returned by the Data API into a full URL.

    The Data API returns codes like ``/MOW0103DXB10032?t=...``; docs say to
    append them to ``https://www.aviasales.ru/search/``.
    """
    code = (link or "").strip()
    if not code:
        raise LinkBuildError("Пустая ссылка из Data API.")
    if code.startswith("http://") or code.startswith("https://"):
        return code
    if not code.startswith("/"):
        code = "/" + code
    host = normalize_domain(domain)
    # The 2026 API returns either "/MOW0103DXB10032?t=..." (legacy docs) or
    # "/search/MOW1011IST1?t=..." (current responses). Avoid doubling "search".
    if code.startswith("/search/"):
        return "https://{}{}".format(host, code)
    return "https://{}/search{}".format(host, code)


def with_marker(url: str, marker: str, sub_id: Optional[str] = None) -> str:
    """Attach ``marker``/``subid`` query params to an Aviasales URL.

    Compatibility helper: for production affiliate links use the Partner
    Links API (``create_partner_links``) instead — Travelpayouts recommends
    branded short links and validates tracking on their side.
    """
    marker = (marker or "").strip()
    if not marker:
        raise LinkBuildError("Пустой маркер Travelpayouts.")
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc:
        raise LinkBuildError("Ожидался абсолютный URL, получено: {!r}".format(url))
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["marker"] = marker
    if sub_id:
        query["subid"] = str(sub_id)
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )
