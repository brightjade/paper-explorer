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
from datetime import date
from typing import NamedTuple

# New-style arXiv ids (YYMM.NNNNN) carry the month the paper first went up.
ARXIV_ID = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}(v\d+)?$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# For a prefix missing from configs/venues.yaml.
DEFAULT_ANNOUNCE_MONTH = 6
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

    arxiv = (paper.get("external_ids") or {}).get("ArXiv")
    match = ARXIV_ID.match(arxiv) if isinstance(arxiv, str) else None
    if match and 1 <= int(match.group(2)) <= 12:
        candidates.append(date(2000 + int(match.group(1)), int(match.group(2)), 15))

    published = paper.get("publication_date")
    if isinstance(published, str) and ISO_DATE.match(published):
        try:
            candidates.append(date.fromisoformat(published))
        except ValueError:
            pass

    return min(candidates)


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
        prefix, year = conf_id.rsplit("_", 1)
        month = announce_months.get(prefix, DEFAULT_ANNOUNCE_MONTH)
        rows: list[tuple[date, int] | None] = []
        for paper in papers:
            cites = paper.get("citation_count")
            if cites is None:
                rows.append(None)
                continue
            when = first_public(paper, int(year), month)
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
