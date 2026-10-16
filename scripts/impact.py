"""Age-adjusted citations and the cross-venue Top 100 lists for the web app.

A paper's `relative_citations` is its citation count divided by the mean
citation count of the papers in this dataset first made public in the same
calendar quarter. Raw counts favour old papers, and citations per year does
not fix that: citations accelerate over a paper's first years, so per year of
age a 2022 paper still out-earns a 2026 one by 3-4x. The value is relative to
the whole corpus -- adding a venue shifts every paper's -- so it is computed at
build time and never written to data/.
"""

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date
from itertools import islice
from typing import NamedTuple

# New-style arXiv ids (YYMM.NNNNN) carry the month the paper first went up.
ARXIV_ID = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}(v\d+)?$")
# Some S2 records carry the arXiv id only inside arXiv's DataCite DOI or the
# DBLP CoRR key.
ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(\d{2})(\d{2})\.\d{4,5}", re.IGNORECASE)
DBLP_CORR = re.compile(r"^journals/corr/abs-(\d{2})(\d{2})-\d{4,5}")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# For a prefix missing from configs/venues.yaml.
DEFAULT_ANNOUNCE_MONTH = 6
# Venues that meet early in the year and post their accepted list the autumn
# before (AAAI 2026 in Nov 2025, WACV 2026 in Oct 2025), so their announce_month
# belongs to year - 1. Measured on 2026-10-15: every AAAI and WACV year's arXiv
# preprints peak in Sep-Dec of the year before.
ANNOUNCED_YEAR_BEFORE = frozenset({"aaai", "wacv"})
# COLING moves around the calendar, so one announce_month cannot date it.
# LREC-COLING 2024 met in May (preprints peak 2024-03) and COLING 2025 in January
# (2024-09..12). Its Aug-Dec years (2016-2022) fit the registry rule as is.
CONFERENCE_MONTHS = {"coling_2024": (2024, 3), "coling_2025": (2024, 11)}
# A quarter with fewer cited papers than this joins the cohort before it: the
# quarter in progress, and the sparse quarters before the dataset's first year.
MIN_COHORT = 300
TOP_N = 100


class PaperImpact(NamedTuple):
    first_public: date
    relative_citations: float


def first_public(paper: dict, year: int, announce_month: int) -> date:
    """The earliest date the paper was public: arXiv month, S2 date or conference.

    Semantic Scholar's `publication_date` is sometimes the proceedings date of a
    paper that was on arXiv years earlier, and 11% of papers have none, so the
    arXiv id's month and the conference date bound it from both sides.
    """
    candidates = [date(year, announce_month, 15)]

    ids = paper.get("external_ids") or {}
    for key, pattern in (("ArXiv", ARXIV_ID), ("DOI", ARXIV_DOI), ("DBLP", DBLP_CORR)):
        value = ids.get(key)
        match = pattern.match(value) if isinstance(value, str) else None
        if match and 1 <= int(match.group(2)) <= 12:
            candidates.append(date(2000 + int(match.group(1)), int(match.group(2)), 15))

    published = paper.get("publication_date")
    if isinstance(published, str) and ISO_DATE.match(published):
        try:
            candidates.append(date.fromisoformat(published))
        except ValueError:
            pass

    return min(candidates)


def venue_year_month(conf_id: str, announce_months: dict[str, int]) -> tuple[int, int]:
    """The (year, month) a conference's accepted list went public."""
    if conf_id in CONFERENCE_MONTHS:
        return CONFERENCE_MONTHS[conf_id]
    prefix, conf_year = conf_id.rsplit("_", 1)
    year = int(conf_year) - 1 if prefix in ANNOUNCED_YEAR_BEFORE else int(conf_year)
    return year, announce_months.get(prefix, DEFAULT_ANNOUNCE_MONTH)


