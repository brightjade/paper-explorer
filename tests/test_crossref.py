"""ICRA and IROS from Crossref, by exact proceedings title."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ppr.scrapers import crossref
from ppr.scrapers.crossref import (
    CROSSREF_CONFERENCES,
    CrossrefUnavailable,
    clean_title,
    count,
    fetch_items,
    parse_items,
    work_filter,
)

ICRA_2025 = "2025 IEEE International Conference on Robotics and Automation (ICRA)"


def _resp(message=None, status=200, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.json = lambda: {"status": "ok", "message": message or {}}
    return r


def _item(doi, title, authors=(("Al", "One"), ("Bea", "Two"))):
    return {"DOI": doi, "title": [title],
            "author": [{"given": g, "family": f, "sequence": "additional"} for g, f in authors]}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("ppr.scrapers.crossref.time.sleep", lambda *_: None)
    monkeypatch.setattr(crossref, "_last_request", 0.0)


class TestFilter:
    def test_names_prefix_type_and_exact_container(self):
        assert work_filter("10.1109", ICRA_2025) == (
            f"prefix:10.1109,type:proceedings-article,container-title:{ICRA_2025}"
        )

    def test_a_comma_in_the_container_is_refused(self):
        """Crossref's filter list is comma-separated; a comma would split the title."""
        with pytest.raises(ValueError):
            work_filter("10.1109", "Proceedings, Volume 1")


class TestCount:
    def test_reads_total_results_without_fetching_items(self):
        with patch("ppr.scrapers.crossref.requests.get",
                   return_value=_resp({"total-results": 1882, "items": []})) as g:
            assert count("10.1109", ICRA_2025) == 1882
        assert g.call_args.kwargs["params"]["rows"] == 0

    def test_sends_no_email_address(self):
        """The polite pool wants a mailto; this project does not send the user's."""
        with patch("ppr.scrapers.crossref.requests.get",
                   return_value=_resp({"total-results": 0, "items": []})) as g:
            count("10.1109", ICRA_2025)
        sent = str(g.call_args)
        assert "mailto" not in sent
        assert "@" not in g.call_args.kwargs["headers"]["User-Agent"]

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retries_overload_then_succeeds(self, status):
        with patch("ppr.scrapers.crossref.requests.get",
                   side_effect=[_resp(status=status), _resp({"total-results": 3, "items": []})]):
            assert count("10.1109", ICRA_2025) == 3

    def test_persistent_throttling_raises(self):
        with patch("ppr.scrapers.crossref.requests.get", return_value=_resp(status=429)) as g:
            with pytest.raises(CrossrefUnavailable):
                count("10.1109", ICRA_2025)
        assert g.call_count == crossref.MAX_RETRIES

    def test_a_network_error_is_retried(self):
        with patch("ppr.scrapers.crossref.requests.get",
                   side_effect=[requests.ConnectionError(), _resp({"total-results": 1, "items": []})]):
            assert count("10.1109", ICRA_2025) == 1

    def test_a_non_retryable_status_raises_at_once(self):
        with patch("ppr.scrapers.crossref.requests.get", return_value=_resp(status=400)) as g:
            with pytest.raises(CrossrefUnavailable, match="400"):
                count("10.1109", ICRA_2025)
        assert g.call_count == 1

    @pytest.mark.parametrize("message", [{"items": []}, {"total-results": None}, {"total-results": "many"}])
    def test_an_unexpected_shape_raises_unavailable(self, message):
        with patch("ppr.scrapers.crossref.requests.get", return_value=_resp(message)):
            with pytest.raises(CrossrefUnavailable, match="unparseable response"):
                count("10.1109", ICRA_2025)


