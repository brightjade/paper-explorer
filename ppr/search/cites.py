"""`ppr search cites`: follow seed papers' references and citations through Semantic Scholar.

A paper linked to several seeds is likely on topic. One in the dataset comes back
as a paper line; one outside it with what Semantic Scholar knows, under the id
`s2:<CorpusId>` that `lookup` and `--exclude` also accept.
"""

import asyncio
from dataclasses import dataclass, field

import httpx

from ppr.matching import title_key
from ppr.s2_client import S2Client
from ppr.search.find import SNIPPET_CHARS, format_line, row_dict
from ppr.search.lookup import classify, lookup

LINK_FIELDS = ("corpusId", "title", "year", "venue", "externalIds", "citationCount")
DIRECTIONS = {"refs": ("references",), "citing": ("citations",), "both": ("references", "citations")}
DETAIL_FIELDS = "corpusId,tldr,abstract"


class S2Unavailable(Exception):
    """Semantic Scholar answered for no seed: unreachable, or none of them is indexed."""


@dataclass
class Linked:
    corpus_id: int
    title: str
    year: int | None
    venue: str
    external_ids: dict
    citation_count: int
    links: int = 0
    rows: list = field(default_factory=list)  # the dataset's papers with this CorpusId; empty when outside
    snippet: str = ""

    @property
    def outside_id(self) -> str:
        return f"s2:{self.corpus_id}"


@dataclass
class CitesReport:
    seeds: int
    answered: int
    skipped: list[str]
    direction: str
    min_links: int
    inside: list[Linked]
    outside: list[Linked]
    inside_total: int
    outside_total: int


def batch_fields(direction: str) -> str:
    return ",".join(["corpusId"] + [f"{d}.{f}" for d in DIRECTIONS[direction] for f in LINK_FIELDS])


def _row_s2_id(row) -> str | None:
    if row["corpus_id"]:
        return f"CorpusId:{row['corpus_id']}"
    if row["arxiv"]:
        return f"ARXIV:{row['arxiv']}"
    if row["doi"]:
        return f"DOI:{row['doi']}"
    return None


def resolve_seeds(con, seeds: list[str]) -> tuple[list[str], list[str]]:
    """(Semantic Scholar ids to ask for, once each in seed order, seeds that resolve to none)."""
    ids, skipped = [], []
    prefixes = {"corpus": "CorpusId:", "arxiv": "ARXIV:", "doi": "DOI:"}
    for raw in seeds:
        item = classify(raw)
        if item.kind in prefixes:
            s2_id = prefixes[item.kind] + item.value
        else:
            s2_id = next((s for row in lookup(con, raw).rows if (s := _row_s2_id(row))), None)
        if not s2_id:
            skipped.append(raw)
        elif s2_id not in ids:
            ids.append(s2_id)
    return ids, skipped


