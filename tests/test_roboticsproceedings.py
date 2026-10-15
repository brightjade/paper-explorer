"""RSS from roboticsproceedings.org."""

from unittest.mock import MagicMock, patch

import pytest

from ppr.scrapers import roboticsproceedings as rp
from ppr.scrapers.roboticsproceedings import (
    ROBOTICSPROCEEDINGS_CONFERENCES,
    index_url,
    parse_index,
    roman,
)


def _entry(number, title, authors="Pascal Roth, Jonas Frey, Cesar Cadena"):
    """One table row, shaped like rss21/index.html."""
    italic = f"<i>{authors}</i><br>" if authors is not None else ""
    return (
        "<tr><td width=500>"
        f'<a href="p{number}.html">{title}</a><br>{italic}'
        f'</td><td valign=top><a href="p{number}.pdf" target="_blank"><img src="../icon-pdf.png"></a>'
        "</td></tr><tr><td>&nbsp</td></tr>"
    )


def _index(rows):
    return (
        '<html><body><div id="menu"><a class="menu" href="../rss01/index.html">Content</a></div>'
        '<div class="content"><h1>Robotics: Science and Systems XXI</h1><h2>Table of Contents</h2>'
        f"<table>{''.join(rows)}</table></div></body></html>"
    )


class TestRoman:
    @pytest.mark.parametrize("n,expected", [(19, "XIX"), (20, "XX"), (21, "XXI"), (22, "XXII"), (4, "IV"), (9, "IX")])
    def test_numerals(self, n, expected):
        assert roman(n) == expected


class TestIndexUrl:
    def test_two_digit_volume(self):
        assert index_url(22) == "https://roboticsproceedings.org/rss22/index.html"


class TestParseIndex:
    def test_papers_get_titles_ordered_authors_and_derived_dois(self):
        papers = parse_index(_index([
            _entry("001", "Learned Perceptive Forward Dynamics Model"),
            _entry("163", "Last Paper", "Ann Lee"),
        ]), year=2025, volume=21)
        assert [(p.title, p.authors, p.link, p.selection) for p in papers] == [
            ("Learned Perceptive Forward Dynamics Model", ["Pascal Roth", "Jonas Frey", "Cesar Cadena"],
             "https://doi.org/10.15607/RSS.2025.XXI.001", "main"),
            ("Last Paper", ["Ann Lee"], "https://doi.org/10.15607/RSS.2025.XXI.163", "main"),
        ]

    def test_menu_and_pdf_links_are_not_papers(self):
        assert len(parse_index(_index([_entry("001", "Only")]), year=2025, volume=21)) == 1

    def test_a_row_without_authors_does_not_borrow_the_next_rows(self):
        papers = parse_index(_index([_entry("001", "No Authors", authors=None),
                                     _entry("002", "Has Authors", "Bo Kim")]), year=2026, volume=22)
        assert papers[0].authors == []
        assert papers[1].authors == ["Bo Kim"]

    def test_whitespace_in_titles_is_collapsed(self):
        papers = parse_index(_index([_entry("001", "Two\n   Lines")]), year=2026, volume=22)
        assert papers[0].title == "Two Lines"


class TestScrape:
    def test_scrapes_a_registered_volume(self):
        r = MagicMock()
        r.status_code = 200
        r.text = _index([_entry("001", "T")])
        r.raise_for_status = lambda: None
        with patch("ppr.scrapers.roboticsproceedings.requests.get", return_value=r) as g:
            papers = rp._scrape_roboticsproceedings("rss_2025")
        assert g.call_args.args[0] == "https://roboticsproceedings.org/rss21/index.html"
        assert papers[0].link == "https://doi.org/10.15607/RSS.2025.XXI.001"


class TestRegistry:
    def test_rss_2023_to_2025_are_volumes_19_to_21(self):
        assert {k: v["volume"] for k, v in ROBOTICSPROCEEDINGS_CONFERENCES.items()
                if k in ("rss_2023", "rss_2024", "rss_2025")} == {
            "rss_2023": 19, "rss_2024": 20, "rss_2025": 21,
        }

    def test_volume_is_year_minus_2004(self):
        for conf_id, conf in ROBOTICSPROCEEDINGS_CONFERENCES.items():
            assert int(conf_id.rsplit("_", 1)[1]) - 2004 == conf["volume"], conf_id

    def test_scrapers_cover_the_registry(self):
        from ppr.scrapers import SCRAPERS

        assert set(ROBOTICSPROCEEDINGS_CONFERENCES) <= set(SCRAPERS)