class TestFetchItems:
    def test_follows_the_cursor_until_every_item_is_in(self):
        pages = [
            _resp({"total-results": 3, "items": [_item("10.1/a", "A"), _item("10.1/b", "B")],
                   "next-cursor": "c2"}),
            _resp({"total-results": 3, "items": [_item("10.1/c", "C")], "next-cursor": "c3"}),
        ]
        with patch("ppr.scrapers.crossref.requests.get", side_effect=pages) as g:
            items = fetch_items("10.1109", ICRA_2025)
        assert [i["DOI"] for i in items] == ["10.1/a", "10.1/b", "10.1/c"]
        assert g.call_args_list[0].kwargs["params"]["cursor"] == "*"
        assert g.call_args_list[1].kwargs["params"]["cursor"] == "c2"

    def test_a_cursor_that_ends_short_raises(self):
        """A partial list could slip under autoregister's 10% check."""
        pages = [
            _resp({"total-results": 5, "items": [_item("10.1/a", "A")], "next-cursor": "c2"}),
            _resp({"total-results": 5, "items": [], "next-cursor": "c3"}),
        ]
        with patch("ppr.scrapers.crossref.requests.get", side_effect=pages):
            with pytest.raises(CrossrefUnavailable, match="1 of 5"):
                fetch_items("10.1109", ICRA_2025)

    def test_a_page_without_a_next_cursor_raises_unavailable(self):
        page = _resp({"total-results": 5, "items": [_item("10.1/a", "A")]})
        with patch("ppr.scrapers.crossref.requests.get", return_value=page):
            with pytest.raises(CrossrefUnavailable, match="unparseable response"):
                fetch_items("10.1109", ICRA_2025)

    def test_a_page_without_total_results_raises_unavailable(self):
        with patch("ppr.scrapers.crossref.requests.get", return_value=_resp({"items": []})):
            with pytest.raises(CrossrefUnavailable, match="unparseable response"):
                fetch_items("10.1109", ICRA_2025)

    def test_nothing_published_is_an_empty_list(self):
        with patch("ppr.scrapers.crossref.requests.get",
                   return_value=_resp({"total-results": 0, "items": []})):
            assert fetch_items("10.1109", ICRA_2025) == []


class TestParseItems:
    def test_maps_items_to_main_papers_with_doi_links(self):
        papers = parse_items([_item("10.1109/icra55743.2025.1", "Segment Any Repeated Object")])
        assert [(p.title, p.link, p.authors, p.selection) for p in papers] == [
            ("Segment Any Repeated Object", "https://doi.org/10.1109/icra55743.2025.1",
             ["Al One", "Bea Two"], "main"),
        ]

    def test_front_matter_is_exactly_the_items_without_authors(self):
        """ICRA 2025: 1,610 records, 6 author-less (Conference Information,
        Program, Welcome, Table of Contents, Top Menu, Author Index), 1,604 papers."""
        items = [_item("10.1/p", "A Paper"),
                 {"DOI": "10.1/toc", "title": ["Table of Contents"]},
                 {"DOI": "10.1/idx", "title": ["ICRA 2025 Author Index"], "author": []}]
        assert [p.title for p in parse_items(items)] == ["A Paper"]

    def test_markup_and_entities_are_stripped_from_titles(self):
        assert clean_title("A Full-Optical (PDM<sup>2</sup>) Sensor") == "A Full-Optical (PDM2) Sensor"
        assert clean_title("This&amp;That: Language-Gesture Control") == "This&That: Language-Gesture Control"
        assert clean_title("S\n   <sup>2</sup>\n   BEV: Lightweight") == "S 2 BEV: Lightweight"

    def test_an_organisation_author_keeps_its_name(self):
        item = {"DOI": "10.1/o", "title": ["T"], "author": [{"name": "The Robotics Consortium"}]}
        assert parse_items([item])[0].authors == ["The Robotics Consortium"]

    def test_author_order_is_preserved(self):
        item = _item("10.1/x", "T", authors=(("Zed", "Last"), ("Amy", "First")))
        assert parse_items([item])[0].authors == ["Zed Last", "Amy First"]


class TestScrape:
    def test_scrapes_a_registered_conference(self, monkeypatch):
        monkeypatch.setitem(CROSSREF_CONFERENCES, "icra_2099",
                            {"prefix": "10.1109", "container": ICRA_2025})
        with patch("ppr.scrapers.crossref.requests.get",
                   return_value=_resp({"total-results": 1, "items": [_item("10.1/a", "A")]})):
            papers = crossref._scrape_crossref("icra_2099")
        assert [p.link for p in papers] == ["https://doi.org/10.1/a"]


class TestPacing:
    def test_min_interval_is_one_second(self):
        assert crossref.MIN_INTERVAL == 1.0

    def test_consecutive_requests_are_spaced(self, monkeypatch):
        slept = []
        monkeypatch.setattr("ppr.scrapers.crossref.time.sleep", lambda s: slept.append(s))
        with patch("ppr.scrapers.crossref.requests.get",
                   return_value=_resp({"total-results": 0, "items": []})):
            count("10.1109", ICRA_2025)
            count("10.1109", ICRA_2025)
        assert max(slept) > crossref.MIN_INTERVAL - 0.05


class TestRegistry:
    def test_scrapers_cover_the_registry(self):
        from ppr.scrapers import SCRAPERS

        assert set(CROSSREF_CONFERENCES) <= set(SCRAPERS)
