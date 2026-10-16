"""conf.researchr.org research-track pages, and the DOI backfill from DBLP."""

from unittest.mock import MagicMock, patch

import pytest

from ppr.dblp_client import DblpUnavailable
from ppr.scrapers import researchr
from ppr.scrapers.researchr import RESEARCHR_CONFERENCES, parse_track_page, track_url

URL = "https://conf.researchr.org/track/icse-2025/icse-2025-research-track"


def _row(event, title, track="Research Track", authors=("Al One", "Bea Two"),
         preprint=None, badge=False, badges=()):
    """One Accepted Papers row, shaped like the live ICSE 2025 page."""
    names = (["Artifact-Available"] if badge else []) + list(badges)
    badge_html = (
        '<span class="pull-right">' + "".join(
            f'<span title="{b}" data-facet-badge="{b}" class="output-badge">'
            f'<img alt="{b}" class="outputimage"/></span>' for b in names
        ) + "</span>"
        if names else ""
    )
    performers = ", ".join(
        f'<a href="https://conf.researchr.org/profile/x/p{i}" class="navigate">{a}</a>'
        for i, a in enumerate(authors)
    )
    link = (
        f'<a href="{preprint}" target="_blank" class="publication-link navigate">'
        '<span class="glyphicon glyphicon-link"></span> Pre-print</a>'
        if preprint else ""
    )
    return (
        f'<tr><td><span data-event-star="{event}"></span></td><td>'
        f'<a href="#" data-event-modal="{event}">{title}{badge_html}</a>'
        f'<div class="prog-track">{track}</div><div class="performers">{performers}</div>'
        f"{link}</td></tr>"
    )


def _page(rows, track="Research Track", conf="ICSE 2025", schedule=""):
    return (
        f"<html><head><title>{conf} - {track} - {conf}</title></head><body>{schedule}"
        '<div id="event-overview" class="tab-pane "><h3>Accepted Papers</h3>'
        '<table class="table table-condensed"><thead><tr><th></th><th>Title</th></tr></thead>'
        f"{''.join(rows)}</table></div></body></html>"
    )


def _ok(text):
    r = MagicMock()
    r.status_code = 200
    r.text = text
    r.raise_for_status = lambda: None
    return r


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("ppr.scrapers.researchr.time.sleep", lambda *_: None)
    monkeypatch.setattr(researchr, "_last_request", 0.0)


class TestTrackUrl:
    def test_builds_a_plain_path(self):
        """robots.txt disallows `/*?`: no query strings, ever."""
        assert track_url("icse", 2025, "research-track") == URL
        assert "?" not in track_url("ase", 2024, "research")


class TestParseTrackPage:
    def test_reads_the_track_name_titles_and_ordered_authors(self):
        track, rows = parse_track_page(_page([
            _row("e1", "3DGen: Provably Correct Parsers", authors=("Sarah Fakhoury", "Markus Kuppe")),
        ]))
        assert track == "Research Track"
        assert rows == [{"title": "3DGen: Provably Correct Parsers",
                         "authors": ["Sarah Fakhoury", "Markus Kuppe"], "link": "", "badges": []}]

    def test_badges_are_returned_and_kept_out_of_the_title(self):
        _, rows = parse_track_page(_page([_row("e1", "A Catalog of Anti-patterns",
                                               badges=("Distinguished Paper Award", "Artifact-Available"))]))
        assert rows[0]["title"] == "A Catalog of Anti-patterns"
        assert rows[0]["badges"] == ["Distinguished Paper Award", "Artifact-Available"]

    def test_badges_are_not_part_of_the_title(self):
        _, rows = parse_track_page(_page([_row("e1", "A Catalog of Anti-patterns", badge=True)]))
        assert rows[0]["title"] == "A Catalog of Anti-patterns"

    def test_a_session_tag_is_stripped(self):
        """FSE 2023 prefixes remote talks with "[Remote] "; left in, 35 titles
        never match DBLP's record of the same paper."""
        _, rows = parse_track_page(_page([_row("e1", "[Remote] A Generative Approach")]))
        assert rows[0]["title"] == "A Generative Approach"

    def test_rows_from_another_track_are_dropped(self):
        """Journal-first papers can sit in the research track's table."""
        _, rows = parse_track_page(_page([
            _row("e1", "Kept"), _row("e2", "Journal paper", track="Journal-first Papers"),
        ]))
        assert [r["title"] for r in rows] == ["Kept"]

    def test_the_schedule_tab_is_not_counted(self):
        """The page lists the same papers again in its schedule, outside #event-overview."""
        schedule = '<div id="program"><strong><a href="#" data-event-modal="e1">Kept</a></strong></div>'
        _, rows = parse_track_page(_page([_row("e1", "Kept")], schedule=schedule))
        assert len(rows) == 1

    def test_a_preprint_link_is_kept(self):
        _, rows = parse_track_page(_page([_row("e1", "T", preprint="https://arxiv.org/pdf/2404.10362")]))
        assert rows[0]["link"] == "https://arxiv.org/pdf/2404.10362"

    def test_a_call_for_papers_page_has_no_rows(self):
        """ICSE 2027's research-track page exists in October 2026, before any acceptances."""
        page = "<html><head><title>ICSE 2027 - Research Track - ICSE 2027</title></head><body>CFP</body></html>"
        assert parse_track_page(page) == ("Research Track", [])

    def test_a_lowercase_track_name_still_matches_its_rows(self):
        """ISSTA 2026 calls it "Research papers"."""
        track, rows = parse_track_page(_page([_row("e1", "T", track="Research papers")],
                                             track="Research papers", conf="ISSTA 2026"))
        assert track == "Research papers"
        assert len(rows) == 1


