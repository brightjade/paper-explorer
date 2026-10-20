"""`ppr search find`: ranked keyword search over the index.

The tool's job is recall within a page; judging relevance is the caller's (the
/survey skill's), so ranking stays plain BM25, with a citation or year sort on
request.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# bm25 column weights, in the fts table's column order: title, abstract, tldr, keywords
WEIGHTS = (10.0, 1.0, 3.0, 2.0)
SNIPPET_CHARS = 400
SORTS = ("relevance", "citations", "year")

_BM25 = "bm25(fts, " + ", ".join(str(w) for w in WEIGHTS) + ")"
# bm25 normalizes by the whole row's length, so a title-only paper (no abstract, no tldr)
# would outrank papers matching in title and abstract: relevance puts those after.
_ORDER = {
    "relevance": f"(p.abstract = '' AND p.tldr = ''), {_BM25}, p.id",
    "citations": f"p.citation_count DESC, {_BM25}, p.id",
    "year": "p.year DESC, p.citation_count DESC, p.id",
}
_YEARS = re.compile(r"(\d{4})(?:-(\d{4}))?")


class QueryError(Exception):
    """A search the index cannot run: no terms, a bad --years, malformed --raw FTS5."""


@dataclass(frozen=True)
class Filters:
    venues: tuple[str, ...] = ()
    years: tuple[int, int] | None = None
    selections: tuple[str, ...] = ()
    awarded: bool = False


def phrase(term: str) -> str:
    """One FTS5 phrase. Quoting keeps `vision-language`, `GPT-4` or `NOT` plain text;
    a trailing `*` makes it a prefix."""
    text = term.strip()
    prefix = text.endswith("*")
    if prefix:
        text = text[:-1].rstrip()
    if not text:
        raise QueryError(f"empty search term {term!r}")
    return '"' + text.replace('"', '""') + '"' + ("*" if prefix else "")


def build_match(terms, must=(), raw: str | None = None) -> str:
    """TERMs ORed, each --must ANDed on; --raw replaces both."""
    if raw is not None:
        if not raw.strip():
            raise QueryError("empty --raw expression")
        return raw
    if not terms and not must:
        raise QueryError("give at least one search term")
    parts = []
    if terms:
        parts.append("(" + " OR ".join(phrase(t) for t in terms) + ")")
    parts.extend(phrase(t) for t in must)
    return " AND ".join(parts)


def parse_years(text: str) -> tuple[int, int]:
    m = _YEARS.fullmatch(text.strip())
    if not m:
        raise QueryError(f"--years takes YYYY or YYYY-YYYY, not {text!r}")
    lo, hi = int(m[1]), int(m[2] or m[1])
    if lo > hi:
        raise QueryError(f"--years {text!r} runs backwards")
    return lo, hi


def split_list(text: str | None) -> tuple[str, ...]:
    return tuple(v.strip().lower() for v in (text or "").split(",") if v.strip())


def read_exclude(path: Path | None) -> frozenset[str]:
    """Ids in the first tab-separated column of `path` (the skill's judged.tsv); none while it does not exist."""
    if path is None or not path.exists():
        return frozenset()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        first = line.split("\t", 1)[0].strip()
        if first and not first.startswith("#") and first != "pid":
            ids.add(first)
    return frozenset(ids)


def fetch_rows(con: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    """`papers` rows by id, in the order given."""
    by_id = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for row in con.execute(f"SELECT * FROM papers WHERE id IN ({', '.join('?' * len(chunk))})", chunk):
            by_id[row["id"]] = row
    return [by_id[i] for i in ids]


def _check_known(con: sqlite3.Connection, column: str, values: tuple[str, ...], flag: str) -> None:
    """A value no paper has would silently match nothing; name it and list the ones that exist."""
    if not values:
        return
    known = sorted(row[0] for row in con.execute(f"SELECT DISTINCT {column} FROM papers") if row[0])
    for value in values:
        if value not in known:
            raise QueryError(f"unknown {flag} value {value!r}; known: {', '.join(known)}")


def search(con: sqlite3.Connection, match: str, filters: Filters = Filters(),
           exclude: frozenset[str] = frozenset(), sort: str = "relevance",
           limit: int = 50, offset: int = 0) -> tuple[int, list[sqlite3.Row]]:
    """(matches left after `exclude`, the requested page of rows)."""
    _check_known(con, "venue", filters.venues, "--venue")
    _check_known(con, "selection", filters.selections, "--selection")
    where = ["fts MATCH ?"]
    params: list = [match]
    if filters.venues:
        where.append(f"p.venue IN ({', '.join('?' * len(filters.venues))})")
        params.extend(filters.venues)
    if filters.years:
        where.append("p.year BETWEEN ? AND ?")
        params.extend(filters.years)
    if filters.selections:
        where.append(f"p.selection IN ({', '.join('?' * len(filters.selections))})")
        params.extend(filters.selections)
    if filters.awarded:
        where.append("p.awards != '[]'")
    sql = (f"SELECT p.id, p.pid FROM fts JOIN papers p ON p.id = fts.rowid "
           f"WHERE {' AND '.join(where)} ORDER BY {_ORDER[sort]}")
    try:
        hits = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        raise QueryError(f"cannot search {match!r}: {exc}") from exc
    kept = [row[0] for row in hits if row[1] not in exclude]
    return len(kept), fetch_rows(con, kept[offset:offset + limit])


def badges(row) -> str:
    """`ICLR 2025 · oral · Outstanding Paper`: venue and year, the track unless plain main, award labels."""
    parts = [f"{row['venue_name']} {row['year']}"]
    if row["selection"] and row["selection"] != "main":
        parts.append(row["selection"])
    parts.extend(a["label"] for a in json.loads(row["awards"]))
    return " · ".join(parts)


def format_line(row) -> str:
    return f"{row['pid']} | {badges(row)} | {row['citation_count']} cites | {row['title']}"


def snippet(row) -> str:
    """The tldr, else the abstract clipped to SNIPPET_CHARS."""
    text = " ".join((row["tldr"] or row["abstract"]).split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rstrip() + "…"


def format_results(total: int, rows: list, offset: int, sort: str, abstract: bool = False) -> str:
    shown = f"showing {offset + 1}–{offset + len(rows)}" if rows else "showing none"
    lines = [f"{total} matches · {shown} · {sort}"]
    for row in rows:
        lines.append(format_line(row))
        if abstract and (text := snippet(row)):
            lines.append(f"    {text}")
    return "\n".join(lines)


def row_dict(row) -> dict:
    out = {key: row[key] for key in row.keys() if key != "id"}
    out["awards"] = json.loads(out["awards"])
    return out
