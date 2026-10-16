from datetime import date

import pytest

from scripts.impact import (
    PaperImpact,
    build_top,
    cohort_of,
    compute_impact,
    first_public,
    merge_cohorts,
    with_relative_citations,
)


class TestFirstPublic:
    def test_arxiv_month_earlier_than_publication_date_wins(self):
        # MiniGPT-5: on arXiv in 2023, but S2 dates it to the 2026 proceedings.
        paper = {"external_ids": {"ArXiv": "2310.02239"}, "publication_date": "2026-10-15"}
        assert first_public(paper, 2026, 10) == date(2023, 10, 15)

    def test_publication_date_earlier_than_arxiv_month_wins(self):
        paper = {"external_ids": {"ArXiv": "2304.02643"}, "publication_date": "2023-04-05"}
        assert first_public(paper, 2023, 7) == date(2023, 4, 5)

    def test_versioned_arxiv_id(self):
        paper = {"external_ids": {"ArXiv": "2401.00001v3"}}
        assert first_public(paper, 2025, 5) == date(2024, 1, 15)

    def test_arxiv_month_from_datacite_doi(self):
        # MiniGPT-5's S2 record has no ArXiv id; arXiv's DataCite DOI still names it.
        paper = {"external_ids": {"DOI": "10.48550/arXiv.2310.02239"}}
        assert first_public(paper, 2026, 10) == date(2023, 10, 15)

    def test_arxiv_month_from_dblp_corr_key(self):
        paper = {"external_ids": {"DBLP": "journals/corr/abs-2310-02239"}}
        assert first_public(paper, 2026, 10) == date(2023, 10, 15)

    def test_publisher_doi_is_not_an_arxiv_id(self):
        paper = {"external_ids": {"DOI": "10.1109/ICRA.2023.10160001", "DBLP": "conf/icra/X23"}}
        assert first_public(paper, 2023, 7) == date(2023, 7, 15)

    def test_venue_date_when_nothing_else(self):
        assert first_public({}, 2025, 9) == date(2025, 9, 15)

    def test_venue_date_caps_a_late_publication_date(self):
        assert first_public({"publication_date": "2026-10-15"}, 2026, 2) == date(2026, 2, 15)

    @pytest.mark.parametrize("arxiv", ["cs/0701001", "", None, "2313.00001", "abcd.12345", 2304])
    def test_unusable_arxiv_ids_are_ignored(self, arxiv):
        paper = {"external_ids": {"ArXiv": arxiv}}
        assert first_public(paper, 2024, 5) == date(2024, 5, 15)

    @pytest.mark.parametrize(
        "pub", ["2023", "2023-04", "20230405", "2023-04-05T00:00", "not a date", "", None, "2023-02-30"]
    )
    def test_unparsable_publication_dates_are_ignored(self, pub):
        assert first_public({"publication_date": pub}, 2024, 5) == date(2024, 5, 15)


class TestCohortOf:
    def test_calendar_quarters(self):
        assert cohort_of(date(2024, 1, 1)) == (2024, 0)
        assert cohort_of(date(2024, 3, 31)) == (2024, 0)
        assert cohort_of(date(2024, 4, 1)) == (2024, 1)
        assert cohort_of(date(2024, 12, 31)) == (2024, 3)

    def test_old_years_are_ordinary_quarters(self):
        # No fixed old-papers bucket: the backfill fills these quarters.
        assert cohort_of(date(2015, 6, 1)) == (2015, 1)