class TestScrape:
    def _register(self, monkeypatch, **extra):
        monkeypatch.setitem(RESEARCHR_CONFERENCES, "icse_2099",
                            {"url": URL, "track": "Research Track", **extra})

    def test_rows_become_main_papers(self, monkeypatch):
        self._register(monkeypatch)
        page = _page([_row("e1", "T", preprint="https://arxiv.org/abs/1")])
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(page)):
            papers = researchr._scrape_researchr("icse_2099")
        assert [(p.title, p.link, p.authors, p.selection) for p in papers] == [
            ("T", "https://arxiv.org/abs/1", ["Al One", "Bea Two"], "main"),
        ]

    def test_a_row_without_a_preprint_links_to_the_track_page(self, monkeypatch):
        self._register(monkeypatch)
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page([_row("e1", "T")]))):
            assert researchr._scrape_researchr("icse_2099")[0].link == URL

    def test_a_page_of_another_track_is_refused(self, monkeypatch):
        self._register(monkeypatch)
        page = _page([_row("e1", "T", track="Technical Track")], track="Technical Track")
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(page)):
            with pytest.raises(ValueError, match="Technical Track"):
                researchr._scrape_researchr("icse_2099")

    def test_dblp_records_replace_matched_rows(self, monkeypatch):
        self._register(monkeypatch, dblp={"key": "db/conf/icse/icse2025.bht"})
        rows = [_row(f"e{i}", f"Paper {i}") for i in range(9)] + [_row("e9", "Only On Researchr")]
        records = [{"title": f"Paper {i}", "link": f"https://doi.org/10.1/{i}",
                    "authors": ["Dblp Name"]} for i in range(9)]
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page(rows))), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers", return_value=records) as t:
            papers = researchr._scrape_researchr("icse_2099")
        t.assert_called_once_with("db/conf/icse/icse2025.bht", number=None)
        assert len(papers) == 10
        assert (papers[0].link, papers[0].authors) == ("https://doi.org/10.1/0", ["Dblp Name"])
        assert (papers[-1].title, papers[-1].link) == ("Only On Researchr", URL)

    def test_dblp_papers_absent_from_researchr_are_not_added(self, monkeypatch):
        """researchr decides membership: DBLP's toc also holds NIER, demo and industry papers."""
        self._register(monkeypatch, dblp={"key": "db/conf/kbse/ase2025.bht"})
        records = [{"title": "Kept", "link": "https://doi.org/10.1/k", "authors": ["A"]},
                   {"title": "A Tool Demo", "link": "https://doi.org/10.1/d", "authors": ["B"]}]
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page([_row("e1", "Kept")]))), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers", return_value=records):
            assert [p.title for p in researchr._scrape_researchr("icse_2099")] == ["Kept"]

    def test_the_join_is_by_title_key(self, monkeypatch):
        self._register(monkeypatch, dblp={"key": "db/conf/icse/icse2025.bht"})
        records = [{"title": "Bug-Exposing Tests", "link": "https://doi.org/10.1/b", "authors": ["A"]}]
        page = _page([_row("e1", "bug-exposing tests")])
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(page)), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers", return_value=records):
            assert researchr._scrape_researchr("icse_2099")[0].title == "Bug-Exposing Tests"

    def test_a_low_join_rate_fails_the_crawl(self, monkeypatch):
        """Under 80% matched means the `dblp` key is wrong, not that DBLP is a bit behind."""
        self._register(monkeypatch, dblp={"key": "db/conf/icse/icse2025.bht"})
        rows = [_row(f"e{i}", f"Paper {i}") for i in range(10)]
        records = [{"title": f"Paper {i}", "link": f"https://doi.org/10.1/{i}", "authors": ["A"]}
                   for i in range(7)]
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page(rows))), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers", return_value=records):
            with pytest.raises(ValueError, match="7/10"):
                researchr._scrape_researchr("icse_2099")

    def test_dblp_unavailable_fails_the_crawl(self, monkeypatch):
        """Never silently ship researchr links where DOIs were promised."""
        self._register(monkeypatch, dblp={"key": "db/conf/icse/icse2025.bht"})
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page([_row("e1", "T")]))), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers",
                   side_effect=DblpUnavailable("bot challenge (HTTP 202)")):
            with pytest.raises(DblpUnavailable):
                researchr._scrape_researchr("icse_2099")

    def test_number_reaches_dblp_for_a_shared_pacmse_volume(self, monkeypatch):
        self._register(monkeypatch, dblp={"key": "db/journals/pacmse/pacmse2.bht", "number": "ISSTA"})
        records = [{"title": "T", "link": "https://doi.org/10.1/t", "authors": ["A"]}]
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok(_page([_row("e1", "T")]))), \
             patch("ppr.scrapers.researchr.dblp_client.toc_papers", return_value=records) as t:
            researchr._scrape_researchr("icse_2099")
        t.assert_called_once_with("db/journals/pacmse/pacmse2.bht", number="ISSTA")


