"""Tests for Travelpayouts deep-link builders (offline, stdlib unittest)."""

from __future__ import annotations

import unittest

from travelpayouts_mcp.links import (
    LinkBuildError,
    build_search_params,
    filled_form_url,
    results_url,
    search_url_from_api_link,
    with_marker,
)


class BuildSearchParamsTests(unittest.TestCase):
    def test_family_business_round_trip(self) -> None:
        params = build_search_params(
            "MOW",
            "IST",
            "2026-07-16",
            "2026-07-20",
            adults=3,
            children=2,
            infants=1,
            travel_class="business",
        )
        self.assertEqual(params, "MOW1607IST2007c321")

    def test_one_way_economy_single_adult(self) -> None:
        params = build_search_params("mow", "led", "2026-07-16")
        self.assertEqual(params, "MOW1607LED1")

    def test_filled_form_without_dates(self) -> None:
        self.assertEqual(build_search_params("MOW", "IST"), "MOWIST1")

    def test_comfort_and_first_classes(self) -> None:
        self.assertEqual(
            build_search_params("MOW", "IST", travel_class="comfort"), "MOWISTw1"
        )
        self.assertEqual(
            build_search_params("MOW", "IST", travel_class="first"), "MOWISTf1"
        )

    def test_country_destination_two_letters(self) -> None:
        self.assertEqual(build_search_params("MOW", "TH"), "MOWTH1")

    def test_invalid_iata(self) -> None:
        with self.assertRaises(LinkBuildError):
            build_search_params("M", "IST")
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW1", "IST")

    def test_invalid_date(self) -> None:
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", "16.07.2026")
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", "2026-13-01")

    def test_return_without_departure(self) -> None:
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", None, "2026-07-20")

    def test_invalid_passengers(self) -> None:
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", adults=0)
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", children=10)

    def test_invalid_travel_class(self) -> None:
        with self.assertRaises(LinkBuildError):
            build_search_params("MOW", "IST", travel_class="luxury")


class UrlTests(unittest.TestCase):
    def test_results_url(self) -> None:
        url = results_url("MOW", "LED", "2026-07-16")
        self.assertEqual(url, "https://www.aviasales.ru/search/MOW1607LED1")

    def test_filled_form_url_custom_domain(self) -> None:
        url = filled_form_url("MOW", "LED", domain="https://www.aviasales.com/")
        self.assertEqual(url, "https://www.aviasales.com/?params=MOWLED1")

    def test_search_url_from_api_link(self) -> None:
        url = search_url_from_api_link("/MOW0103DXB10032?t=abc&search_date=1")
        self.assertEqual(
            url, "https://www.aviasales.ru/search/MOW0103DXB10032?t=abc&search_date=1"
        )

    def test_search_url_from_current_api_link_with_search_prefix(self) -> None:
        url = search_url_from_api_link("/search/MOW1011IST1?t=DP1794")
        self.assertEqual(
            url, "https://www.aviasales.ru/search/MOW1011IST1?t=DP1794"
        )

    def test_search_url_from_full_link(self) -> None:
        url = search_url_from_api_link("https://example.com/search/MOWLED1")
        self.assertEqual(url, "https://example.com/search/MOWLED1")

    def test_search_url_from_bare_code(self) -> None:
        self.assertEqual(
            search_url_from_api_link("MOWLED1", domain="www.aviasales.com"),
            "https://www.aviasales.com/search/MOWLED1",
        )

    def test_empty_api_link(self) -> None:
        with self.assertRaises(LinkBuildError):
            search_url_from_api_link("")

    def test_with_marker(self) -> None:
        url = with_marker(
            "https://www.aviasales.ru/search/MOWLED1?t=abc", "674170", "seo_en"
        )
        self.assertIn("marker=674170", url)
        self.assertIn("subid=seo_en", url)
        self.assertIn("t=abc", url)

    def test_with_marker_empty(self) -> None:
        with self.assertRaises(LinkBuildError):
            with_marker("https://www.aviasales.ru/", "")


if __name__ == "__main__":
    unittest.main()