class TestMergeCohorts:
    def test_quarter_of_exactly_min_size_stays_on_its_own(self):
        groups = merge_cohorts({(2024, 0): 5, (2024, 1): 5}, min_size=5)
        assert groups[(2024, 0)] != groups[(2024, 1)]

    def test_small_quarter_joins_the_one_before(self):
        groups = merge_cohorts({(2024, 0): 5, (2024, 1): 5, (2024, 2): 4}, min_size=5)
        assert groups[(2024, 2)] == groups[(2024, 1)]
        assert groups[(2024, 1)] != groups[(2024, 0)]

    def test_small_oldest_quarter_joins_the_one_after(self):
        groups = merge_cohorts({(2024, 0): 2, (2024, 1): 5}, min_size=5)
        assert groups[(2024, 0)] == groups[(2024, 1)]

    def test_run_of_sparse_old_quarters_becomes_one_cohort(self):
        counts = {(2017, 0): 2, (2019, 3): 1, (2021, 2): 3, (2022, 1): 9, (2022, 2): 9}
        groups = merge_cohorts(counts, min_size=5)
        assert groups[(2017, 0)] == groups[(2019, 3)] == groups[(2021, 2)]
        assert groups[(2021, 2)] != groups[(2022, 1)]
        assert groups[(2022, 1)] != groups[(2022, 2)]

    def test_sparse_run_still_too_small_joins_forward(self):
        counts = {(2024, 0): 2, (2024, 1): 2, (2024, 2): 5}
        groups = merge_cohorts(counts, min_size=5)
        assert groups[(2024, 0)] == groups[(2024, 1)] == groups[(2024, 2)]

    def test_lone_small_cohort_is_kept(self):
        assert merge_cohorts({(2024, 0): 1}, min_size=5) == {(2024, 0): 0}

    def test_empty(self):
        assert merge_cohorts({}, min_size=5) == {}


def _ratios(impacts, conf_id):
    return [None if i is None else i.relative_citations for i in impacts[conf_id]]


