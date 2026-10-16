"""Archive years: conference-years Semantic Scholar finished indexing long ago.

The monthly run re-attempts unmatched papers because S2 indexes a venue months
after we crawl it. Once a conference is ARCHIVE_AGE years old that reason is
gone, so the monthly run refreshes archive conferences by batch only, one
cohort a month, and discovery stops probing their years.
"""

import zlib
from dataclasses import dataclass, field
from datetime import date

ARCHIVE_AGE = 4
COHORTS = 3


def conference_year(conf_id: str) -> int | None:
    tail = conf_id.rpartition("_")[2]
    return int(tail) if tail.isdigit() else None


def first_live_year(today_year: int) -> int:
    """The oldest conference year that is not archive in `today_year`."""
    return today_year - ARCHIVE_AGE + 1


def is_archive(conf_id: str, today: date) -> bool:
    year = conference_year(conf_id)
    return year is not None and year < first_live_year(today.year)


def cohort(conf_id: str) -> int:
    """Stable across runs and machines: crc32, never Python's salted hash()."""
    return zlib.crc32(conf_id.encode("utf-8")) % COHORTS


def is_due(conf_id: str, today: date) -> bool:
    return cohort(conf_id) == today.month % COHORTS


@dataclass
class EnrichPlan:
    due: list[str] = field(default_factory=list)  # archive, refreshed batch-only this run
    live: list[str] = field(default_factory=list)  # full enrich
    not_due: list[str] = field(default_factory=list)  # archive, left untouched this run


def plan_enrich(
    conf_ids: list[str], today: date | None, exempt: frozenset[str] = frozenset()
) -> EnrichPlan:
    """Split one run's conferences.

    `today=None` means no archive rule at all: the caller named its
    conferences, and named conferences get a full enrich. `exempt` names
    conferences the run must finish (a re-crawl's `--require`), which get one
    too, archive or not.
    """
    plan = EnrichPlan()
    for conf_id in conf_ids:
        if today is None or conf_id in exempt or not is_archive(conf_id, today):
            plan.live.append(conf_id)
        elif is_due(conf_id, today):
            plan.due.append(conf_id)
        else:
            plan.not_due.append(conf_id)
    return plan
