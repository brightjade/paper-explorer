from unittest.mock import patch

from ppr.scrapers.dblp import DBLP_CONFERENCES, SCRAPERS, _scrape_dblp


class TestScrapeDblp:
    def test_maps_records_to_main_papers(self):
        records = [{"title": "A Paper", "link": "https://doi.org/10.1/a",
                    "authors": ["Al One", "Bea Two"]}]
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=records) as t:
            papers = _scrape_dblp("icra_2023")
        t.assert_called_once_with("db/conf/icra/icra2023.bht", number=None)
        assert [(p.title, p.link, p.authors, p.selection) for p in papers] == [
            ("A Paper", "https://doi.org/10.1/a", ["Al One", "Bea Two"], "main"),
        ]

    def test_skips_records_without_a_link(self):
        """The search-API scraper skipped entries without an `ee`; a paper a
        reader cannot open is not one we list."""
        records = [{"title": "Kept", "link": "https://doi.org/10.1/a", "authors": ["A"]},
                   {"title": "Dropped", "link": "", "authors": ["B"]}]
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=records):
            assert [p.title for p in _scrape_dblp("icra_2023")] == ["Kept"]

    def test_passes_number_for_a_shared_pacmse_volume(self, monkeypatch):
        monkeypatch.setitem(DBLP_CONFERENCES, "fse_2099",
                            {"key": "db/journals/pacmse/pacmse9.bht", "number": "FSE"})
        with patch("ppr.scrapers.dblp.dblp_client.toc_papers", return_value=[]) as t:
            _scrape_dblp("fse_2099")
        t.assert_called_once_with("db/journals/pacmse/pacmse9.bht", number="FSE")


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
