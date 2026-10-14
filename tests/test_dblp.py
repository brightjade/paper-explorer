from unittest.mock import MagicMock, patch

from ppr.scrapers.dblp import (
    DBLP_CONFERENCES,
    SCRAPERS,
    _clean_author,
    _fetch_dblp,
    _scrape_dblp,
)


class TestCleanAuthor:
    def test_strips_four_digit_suffix(self):
        assert _clean_author("Hao Zhong 0001") == "Hao Zhong"

    def test_strips_different_suffix(self):
        assert _clean_author("Wei Meng 0003") == "Wei Meng"

    def test_no_suffix_unchanged(self):
        assert _clean_author("John Smith") == "John Smith"

    def test_name_ending_in_digits_not_suffix(self):
        # Only strip if preceded by space and exactly 4 digits at end
        assert _clean_author("Agent 47") == "Agent 47"

    def test_empty_string(self):
        assert _clean_author("") == ""


def _make_dblp_response(hits: list[dict], total: int) -> dict:
    """Build a minimal DBLP API response."""
    return {
        "result": {
            "hits": {
                "@total": str(total),
                "@sent": str(len(hits)),
                "@first": "0",
                "hit": [{"info": h} for h in hits],
            }
        }
    }


class TestFetchDblp:
    @patch("ppr.scrapers.dblp.requests.get")
    def test_returns_paper_info_dicts(self, mock_get):
        hits = [
            {
                "title": "Paper One.",
                "authors": {"author": [{"text": "Alice 0001"}]},
                "ee": "https://doi.org/10.1145/1",
                "venue": "ICSE",
                "year": "2024",
            },
            {
                "title": "Paper Two.",
                "authors": {"author": [{"text": "Bob"}]},
                "ee": "https://doi.org/10.1145/2",
                "venue": "ICSE",
                "year": "2024",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_dblp_response(hits, total=2)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _fetch_dblp("db/conf/icse/icse2024.bht")
        assert len(result) == 2
        assert result[0]["title"] == "Paper One."
        assert result[1]["authors"]["author"][0]["text"] == "Bob"

    @patch("ppr.scrapers.dblp.requests.get")
    def test_filters_by_number(self, mock_get):
        hits = [
            {
                "title": "FSE Paper.",
                "authors": {"author": [{"text": "Alice"}]},
                "ee": "https://doi.org/10.1145/1",
                "number": "FSE",
            },
            {
                "title": "ISSTA Paper.",
                "authors": {"author": [{"text": "Bob"}]},
                "ee": "https://doi.org/10.1145/2",
                "number": "ISSTA",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_dblp_response(hits, total=2)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _fetch_dblp("db/journals/pacmse/pacmse2.bht", number="FSE")
        assert len(result) == 1
        assert result[0]["title"] == "FSE Paper."

    @patch("ppr.scrapers.dblp.time.sleep")
    @patch("ppr.scrapers.dblp.requests.get")
    def test_paginates_when_more_than_1000(self, mock_get, mock_sleep):
        # First page: 1000 hits out of 1200 total
        page1_hits = [{"title": f"P{i}.", "authors": {"author": [{"text": "A"}]}, "ee": "https://x"} for i in range(1000)]
        resp1 = MagicMock()
        resp1.json.return_value = _make_dblp_response(page1_hits, total=1200)
        resp1.raise_for_status = MagicMock()

        # Second page: remaining 200
        page2_hits = [{"title": f"Q{i}.", "authors": {"author": [{"text": "B"}]}, "ee": "https://y"} for i in range(200)]
        resp2 = MagicMock()
        resp2.json.return_value = _make_dblp_response(page2_hits, total=1200)
        resp2.raise_for_status = MagicMock()

        mock_get.side_effect = [resp1, resp2]

        result = _fetch_dblp("db/conf/kbse/ase2025.bht")
        assert len(result) == 1200
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("ppr.scrapers.dblp.requests.get")
    def test_empty_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"hits": {"@total": "0", "@sent": "0", "@first": "0"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _fetch_dblp("db/conf/icse/icse2099.bht")
        assert result == []


class TestScrapeDblp:
    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_maps_dblp_to_paper_objects(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Some Great Paper.",
                "authors": {"author": [
                    {"text": "Alice Smith 0001"},
                    {"text": "Bob Jones"},
                ]},
                "ee": "https://doi.org/10.1145/12345",
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert len(papers) == 1
        p = papers[0]
        assert p.title == "Some Great Paper"
        assert p.authors == ["Alice Smith", "Bob Jones"]
        assert p.link == "https://doi.org/10.1145/12345"
        assert p.selection == "main"

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_strips_trailing_dot_from_title(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Title With Dot.",
                "authors": {"author": [{"text": "Alice"}]},
                "ee": "https://doi.org/10.1145/1",
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert papers[0].title == "Title With Dot"

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_unescapes_html_entities_in_title(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "That&apos;s a Tough Call.",
                "authors": {"author": [{"text": "Alice"}]},
                "ee": "https://doi.org/10.1145/1",
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert papers[0].title == "That's a Tough Call"

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_handles_single_author(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Solo Paper.",
                "authors": {"author": {"text": "Solo Author 0002"}},
                "ee": "https://doi.org/10.1145/1",
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert papers[0].authors == ["Solo Author"]

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_skips_entries_without_ee(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "No Link Paper.",
                "authors": {"author": [{"text": "Alice"}]},
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert len(papers) == 0

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_handles_ee_as_list(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Multi Link.",
                "authors": {"author": [{"text": "Alice"}]},
                "ee": ["https://doi.org/10.1145/1", "https://doi.org/10.1145/2"],
            },
        ]
        papers = _scrape_dblp("icse_2024")
        assert len(papers) == 1
        assert papers[0].link == "https://doi.org/10.1145/1"

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_passes_number_for_pacmse(self, mock_fetch):
        mock_fetch.return_value = []
        _scrape_dblp("fse_2025")
        mock_fetch.assert_called_once_with(
            "db/journals/pacmse/pacmse2.bht", number="FSE"
        )

    @patch("ppr.scrapers.dblp._fetch_dblp")
    def test_no_number_for_traditional(self, mock_fetch):
        mock_fetch.return_value = []
        _scrape_dblp("icse_2024")
        mock_fetch.assert_called_once_with(
            "db/conf/icse/icse2024.bht", number=None
        )


class TestScrapersDict:
    def test_all_conferences_registered(self):
        for conf_id in DBLP_CONFERENCES:
            assert conf_id in SCRAPERS, f"{conf_id} not in SCRAPERS"

    def test_expected_conference_ids(self):
        expected = {
            "icse_2023", "icse_2024", "icse_2025",
            "fse_2023", "fse_2024", "fse_2025",
            "ase_2023", "ase_2024", "ase_2025",
            "issta_2023", "issta_2024", "issta_2025",
            # Robotics
            "icra_2023", "icra_2024", "icra_2025",
            "iros_2023", "iros_2024", "iros_2025",
            "rss_2023", "rss_2024",
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