def cohort_of(d: date) -> tuple[int, int]:
    """The calendar quarter of a date, as (year, 0-3)."""
    return (d.year, (d.month - 1) // 3)


def merge_cohorts(
    counts: dict[tuple[int, int], int], min_size: int
) -> dict[tuple[int, int], int]:
    """Map each quarter to a group id, folding small quarters into the one before.

    Quarters are walked oldest first. One under `min_size` joins the group before
    it; if the oldest group is still under `min_size` at the end, it joins the
    next group.
    """
    groups: list[list[tuple[int, int]]] = []
    for key in sorted(counts):
        if groups and counts[key] < min_size:
            groups[-1].append(key)
        else:
            groups.append([key])

    if len(groups) > 1 and sum(counts[k] for k in groups[0]) < min_size:
        groups[1] = groups[0] + groups[1]
        del groups[0]

    return {key: gid for gid, group in enumerate(groups) for key in group}


def compute_impact(
    all_papers: dict[str, list[dict]],
    announce_months: dict[str, int],
    min_cohort: int = MIN_COHORT,
) -> dict[str, list[PaperImpact | None]]:
    """Each paper's first-public date and relative citations, per conference.

    The lists are positionally aligned with `all_papers`; a paper without a
    `citation_count` gets None and does not count toward any cohort.
    """
    dated: dict[str, list[tuple[date, int] | None]] = {}
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for conf_id, papers in all_papers.items():
        year, month = venue_year_month(conf_id, announce_months)
        rows: list[tuple[date, int] | None] = []
        for paper in papers:
            cites = paper.get("citation_count")
            if cites is None:
                rows.append(None)
                continue
            when = first_public(paper, year, month)
            counts[cohort_of(when)] += 1
            rows.append((when, cites))
        dated[conf_id] = rows

    group_of = merge_cohorts(counts, min_cohort)
    totals: dict[int, int] = defaultdict(int)
    sizes: dict[int, int] = defaultdict(int)
    for rows in dated.values():
        for row in rows:
            if row is not None:
                group = group_of[cohort_of(row[0])]
                totals[group] += row[1]
                sizes[group] += 1
    means = {group: max(totals[group] / sizes[group], 1.0) for group in sizes}

    return {
        conf_id: [
            None
            if row is None
            else PaperImpact(row[0], round(row[1] / means[group_of[cohort_of(row[0])]], 2))
            for row in rows
        ]
        for conf_id, rows in dated.items()
    }


def with_relative_citations(
    papers: list[dict], impacts: list[PaperImpact | None]
) -> list[dict]:
    """Copies of `papers` carrying `relative_citations` where there is one."""
    return [
        paper if impact is None else {**paper, "relative_citations": impact.relative_citations}
        for paper, impact in zip(papers, impacts)
    ]


SORTS = ("relative", "citations")
# Pool entries keep what a paper row renders; abstracts would make top.json
# several megabytes for text nobody reads in a ranking.
OPTIONAL_FIELDS = ("influential_citation_count", "tldr", "link", "open_access_pdf", "forum_id", "awards")
POOL_EXTERNAL_IDS = ("ArXiv", "DOI")


class _Candidate(NamedTuple):
    conf_id: str
    index: int
    venue: str
    year: int
    category: str
    paper: dict
    impact: PaperImpact


def _by_relative(c: _Candidate) -> tuple:
    return (-c.impact.relative_citations, -c.paper["citation_count"], c.paper["title"])


def _by_citations(c: _Candidate) -> tuple:
    return (-c.paper["citation_count"], -c.impact.relative_citations, c.paper["title"])


def _pool_entry(c: _Candidate) -> dict:
    paper = c.paper
    entry = {
        "title": paper["title"],
        "authors": paper.get("authors", []),
        "venue": c.venue,
        "year": c.year,
        "conference_id": c.conf_id,
        "selection": paper.get("selection", ""),
        "citation_count": paper["citation_count"],
        "relative_citations": c.impact.relative_citations,
        "first_public": c.impact.first_public.isoformat(),
    }
    for key in OPTIONAL_FIELDS:
        if paper.get(key) not in (None, ""):
            entry[key] = paper[key]
    ids = {
        key: value
        for key, value in (paper.get("external_ids") or {}).items()
        if key in POOL_EXTERNAL_IDS and value
    }
    if ids:
        entry["external_ids"] = ids
    return entry


def build_top(
    all_papers: dict[str, list[dict]],
    impacts: dict[str, list[PaperImpact | None]],
    parse_conference_id: Callable[[str], tuple[str, int]],
    category_of: Callable[[str], str],
    categories: Sequence[str],
    top_n: int = TOP_N,
) -> dict:
    """The Top 100 lists for every (period, category, sort), as indices into one pool.

    The pool is keyed by (conference, position), never by title: two different
    papers may share a title.
    """
    candidates: list[_Candidate] = []
    years: set[int] = set()
    for conf_id, papers in all_papers.items():
        venue, year = parse_conference_id(conf_id)
        years.add(year)
        category = category_of(conf_id)
        for index, (paper, impact) in enumerate(zip(papers, impacts[conf_id])):
            if impact is not None:
                candidates.append(_Candidate(conf_id, index, venue, year, category, paper, impact))

    ordered = {
        "relative": sorted(candidates, key=_by_relative),
        "citations": sorted(candidates, key=_by_citations),
    }
    pool: list[dict] = []
    pool_index: dict[tuple[str, int], int] = {}

    def ref(c: _Candidate) -> int:
        key = (c.conf_id, c.index)
        if key not in pool_index:
            pool_index[key] = len(pool)
            pool.append(_pool_entry(c))
        return pool_index[key]

    year_keys = [str(y) for y in sorted(years, reverse=True)]
    lists: dict[str, dict[str, dict[str, list[int]]]] = {}
    for period in ["all", *year_keys]:
        lists[period] = {}
        for cat in ["all", *categories]:
            lists[period][cat] = {}
            for sort in SORTS:
                picked = islice(
                    (
                        c
                        for c in ordered[sort]
                        if (period == "all" or str(c.year) == period)
                        and (cat == "all" or c.category == cat)
                    ),
                    top_n,
                )
                lists[period][cat][sort] = [ref(c) for c in picked]

    return {"categories": list(categories), "years": year_keys, "papers": pool, "lists": lists}
