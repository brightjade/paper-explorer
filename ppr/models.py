from dataclasses import asdict, dataclass, field
from pathlib import Path
import json


class EmptyOverwriteError(Exception):
    """A zero-paper write would have erased an existing non-empty papers.jsonl."""


@dataclass
class Paper:
    title: str
    link: str
    authors: list[str]
    selection: str = ""
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""
    citation_count: int | None = None
    forum_id: str = ""
    influential_citation_count: int | None = None
    reference_count: int | None = None
    tldr: str = ""
    publication_date: str = ""
    venue_date: str = ""  # the paper's own date at the venue (YYYY-MM-DD); crawl-owned, enrich never writes it
    fields_of_study: list[str] = field(default_factory=list)
    open_access_pdf: str = ""
    external_ids: dict = field(default_factory=dict)
    match_status: str = ""
    abstract_source: str = ""  # "s2" when Semantic Scholar filled `abstract`; empty means the crawl supplied it

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != "" and v != [] and v != {}}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Paper":
        return cls(
            title=data["title"],
            link=data.get("link", ""),
            authors=data.get("authors", []),
            keywords=data.get("keywords", []),
            abstract=data.get("abstract", ""),
            selection=data.get("selection", ""),
            citation_count=data.get("citation_count"),
            forum_id=data.get("forum_id", ""),
            influential_citation_count=data.get("influential_citation_count"),
            reference_count=data.get("reference_count"),
            tldr=data.get("tldr", ""),
            publication_date=data.get("publication_date", ""),
            venue_date=data.get("venue_date", ""),
            fields_of_study=data.get("fields_of_study", []),
            open_access_pdf=data.get("open_access_pdf", ""),
            external_ids=data.get("external_ids", {}),
            match_status=data.get("match_status", ""),
            abstract_source=data.get("abstract_source", ""),
        )


def _existing_paper_count(path: Path) -> int:
    """Papers already on disk at `path`; 0 if it is absent or blank.

    Counts non-blank lines the way `ppr/validate.py` does, so a file holding
    only a stray newline is treated as the empty file it effectively is.
    """
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def write_papers(papers: list[Paper], path: Path) -> Path:
    """Write `papers` to `path` as JSONL, refusing to erase an existing crawl.

    Every source can fail into an empty list rather than an exception: an
    OpenReview error swallowed into `[]`, or a scraper whose selector a site
    redesign outgrew. A plain `open(path, "w")` then truncates a good crawl to
    zero bytes while the caller logs "Saved 0 papers" and exits 0 -- the CoRL
    2024 failure reached through the save path instead of the filter.

    `ppr/enrich.py`'s `check_guards` already refuses exactly this for
    `papers_enriched.jsonl`. The same rule has to hold for the file it reads
    from, or the two modules disagree about one rule.

    Writing zero papers to a conference that has none yet is fine; it is
    overwriting real data with nothing that must not happen silently.
    """
    existing = _existing_paper_count(path)
    if not papers and existing:
        raise EmptyOverwriteError(
            f"{path} holds {existing} papers and this crawl produced 0 — "
            f"refusing to overwrite. The source likely broke (an API error, or "
            f"a selector the site outgrew); fix it and re-crawl."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for paper in papers:
            f.write(paper.to_json() + "\n")
    return path
