"""Reading and writing data/<venue>/<year>.jsonl, a conference-year's one paper file.

Two steps write it and each owns its fields. The crawl owns which papers are
listed and what they say (title, authors, link, selection, keywords,
forum_id, venue_date, and the abstract when its source has one). Enrich owns
what Semantic Scholar adds, plus an abstract it filled in, which carries
`abstract_source: "s2"`. `save_crawl` keeps enrich's fields across a re-crawl;
`crawl_view` takes them off again.
"""

import json
import os
from pathlib import Path

from ppr.models import Paper

# A crawl that returns fewer than this fraction of the papers on disk is
# treated as a broken source (an API error swallowed into a short list, a
# selector a redesign outgrew), not as the venue shrinking.
MIN_KEEP_RATIO = 0.5

# A run that would leave less than this fraction of the previously matched
# papers carrying a Semantic Scholar ID is treated as a failed lookup rather
# than as real data.
MIN_COVERAGE_RATIO = 0.5


def enrichment_coverage(papers: list[Paper]) -> int:
    """How many papers carry a Semantic Scholar corpus ID."""
    return sum(1 for p in papers if (p.external_ids or {}).get("CorpusId"))


def check_enrichment_coverage(
    papers: list[Paper], enriched: list[Paper]
) -> str | None:
    """Decide whether the about-to-be-written papers are worth keeping.

    The paper-count check bounds how many *papers* a write may lose; this bounds
    how much *enrichment* it may lose, which the paper count cannot see. An API that
    answers nothing — or a title change that routes every paper cold and finds
    no match — writes the same papers back with citations, tldrs and external
    IDs blank. Losing the corpus IDs also costs every future run the fast
    refresh path, so the damage compounds.

    Returns a human-readable reason to skip, or None to proceed. Coverage is
    only ever compared against existing enrichment, so a conference being
    enriched for the first time is never blocked.
    """
    prior = enrichment_coverage(enriched)
    if not prior:
        return None
    current = enrichment_coverage(papers)
    if current < MIN_COVERAGE_RATIO * prior:
        return (
            f"only {current} of {len(papers)} papers would keep a Semantic "
            f"Scholar ID, under {MIN_COVERAGE_RATIO:.0%} of the {prior} matched "
            f"before — refusing to overwrite. The lookups likely failed; retry."
        )
    return None


class ShrinkError(Exception):
    """A crawl would have replaced a conference's papers with under half as many,
    or left under half of its matched papers enriched."""


def normalize_title(title: str) -> str:
    """Lowercase and collapse whitespace, for cross-source title comparison."""
    return " ".join(title.lower().split())


def read_papers(path: Path) -> list[Paper]:
    """Read a JSONL paper file. A missing or empty file reads as no papers."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [Paper.from_dict(json.loads(line)) for line in f if line.strip()]


def carry_over(raw: Paper, prior: Paper) -> Paper:
    """Copy prior enrichment onto a freshly-crawled paper, in place.

    The crawl is authoritative for identity (title, authors, link, selection,
    keywords, forum_id, venue_date); the file on disk holds the only copy of
    previous enrichment. Carrying it over means a paper whose refresh lookup
    comes back empty keeps its old values instead of silently losing them. An
    abstract the crawl did not supply is kept with its `abstract_source`, so it
    can still be told apart from one the crawl did.
    """
    raw.citation_count = prior.citation_count
    raw.influential_citation_count = prior.influential_citation_count
    raw.reference_count = prior.reference_count
    raw.tldr = prior.tldr
    raw.publication_date = prior.publication_date
    raw.fields_of_study = prior.fields_of_study
    raw.open_access_pdf = prior.open_access_pdf
    raw.external_ids = prior.external_ids
    raw.match_status = prior.match_status
    if not raw.abstract and prior.abstract:
        raw.abstract = prior.abstract
        raw.abstract_source = prior.abstract_source
    return raw


def crawl_view(paper: Paper) -> Paper:
    """Take off everything enrich contributed, in place, leaving what the crawl gave."""
    paper.citation_count = None
    paper.influential_citation_count = None
    paper.reference_count = None
    paper.tldr = ""
    paper.publication_date = ""
    paper.fields_of_study = []
    paper.open_access_pdf = ""
    paper.external_ids = {}
    paper.match_status = ""
    if paper.abstract_source == "s2":
        paper.abstract = ""
    paper.abstract_source = ""
    return paper


def _write_sorted(papers: list[Paper], path: Path) -> None:
    """Sort by citation count descending and replace `path` atomically.

    Writing to a temp file and renaming means an interrupted or failing run
    leaves the previous file untouched.
    """
    ordered = sorted(
        papers,
        key=lambda p: p.citation_count if p.citation_count is not None else -1,
        reverse=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for paper in ordered:
                f.write(paper.to_json() + "\n")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_crawl(papers: list[Paper], path: Path) -> Path:
    """Write a crawl over `path`, keeping each paper's enrichment from the file.

    Every source can fail into a short list rather than an exception -- an
    OpenReview error swallowed into `[]`, or a scraper whose selector a site
    redesign outgrew -- so a crawl under half of what is on disk is refused and
    the file left alone. The crawl decides which papers are listed: one it no
    longer returns is dropped, a new one arrives unenriched. A crawl that would
    leave under half of the matched papers enriched is refused too: titles are
    how enrichment is carried over, so a source that garbled them would
    otherwise wipe every citation without changing the paper count.
    """
    existing = read_papers(path)
    if existing and len(papers) < MIN_KEEP_RATIO * len(existing):
        raise ShrinkError(
            f"{path}: this crawl returned {len(papers)} papers, under "
            f"{MIN_KEEP_RATIO:.0%} of the {len(existing)} on disk -- refusing to "
            f"overwrite. The source likely broke; fix it and re-crawl. If the venue "
            f"really shrank, delete {path} and re-crawl."
        )
    prior = {normalize_title(p.title): p for p in existing}
    for paper in papers:
        old = prior.get(normalize_title(paper.title))
        if old is not None:
            carry_over(paper, old)
    kept, before = enrichment_coverage(papers), enrichment_coverage(existing)
    if kept < MIN_COVERAGE_RATIO * before:
        raise ShrinkError(
            f"{path}: only {kept} of this crawl's papers would keep a Semantic Scholar ID, "
            f"under {MIN_COVERAGE_RATIO:.0%} of the {before} on disk -- refusing to overwrite. "
            f"A paper keeps its enrichment only when its title still matches; if the source "
            f"really renamed them, delete {path} and re-crawl."
        )
    _write_sorted(papers, path)
    return path


def save_enriched(papers: list[Paper], path: Path) -> None:
    """Replace `path` with an enrich run's result."""
    _write_sorted(papers, path)