class TestComputeImpact:
    def test_ratio_to_cohort_mean(self):
        all_papers = {
            "iclr_2025": [
                {"title": "a", "citation_count": 10, "publication_date": "2025-01-10"},
                {"title": "b", "citation_count": 20, "publication_date": "2025-01-11"},
                {"title": "c", "citation_count": 30, "publication_date": "2025-01-12"},
            ]
        }
        impacts = compute_impact(all_papers, {"iclr": 1}, min_cohort=1)
        assert _ratios(impacts, "iclr_2025") == [0.5, 1.0, 1.5]
        assert impacts["iclr_2025"][0].first_public == date(2025, 1, 10)

    def test_cohorts_are_shared_across_conferences(self):
        all_papers = {
            "iclr_2025": [{"title": "a", "citation_count": 30, "publication_date": "2025-01-10"}],
            "cvpr_2025": [{"title": "b", "citation_count": 10, "publication_date": "2025-02-10"}],
        }
        impacts = compute_impact(all_papers, {"iclr": 1, "cvpr": 2}, min_cohort=1)
        assert _ratios(impacts, "iclr_2025") == [1.5]
        assert _ratios(impacts, "cvpr_2025") == [0.5]

    def test_separate_quarters_have_separate_means(self):
        all_papers = {
            "iclr_2025": [
                {"title": "a", "citation_count": 40, "publication_date": "2024-11-01"},
                {"title": "b", "citation_count": 10, "publication_date": "2025-01-10"},
            ]
        }
        impacts = compute_impact(all_papers, {"iclr": 1}, min_cohort=1)
        assert _ratios(impacts, "iclr_2025") == [1.0, 1.0]

    def test_uncited_papers_get_none_and_do_not_count_toward_cohort_size(self):
        # Q1 2025 has one cited paper plus one uncited. If the uncited one counted,
        # Q1 would reach min_cohort=2 and stand alone (ratio 1.0). It must not
        # count, so Q1 merges into Q4 2024: mean (40+40+10)/3 = 30, ratio 0.33.
        all_papers = {
            "iclr_2025": [
                {"title": "a", "citation_count": 40, "publication_date": "2024-11-01"},
                {"title": "b", "citation_count": 40, "publication_date": "2024-11-02"},
                {"title": "c", "citation_count": 10, "publication_date": "2025-01-10"},
                {"title": "d", "publication_date": "2025-01-10"},
            ]
        }
        impacts = compute_impact(all_papers, {"iclr": 1}, min_cohort=2)
        assert _ratios(impacts, "iclr_2025") == [1.33, 1.33, 0.33, None]

    def test_mean_is_floored_at_one_and_zero_citations_give_zero(self):
        all_papers = {
            "iclr_2026": [
                {"title": "a", "citation_count": 1, "publication_date": "2026-01-10"},
                {"title": "b", "citation_count": 0, "publication_date": "2026-01-10"},
            ]
        }
        impacts = compute_impact(all_papers, {"iclr": 1}, min_cohort=1)
        # mean 0.5 is floored to 1.0; without the floor "a" would be 2.0
        assert _ratios(impacts, "iclr_2026") == [1.0, 0.0]

    def test_rounds_to_two_decimals(self):
        all_papers = {
            "iclr_2025": [
                {"title": "a", "citation_count": 1, "publication_date": "2025-01-10"},
                {"title": "b", "citation_count": 2, "publication_date": "2025-01-10"},
            ]
        }
        impacts = compute_impact(all_papers, {"iclr": 1}, min_cohort=1)
        assert _ratios(impacts, "iclr_2025") == [0.67, 1.33]

    def test_unregistered_prefix_uses_june(self):
        all_papers = {"newconf_2025": [{"title": "a", "citation_count": 5}]}
        impacts = compute_impact(all_papers, {}, min_cohort=1)
        assert impacts["newconf_2025"][0].first_public == date(2025, 6, 15)

    @pytest.mark.parametrize("prefix", ["aaai", "wacv"])
    def test_venues_announcing_the_year_before_date_from_that_year(self, prefix):
        # AAAI 2026's accepted list went up in Nov 2025, not Dec 2026.
        all_papers = {f"{prefix}_2026": [{"title": "a", "citation_count": 5}]}
        impacts = compute_impact(all_papers, {prefix: 11}, min_cohort=1)
        assert impacts[f"{prefix}_2026"][0].first_public == date(2025, 11, 15)

    @pytest.mark.parametrize(
        "conf_id, expected",
        [
            ("coling_2024", date(2024, 3, 15)),  # LREC-COLING 2024 met in May
            ("coling_2025", date(2024, 11, 15)),  # COLING 2025 met in January
            ("coling_2022", date(2022, 11, 15)),  # an Aug-Dec year: the registry rule
        ],
    )
    def test_coling_dates_follow_each_years_calendar(self, conf_id, expected):
        all_papers = {conf_id: [{"title": "a", "citation_count": 5}]}
        impacts = compute_impact(all_papers, {"coling": 11}, min_cohort=1)
        assert impacts[conf_id][0].first_public == expected

    def test_multiword_prefix(self):
        all_papers = {"usenix_security_2024": [{"title": "a", "citation_count": 5}]}
        impacts = compute_impact(all_papers, {"usenix_security": 8}, min_cohort=1)
        assert impacts["usenix_security_2024"][0].first_public == date(2024, 8, 15)

    def test_conference_without_citations(self):
        all_papers = {
            "iclr_2025": [{"title": "a", "citation_count": 5}],
            "acl_2025": [{"title": "b"}, {"title": "c"}],
        }
        impacts = compute_impact(all_papers, {"iclr": 1, "acl": 5}, min_cohort=1)
        assert impacts["acl_2025"] == [None, None]
        assert _ratios(impacts, "iclr_2025") == [1.0]


class TestWithRelativeCitations:
    def test_adds_the_field_only_where_there_is_an_impact(self):
        papers = [{"title": "a", "citation_count": 0}, {"title": "b"}]
        impacts = [PaperImpact(date(2025, 1, 1), 0.0), None]
        out = with_relative_citations(papers, impacts)
        assert out[0]["relative_citations"] == 0.0
        assert "relative_citations" not in out[1]

    def test_does_not_mutate_its_input(self):
        papers = [{"title": "a", "citation_count": 3}]
        with_relative_citations(papers, [PaperImpact(date(2025, 1, 1), 1.0)])
        assert "relative_citations" not in papers[0]


