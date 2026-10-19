from unittest.mock import patch

import pytest

from ppr.scrapers.dblp import (
    DBLP_CONFERENCES,
    SCRAPERS,
    EmptyTocError,
    _scrape_dblp,
    load_backfill,
    merge_backfill,
)


class TestScrapeDblp:
    def test_maps_records_to_main_papers(self):
        records = [{"title": "A Paper", "link": "https://doi.org/10.1/a",
                    "authors": ["Al One", "Bea Two"]}]
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=records) as t:
            papers = _scrape_dblp("icra_2023")
        t.assert_called_once_with("db/conf/icra/icra2023.bht")
        assert [(p.title, p.link, p.authors, p.selection) for p in papers] == [
            ("A Paper", "https://doi.org/10.1/a", ["Al One", "Bea Two"], "main"),
        ]

    def test_skips_records_without_a_link(self):
        """A paper a reader cannot open is not one we list."""
        records = [{"title": "Kept", "link": "https://doi.org/10.1/a", "authors": ["A"]},
                   {"title": "Dropped", "link": "", "authors": ["B"]}]
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=records):
            assert [p.title for p in _scrape_dblp("icra_2023")] == ["Kept"]


class TestScrapersDict:
    def test_all_conferences_registered(self):
        for conf_id in DBLP_CONFERENCES:
            assert conf_id in SCRAPERS, f"{conf_id} not in SCRAPERS"

    def test_expected_conference_ids(self):
        expected = {
            # Robotics
            "icra_2023", "icra_2024", "icra_2025",
            "iros_2023", "iros_2024", "iros_2025",
            # AI
            "ijcai_2023", "ijcai_2024", "ijcai_2025",
        }
        # A subset, not equality: the monthly pipeline registers new
        # conference-years on its own, and an equality check would fail every
        # one of them. Dropping an existing registration still fails here.
        assert expected <= set(DBLP_CONFERENCES.keys())

    def test_scrapers_are_callable(self):
        for conf_id, scraper in SCRAPERS.items():
            assert callable(scraper), f"{conf_id} scraper is not callable"


class TestBackfillEntries:
    def _entry(self, monkeypatch, tocs):
        monkeypatch.setitem(DBLP_CONFERENCES, "acl_2021", {"tocs": tocs})

    def test_each_toc_tags_its_own_selection(self, monkeypatch):
        self._entry(monkeypatch, [{"key": "db/conf/acl/acl2021-1.bht", "selection": "main"},
                                  {"key": "db/conf/acl/acl2021f.bht", "selection": "findings"}])
        by_key = {
            "db/conf/acl/acl2021-1.bht": [{"title": "Long", "link": "https://doi.org/1", "authors": ["A"]}],
            "db/conf/acl/acl2021f.bht": [{"title": "Find", "link": "https://doi.org/2", "authors": ["B"]}],
        }
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", side_effect=lambda k: by_key[k]):
            papers = _scrape_dblp("acl_2021")
        assert [(p.title, p.selection) for p in papers] == [("Long", "main"), ("Find", "findings")]

    def test_a_toc_with_no_records_fails_the_conference(self, monkeypatch):
        self._entry(monkeypatch, [{"key": "db/conf/acl/acl2021-1.bht", "selection": "main"}])
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=[]):
            with pytest.raises(EmptyTocError):
                _scrape_dblp("acl_2021")

    def test_a_toc_whose_records_all_lack_links_fails_too(self, monkeypatch):
        # Review focus 1: zero papers after the link filter is the same error.
        self._entry(monkeypatch, [{"key": "db/conf/acl/acl2021-1.bht", "selection": "main"}])
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers",
                   return_value=[{"title": "T", "link": "", "authors": ["A"]}]):
            with pytest.raises(EmptyTocError):
                _scrape_dblp("acl_2021")

    def test_single_key_entries_still_return_empty(self):
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=[]):
            assert _scrape_dblp("icra_2023") == []


class TestLoadBackfill:
    @staticmethod
    def _venue_file(tmp_path, body):
        (tmp_path / "acl").mkdir(exist_ok=True)
        (tmp_path / "acl" / "dblp.yaml").write_text(body)

    def test_no_venue_file_is_empty(self, tmp_path):
        assert load_backfill(tmp_path) == {}

    def test_empty_mapping(self, tmp_path):
        self._venue_file(tmp_path, "# header\n{}\n")
        assert load_backfill(tmp_path) == {}

    def test_entry_without_tocs_is_refused(self, tmp_path):
        self._venue_file(tmp_path, "2021:\n  tocs: []\n")
        with pytest.raises(ValueError, match="2021"):
            load_backfill(tmp_path)

    def test_reads_tocs(self, tmp_path):
        self._venue_file(
            tmp_path, "2021:\n  tocs:\n    - {key: db/conf/acl/acl2021-1.bht, selection: main}\n")
        assert load_backfill(tmp_path) == {
            "acl_2021": {"tocs": [{"key": "db/conf/acl/acl2021-1.bht", "selection": "main"}]}}

    def test_merge_refuses_an_id_already_in_dblp_py(self):
        with pytest.raises(ValueError, match="icra_2023"):
            merge_backfill({"icra_2023": {"key": "x"}}, {"icra_2023": {"tocs": []}})
