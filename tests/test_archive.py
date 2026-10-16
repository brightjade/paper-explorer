from datetime import date

from ppr.archive import (
    EnrichPlan,
    cohort,
    conference_year,
    first_live_year,
    is_archive,
    is_due,
    plan_enrich,
)

NOV_2026 = date(2026, 11, 3)


class TestArchiveYears:
    def test_first_live_year_is_three_years_back(self):
        assert first_live_year(2026) == 2023

    def test_boundary(self):
        assert is_archive("cvpr_2022", NOV_2026)
        assert not is_archive("cvpr_2023", NOV_2026)

    def test_the_window_moves_with_the_run_year(self):
        assert is_archive("cvpr_2023", date(2027, 1, 3))

    def test_ids_without_a_year_are_never_archive(self):
        assert conference_year("venues") is None
        assert not is_archive("venues", NOV_2026)


class TestCohorts:
    def test_cohorts_are_crc32_not_salted_hash(self):
        # Literal values: Python's hash() is salted per process, crc32 is not.
        assert cohort("iclr_2015") == 0
        assert cohort("neurips_2017") == 1
        assert cohort("cvpr_2019") == 2

    def test_every_cohort_is_due_once_in_any_three_months(self):
        ids = ["iclr_2015", "neurips_2017", "cvpr_2019"]
        for month in range(1, 11):
            due = [c for m in (month, month + 1, month + 2)
                   for c in ids if is_due(c, date(2026, m, 3))]
            assert sorted(due) == sorted(ids)


class TestPlanEnrich:
    IDS = ["icml_2026", "cvpr_2019", "neurips_2017", "iclr_2015"]

    def test_no_date_means_no_archive_rule(self):
        assert plan_enrich(self.IDS, None) == EnrichPlan(due=[], live=self.IDS, not_due=[])

    def test_splits_by_cohort(self):
        # November: 11 % 3 == 2, so cohort 2 (cvpr_2019) is due.
        plan = plan_enrich(self.IDS, NOV_2026)
        assert plan.due == ["cvpr_2019"]
        assert plan.live == ["icml_2026"]
        assert sorted(plan.not_due) == ["iclr_2015", "neurips_2017"]

    def test_exempt_archive_ids_get_a_full_enrich(self):
        plan = plan_enrich(self.IDS, NOV_2026, exempt=frozenset({"neurips_2017"}))
        assert "neurips_2017" in plan.live
        assert "neurips_2017" not in plan.not_due