class TestPacing:
    def test_min_interval_is_researchr_crawl_delay(self):
        """conf.researchr.org/robots.txt: `Crawl-delay: 2` (checked 2026-10-14)."""
        assert researchr.MIN_INTERVAL == 2.0

    def test_consecutive_gets_are_spaced(self, monkeypatch):
        slept = []
        monkeypatch.setattr("ppr.scrapers.researchr.time.sleep", lambda s: slept.append(s))
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok("")):
            researchr.get(URL)
            researchr.get(URL)
        assert max(slept) > researchr.MIN_INTERVAL - 0.05

    def test_identifies_the_project_not_a_browser(self):
        with patch("ppr.scrapers.researchr.requests.get", return_value=_ok("")) as g:
            researchr.get(URL)
        assert "Mozilla" not in g.call_args.kwargs["headers"]["User-Agent"]


class TestRegistry:
    def test_every_entry_names_a_plain_track_url_and_a_track(self):
        for conf_id, conf in RESEARCHR_CONFERENCES.items():
            assert conf["url"].startswith("https://conf.researchr.org/track/"), conf_id
            assert "?" not in conf["url"], conf_id
            assert conf["track"], conf_id

    def test_scrapers_cover_the_registry(self):
        from ppr.scrapers import SCRAPERS

        assert set(RESEARCHR_CONFERENCES) <= set(SCRAPERS)


class TestShippedRegistry:
    """The 2023-2025 entries were written from a live probe on 2026-10-14."""

    EXPECTED = {
        "icse_2023": ("icse-2023-technical-track", "Technical Track", "db/conf/icse/icse2023.bht", None),
        "icse_2024": ("icse-2024-research-track", "Research Track", "db/conf/icse/icse2024.bht", None),
        "icse_2025": ("icse-2025-research-track", "Research Track", "db/conf/icse/icse2025.bht", None),
        "fse_2023": ("fse-2023-research-papers", "Research Papers", "db/conf/sigsoft/fse2023.bht", None),
        "fse_2024": ("fse-2024-research-papers", "Research Papers", "db/journals/pacmse/pacmse1.bht", None),
        "fse_2025": ("fse-2025-research-papers", "Research Papers", "db/journals/pacmse/pacmse2.bht", "FSE"),
        "ase_2023": ("ase-2023-papers", "Research Papers", "db/conf/kbse/ase2023.bht", None),
        "ase_2024": ("ase-2024-research", "Research Papers", "db/conf/kbse/ase2024.bht", None),
        "ase_2025": ("ase-2025-papers", "Research Papers", "db/conf/kbse/ase2025.bht", None),
        "issta_2023": ("issta-2023-technical-papers", "Technical Papers", "db/conf/issta/issta2023.bht", None),
        "issta_2024": ("issta-2024-papers", "Technical Papers", "db/conf/issta/issta2024.bht", None),
        "issta_2025": ("issta-2025-papers", "Research Papers", "db/journals/pacmse/pacmse2.bht", "ISSTA"),
    }

    @pytest.mark.parametrize("conf_id", sorted(EXPECTED))
    def test_entry(self, conf_id):
        slug, track, key, number = self.EXPECTED[conf_id]
        conf = RESEARCHR_CONFERENCES[conf_id]
        venue, year = conf_id.rsplit("_", 1)
        assert conf["url"] == f"https://conf.researchr.org/track/{venue}-{year}/{slug}"
        assert conf["track"] == track
        assert conf["dblp"]["key"] == key
        assert conf["dblp"].get("number") == number

    def test_se_years_left_dblp(self):
        from ppr.scrapers.dblp import DBLP_CONFERENCES

        assert not set(self.EXPECTED) & set(DBLP_CONFERENCES)