def _corpus_id(value) -> int | None:
    """A Semantic Scholar corpusId as an int; S2 sometimes sends it as a string of digits. Anything else is missing."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def aggregate(entries: list[dict | None], direction: str) -> dict[int, Linked]:
    """Every paper linked to a seed, with how many seeds link to it; the seeds themselves left out."""
    seeds = {_corpus_id(e.get("corpusId")) for e in entries if e}
    linked: dict[int, Linked] = {}
    answered: set[int | None] = set()  # two ids (a pid's CorpusId, an arXiv id) can answer as one paper
    for entry in entries:
        seed = _corpus_id(entry.get("corpusId")) if entry else None
        if not entry or seed in answered:
            continue
        answered.add(seed)
        seen: set[int] = set()
        for key in DIRECTIONS[direction]:
            for link in entry.get(key) or []:
                cid = _corpus_id((link or {}).get("corpusId"))
                if cid is None or cid in seen or cid in seeds:
                    continue
                seen.add(cid)
                if cid not in linked:
                    linked[cid] = Linked(cid, link.get("title") or "", link.get("year"), link.get("venue") or "",
                                         link.get("externalIds") or {}, int(link.get("citationCount") or 0))
                linked[cid].links += 1
    return linked


def _attach_rows(con, linked: dict[int, Linked]) -> None:
    ids = list(linked)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for row in con.execute(f"SELECT * FROM papers WHERE corpus_id IN ({', '.join('?' * len(chunk))}) "
                               "ORDER BY year, conf_id", chunk):
            linked[row["corpus_id"]].rows.append(row)
    # A paper the dataset holds under another (or no) CorpusId is still inside: match its title.
    for x in linked.values():
        if not x.rows and (key := title_key(x.title)):
            x.rows.extend(con.execute("SELECT * FROM papers WHERE title_key = ? ORDER BY year, conf_id", (key,)))


async def _batch(client: S2Client, ids: list[str], fields: str) -> list[dict | None]:
    async with httpx.AsyncClient(timeout=120) as http:
        return await client.get_batch(http, ids, fields=fields)


def _snippet(entry: dict) -> str:
    tldr = entry.get("tldr")
    text = (tldr.get("text") if isinstance(tldr, dict) else tldr) or entry.get("abstract") or ""
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rstrip() + "…"


def chase(con, client: S2Client, seeds: list[str], direction: str = "both", min_links: int = 2,
          limit: int = 50, exclude: frozenset[str] = frozenset(), abstracts: bool = False) -> CitesReport:
    ids, skipped = resolve_seeds(con, seeds)
    if not ids:
        return CitesReport(0, 0, skipped, direction, min_links, [], [], 0, 0)
    entries = asyncio.run(_batch(client, ids, batch_fields(direction)))
    answered = sum(1 for e in entries if e)
    if not answered:
        raise S2Unavailable("Semantic Scholar returned nothing for any seed (unreachable, or none is indexed)")
    linked = aggregate(entries, direction)
    _attach_rows(con, linked)
    inside = [x for x in linked.values() if x.rows and not any(r["pid"] in exclude for r in x.rows)]
    outside = [x for x in linked.values()
               if not x.rows and x.links >= min_links and x.outside_id not in exclude]
    inside.sort(key=lambda x: (-x.links, -x.rows[0]["citation_count"]))
    outside.sort(key=lambda x: (-x.links, -x.citation_count))
    report = CitesReport(len(ids), answered, skipped, direction, min_links,
                         inside[:limit], outside[:limit], len(inside), len(outside))
    if abstracts and report.outside:
        details = asyncio.run(_batch(client, [f"CorpusId:{x.corpus_id}" for x in report.outside], DETAIL_FIELDS))
        for x, entry in zip(report.outside, details):
            if entry:
                x.snippet = _snippet(entry)
    return report


def _outside_ref(x: Linked) -> str:
    if x.external_ids.get("ArXiv"):
        return f"arXiv:{x.external_ids['ArXiv']}"
    if x.external_ids.get("DOI"):
        return f"doi:{x.external_ids['DOI']}"
    return "-"


def format_report(r: CitesReport) -> str:
    head = f"cites · {r.seeds} seeds ({r.answered} answered) · {r.direction}"
    if r.skipped:
        head += f" · skipped (no id): {'; '.join(r.skipped)}"
    lines = [head, f"in dataset ({r.inside_total}, showing {len(r.inside)})"]
    for x in r.inside:
        lines.extend(f"  {x.links} links | {format_line(row)}" for row in x.rows)
    lines.append(f"outside ({r.outside_total} with ≥{r.min_links} links, showing {len(r.outside)})")
    for x in r.outside:
        lines.append(f"  {x.links} links | {x.outside_id} | {x.year or '?'} | {x.venue or '-'} | "
                     f"{_outside_ref(x)} | {x.citation_count} cites | {x.title}")
        if x.snippet:
            lines.append(f"      {x.snippet}")
    return "\n".join(lines)


def report_records(r: CitesReport) -> list[dict]:
    """One JSON record per linked paper, dataset papers first: the shape the skill's judges read."""
    records = [{"group": "dataset", "links": x.links, **row_dict(row)} for x in r.inside for row in x.rows]
    records.extend({"group": "outside", "links": x.links, "id": x.outside_id, "corpus_id": x.corpus_id,
                    "title": x.title, "year": x.year, "venue": x.venue, "external_ids": x.external_ids,
                    "citation_count": x.citation_count, "snippet": x.snippet} for x in r.outside)
    return records
