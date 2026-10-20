"""`ppr search lookup`: ground ids and titles in the dataset.

Offline: an item the dataset does not hold comes back `not in dataset`; whether
it was accepted somewhere else is for the caller to find out. Asta and Undermind
exports, web results and Zotero items all come through here.
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ppr.matching import MATCHED, MATCHED_FUZZY, match_verdict, title_key
from ppr.search.find import format_line, row_dict
from ppr.search.index import LIST_SEP

FOUND, FUZZY, MISSING = "found", "fuzzy", "not in dataset"
TITLE_CANDIDATES = 50  # fetched by bm25 over the ORed words, then re-ranked by title similarity
TITLE_VERDICTS = 5

_PID = re.compile(r"[a-z][a-z_]*_\d{4}:[0-9a-f]{8}(?:\.\d+)?")
_CORPUS = re.compile(r"(?:corpusid:|s2:)\s*(\d+)", re.I)
_OPENREVIEW = re.compile(r"(?:https?://)?openreview\.net/(?:forum|pdf)\?id=([\w-]+)", re.I)
_ARXIV = re.compile(
    r"(?:(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*|(?:https?://(?:dx\.)?doi\.org/)?10\.48550/arxiv\.)?"
    r"(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?", re.I)
_DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", re.I)
# A bare OpenReview forum id: one token mixing letters and digits. A one-word
# title can look the same, so a miss falls back to the title lookup.
_FORUM_ID = re.compile(r"(?=.*\d)(?=.*[A-Za-z])[\w-]{9,14}")
_WORD = re.compile(r"\w+")

_COLUMN = {"pid": "pid", "corpus": "corpus_id", "openreview": "forum_id", "arxiv": "arxiv", "doi": "doi"}


@dataclass(frozen=True)
class Item:
    raw: str
    kind: str  # pid | corpus | openreview | arxiv | doi | title
    value: str
    authors: tuple[str, ...] = ()


@dataclass
class Result:
    item: Item
    status: str
    rows: list = field(default_factory=list)


def classify(raw: str) -> Item:
    text = raw.strip()
    if _PID.fullmatch(text):
        return Item(raw, "pid", text)
    if m := _CORPUS.fullmatch(text):
        return Item(raw, "corpus", m[1])
    if m := _OPENREVIEW.match(text):
        return Item(raw, "openreview", m[1])
    if m := _ARXIV.fullmatch(text):
        return Item(raw, "arxiv", m[1])
    if m := _DOI.fullmatch(text):
        return Item(raw, "doi", m[1].lower())
    if _FORUM_ID.fullmatch(text):
        return Item(raw, "openreview", text)
    title, _, authors = text.partition(";;")
    return Item(raw, "title", title.strip(), tuple(a.strip() for a in authors.split(",") if a.strip()))


def _as_s2(row) -> dict:
    return {"title": row["title"], "authors": [{"name": n} for n in row["authors"].split(LIST_SEP) if n]}


def _by_title(con, item: Item) -> Result:
    key = title_key(item.value)
    if not key:
        return Result(item, MISSING)
    rows = con.execute("SELECT * FROM papers WHERE title_key = ? ORDER BY year, conf_id", (key,)).fetchall()
    if rows:
        return Result(item, FOUND, rows)
    words = sorted(set(_WORD.findall(item.value.lower())), key=len, reverse=True)[:12]
    if not words:
        return Result(item, MISSING)
    match = "title : (" + " OR ".join(f'"{w}"' for w in words) + ")"
    candidates = con.execute(
        "SELECT p.* FROM fts JOIN papers p ON p.id = fts.rowid WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
        (match, TITLE_CANDIDATES)).fetchall()
    candidates.sort(key=lambda row: -difflib.SequenceMatcher(None, key, row["title_key"]).ratio())
    accepted = [row for row in candidates[:TITLE_VERDICTS]
                if match_verdict(item.value, list(item.authors), _as_s2(row)) in (MATCHED, MATCHED_FUZZY)]
    return Result(item, FUZZY, accepted) if accepted else Result(item, MISSING)


def lookup(con, raw: str) -> Result:
    item = classify(raw)
    if item.kind == "title":
        return _by_title(con, item)
    value = int(item.value) if item.kind == "corpus" else item.value
    rows = con.execute(f"SELECT * FROM papers WHERE {_COLUMN[item.kind]} = ? ORDER BY year, conf_id",
                       (value,)).fetchall()
    if rows:
        return Result(item, FOUND, rows)
    if item.kind == "openreview" and "openreview" not in item.raw.lower():
        return _by_title(con, Item(item.raw, "title", item.value))
    return Result(item, MISSING)


def read_items(items: list[str], file: Path | None) -> list[str]:
    """Arguments, then the non-blank, non-`#` lines of `file`, stripped."""
    out = [i.strip() for i in items if i.strip()]
    if file is not None:
        out.extend(line.strip() for line in file.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.lstrip().startswith("#"))
    return out


def format_result(result: Result) -> str:
    lines = [f"{result.status}\t{result.item.raw.strip()}"]
    lines.extend(f"    {format_line(row)}" for row in result.rows)
    return "\n".join(lines)


def result_dict(result: Result) -> dict:
    return {"input": result.item.raw.strip(), "kind": result.item.kind, "status": result.status,
            "papers": [row_dict(row) for row in result.rows]}
