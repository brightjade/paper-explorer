from datetime import date

import pytest

from scripts.impact import (
    PaperImpact,
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