def _parse(conf_id):
    prefix, year = conf_id.rsplit("_", 1)
    return prefix.upper(), int(year)


def _category(conf_id):
    return {"iclr": "ML", "cvpr": "CV", "acl": "NLP"}[conf_id.rsplit("_", 1)[0]]


def _imp(rel, when=date(2025, 1, 15)):
    return PaperImpact(when, rel)


def _top(all_papers, impacts, top_n=100, categories=("ML", "CV", "NLP")):
    return build_top(all_papers, impacts, _parse, _category, categories, top_n=top_n)


def _titles(top, ids):
    return [top["papers"][i]["title"] for i in ids]


class TestBuildTop:
    @pytest.fixture
    def two_confs(self):
        all_papers = {
            "iclr_2025": [{"title": "a", "citation_count": 5}],
            "cvpr_2024": [{"title": "b", "citation_count": 3}],
            "acl_2023": [{"title": "c"}],  # never enriched
        }
        impacts = {"iclr_2025": [_imp(2.0)], "cvpr_2024": [_imp(1.0)], "acl_2023": [None]}
        return all_papers, impacts

    def test_every_combination_is_present(self, two_confs):
        top = _top(*two_confs)
        assert top["categories"] == ["ML", "CV", "NLP"]
        assert top["years"] == ["2025", "2024", "2023"]
        assert list(top["lists"]) == ["all", "2025", "2024", "2023"]
        for period in top["lists"].values():
            assert list(period) == ["all", "ML", "CV", "NLP"]
            for cat in period.values():
                assert set(cat) == {"relative", "citations"}

    def test_filters_by_year_and_category(self, two_confs):
        top = _top(*two_confs)
        lists = top["lists"]
        assert _titles(top, lists["all"]["all"]["relative"]) == ["a", "b"]
        assert _titles(top, lists["2024"]["all"]["relative"]) == ["b"]
        assert _titles(top, lists["all"]["ML"]["citations"]) == ["a"]
        assert lists["2024"]["ML"]["relative"] == []
        # a year whose only conference has no citations: present, and empty
        assert lists["2023"]["all"]["relative"] == []
        assert lists["2023"]["NLP"]["citations"] == []

    def test_uncited_papers_are_left_out(self, two_confs):
        top = _top(*two_confs)
        assert "c" not in [p["title"] for p in top["papers"]]

    def test_relative_sort_ties_break_by_citations_then_title(self):
        all_papers = {
            "iclr_2025": [
                {"title": "b", "citation_count": 10},
                {"title": "a", "citation_count": 10},
                {"title": "c", "citation_count": 20},
                {"title": "d", "citation_count": 99},
            ]
        }
        impacts = {"iclr_2025": [_imp(2.0), _imp(2.0), _imp(2.0), _imp(1.0)]}
        top = _top(all_papers, impacts)
        assert _titles(top, top["lists"]["all"]["all"]["relative"]) == ["c", "a", "b", "d"]

    def test_citation_sort_ties_break_by_relative_then_title(self):
        all_papers = {
            "iclr_2025": [
                {"title": "x", "citation_count": 10},
                {"title": "y", "citation_count": 10},
                {"title": "w", "citation_count": 10},
                {"title": "z", "citation_count": 50},
            ]
        }
        impacts = {"iclr_2025": [_imp(1.0), _imp(3.0), _imp(3.0), _imp(0.5)]}
        top = _top(all_papers, impacts)
        assert _titles(top, top["lists"]["all"]["all"]["citations"]) == ["z", "w", "y", "x"]

    def test_lists_are_capped(self):
        all_papers = {
            "iclr_2025": [{"title": t, "citation_count": n} for t, n in [("a", 3), ("b", 2), ("c", 1)]]
        }
        impacts = {"iclr_2025": [_imp(3.0), _imp(2.0), _imp(1.0)]}
        top = _top(all_papers, impacts, top_n=2)
        assert _titles(top, top["lists"]["all"]["all"]["relative"]) == ["a", "b"]
        assert _titles(top, top["lists"]["2025"]["ML"]["citations"]) == ["a", "b"]

    def test_pool_holds_each_paper_once_and_indices_are_valid(self, two_confs):
        top = _top(*two_confs)
        assert len(top["papers"]) == 2
        for period in top["lists"].values():
            for cat in period.values():
                for ids in cat.values():
                    assert all(0 <= i < len(top["papers"]) for i in ids)

    def test_same_title_in_two_conferences_stays_two_papers(self):
        all_papers = {
            "iclr_2025": [{"title": "Same", "citation_count": 5}],
            "cvpr_2025": [{"title": "Same", "citation_count": 4}],
        }
        impacts = {"iclr_2025": [_imp(2.0)], "cvpr_2025": [_imp(1.0)]}
        top = _top(all_papers, impacts)
        ids = top["lists"]["all"]["all"]["relative"]
        assert [top["papers"][i]["conference_id"] for i in ids] == ["iclr_2025", "cvpr_2025"]

    def test_pool_entry_fields(self):
        paper = {
            "title": "a",
            "authors": ["X", "Y"],
            "selection": "oral",
            "citation_count": 5,
            "influential_citation_count": 0,
            "tldr": "short",
            "link": "https://example.com/a",
            "open_access_pdf": "https://example.com/a.pdf",
            "forum_id": "abc",
            "abstract": "long text",
            "keywords": ["k"],
            "publication_date": "2025-01-02",
            "external_ids": {"ArXiv": "2501.00001", "DOI": "10.1/x", "CorpusId": 7},
        }
        top = _top({"iclr_2025": [paper]}, {"iclr_2025": [_imp(2.5, date(2025, 1, 2))]})
        assert top["papers"][0] == {
            "title": "a",
            "authors": ["X", "Y"],
            "venue": "ICLR",
            "year": 2025,
            "conference_id": "iclr_2025",
            "selection": "oral",
            "citation_count": 5,
            "relative_citations": 2.5,
            "first_public": "2025-01-02",
            "influential_citation_count": 0,
            "tldr": "short",
            "link": "https://example.com/a",
            "open_access_pdf": "https://example.com/a.pdf",
            "forum_id": "abc",
            "external_ids": {"ArXiv": "2501.00001", "DOI": "10.1/x"},
        }

    def test_pool_entry_keeps_awards(self):
        awards = [{"label": "Best Paper", "kind": "award"}]
        top = _top(
            {"iclr_2025": [{"title": "a", "citation_count": 5, "awards": awards},
                           {"title": "b", "citation_count": 4}]},
            {"iclr_2025": [_imp(2.0), _imp(1.0)]},
        )
        by_title = {p["title"]: p for p in top["papers"]}
        assert by_title["a"]["awards"] == awards
        assert "awards" not in by_title["b"]

    def test_pool_entry_omits_absent_fields(self):
        top = _top({"iclr_2025": [{"title": "a", "citation_count": 5}]}, {"iclr_2025": [_imp(1.0)]})
        assert top["papers"][0] == {
            "title": "a",
            "authors": [],
            "venue": "ICLR",
            "year": 2025,
            "conference_id": "iclr_2025",
            "selection": "",
            "citation_count": 5,
            "relative_citations": 1.0,
            "first_public": "2025-01-15",
        }


def test_venue_date_replaces_the_announce_month():
    assert first_public({"venue_date": "2025-11-20"}, 2025, 1) == date(2025, 11, 20)


def test_venue_date_still_loses_to_an_earlier_arxiv_month():
    paper = {"venue_date": "2025-11-20", "external_ids": {"ArXiv": "2406.01234"}}
    assert first_public(paper, 2025, 1) == date(2024, 6, 15)


def test_a_malformed_venue_date_falls_back_to_the_announce_month():
    assert first_public({"venue_date": "2025-13-40"}, 2025, 1) == date(2025, 1, 15)
