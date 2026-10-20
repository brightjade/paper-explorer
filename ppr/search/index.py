"""The `ppr search` index: every paper in data/ in one SQLite file, with an FTS5 table.

Derived data. `open_index` rebuilds it whenever data/ or the schema changed, so a
search never reads a stale dataset, and writes it atomically, so a failed build
leaves the previous index in place.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ppr.awards.join import attach, attach_test_of_time, load_entries
from ppr.layout import awards_path, conference_ids, papers_path, split_id
from ppr.matching import title_key
from ppr.venues import load_registry

logger = logging.getLogger(__name__)

# Bump when the tables change: an index built by older code is then rebuilt.
SCHEMA_VERSION = 1

LIST_SEP = "; "

_ARXIV_VERSION = re.compile(r"v\d+$")

_SCHEMA = """
CREATE TABLE papers (
    id INTEGER PRIMARY KEY,
    pid TEXT NOT NULL UNIQUE,
    conf_id TEXT NOT NULL,
    venue TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    year INTEGER NOT NULL,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    authors TEXT NOT NULL,
    abstract TEXT NOT NULL,
    tldr TEXT NOT NULL,
    keywords TEXT NOT NULL,
    citation_count INTEGER NOT NULL,
    influential_citation_count INTEGER NOT NULL,
    selection TEXT NOT NULL,
    awards TEXT NOT NULL,
    link TEXT NOT NULL,
    forum_id TEXT NOT NULL,
    arxiv TEXT NOT NULL,
    doi TEXT NOT NULL,
    corpus_id INTEGER,
    publication_date TEXT NOT NULL
);
CREATE INDEX papers_title_key ON papers(title_key);
CREATE INDEX papers_arxiv ON papers(arxiv);
CREATE INDEX papers_doi ON papers(doi);
CREATE INDEX papers_corpus_id ON papers(corpus_id);
CREATE INDEX papers_forum_id ON papers(forum_id);
CREATE VIRTUAL TABLE fts USING fts5(
    title, abstract, tldr, keywords,
    content='papers', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_INSERT = (
    "INSERT INTO papers (pid, conf_id, venue, venue_name, year, title, title_key, authors, abstract, "
    "tldr, keywords, citation_count, influential_citation_count, selection, awards, link, forum_id, "
    "arxiv, doi, corpus_id, publication_date) VALUES (" + ", ".join("?" * 21) + ")"
)


class NoData(Exception):
    """data/ holds no conference: there is nothing to search."""


def pid_for(conf_id: str, title: str) -> str:
    """`iclr_2025:3fa9c1d2`: the same for a paper whatever the release or citation order."""
    return f"{conf_id}:{hashlib.sha1(title_key(title).encode('utf-8')).hexdigest()[:8]}"


def assign_pids(conf_id: str, papers: list[dict]) -> list[str]:
    """One pid per paper, in input order. A repeated title's later copies get `.2`, `.3`, ...

    The copies are ordered by (authors, link), not by position: the year file is
    sorted by citations, which change every month.
    """
    pids = [pid_for(conf_id, p["title"]) for p in papers]
    groups: dict[str, list[int]] = {}
    for i, pid in enumerate(pids):
        groups.setdefault(pid, []).append(i)
    for pid, members in groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda i: (LIST_SEP.join(papers[i].get("authors") or []),
                                                 papers[i].get("link") or ""))
        for n, i in enumerate(ordered[1:], start=2):
            pids[i] = f"{pid}.{n}"
    return pids


def fingerprint(data_dir: Path) -> str:
    """Changes whenever a year file or an awards file does, or the schema."""
    paths: set[Path] = set()
    for conf_id in conference_ids(data_dir):
        paths.add(papers_path(data_dir, conf_id))
        awards = awards_path(data_dir, conf_id)
        if awards.exists():
            paths.add(awards)
    digest = hashlib.sha256(f"schema {SCHEMA_VERSION}\n".encode())
    for path in sorted(paths):
        stat = path.stat()
        digest.update(f"{path.relative_to(data_dir)}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def load_dataset(data_dir: Path, venue_names: dict[str, str]) -> dict[str, list[dict]]:
    """Every conference's papers, awards joined exactly as scripts/build_data.py joins them."""
    papers_by_conf: dict[str, list[dict]] = {}
    tot_by_conf: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for conf_id in conference_ids(data_dir):
        with open(papers_path(data_dir, conf_id), encoding="utf-8") as f:
            papers = [json.loads(line) for line in f if line.strip()]
        if not papers:
            continue
        attached = attach(papers, load_entries(data_dir, conf_id))
        papers_by_conf[conf_id] = attached.papers
        if attached.test_of_time:
            tot_by_conf[conf_id] = attached.test_of_time
        prefix, year = split_id(conf_id)
        names[conf_id] = f"{venue_names.get(prefix, prefix.upper())} {year}"
    return attach_test_of_time(papers_by_conf, tot_by_conf, names).papers


def _text(value) -> str:
    if isinstance(value, dict):  # an S2 tldr object
        value = value.get("text")
    return value or ""


def _rows(papers_by_conf: dict[str, list[dict]], venue_names: dict[str, str]):
    for conf_id, papers in papers_by_conf.items():
        venue, year = split_id(conf_id)
        for pid, p in zip(assign_pids(conf_id, papers), papers):
            ext = p.get("external_ids") or {}
            yield (
                pid, conf_id, venue, venue_names.get(venue, venue.upper()), year,
                p["title"], title_key(p["title"]), LIST_SEP.join(p.get("authors") or []),
                _text(p.get("abstract")), _text(p.get("tldr")), LIST_SEP.join(p.get("keywords") or []),
                int(p.get("citation_count") or 0), int(p.get("influential_citation_count") or 0),
                p.get("selection") or "", json.dumps(p.get("awards") or []),
                p.get("link") or "", p.get("forum_id") or "",
                _ARXIV_VERSION.sub("", (ext.get("ArXiv") or "").strip()),
                (ext.get("DOI") or "").strip().lower(), ext.get("CorpusId"),
                p.get("publication_date") or "",
            )


def _release_tag(data_dir: Path) -> str:
    try:
        return json.loads((data_dir.parent / ".data-release.json").read_text(encoding="utf-8")).get("tag") or ""
    except (OSError, ValueError):
        return ""


def build_index(data_dir: Path, index_path: Path, fp: str | None = None) -> int:
    """Write the index of data/ to index_path atomically; return the number of papers."""
    fp = fp or fingerprint(data_dir)
    venue_names = {prefix: venue.name for prefix, venue in load_registry().items()}
    papers_by_conf = load_dataset(data_dir, venue_names)
    if not papers_by_conf:
        raise NoData(f"no conference data under {data_dir}; run `uv run python -m scripts.sync_data`")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=index_path.parent, prefix=".search-", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        con = sqlite3.connect(tmp)
        try:
            con.executescript(_SCHEMA)
            con.executemany(_INSERT, _rows(papers_by_conf, venue_names))
            con.execute("INSERT INTO fts (rowid, title, abstract, tldr, keywords) "
                        "SELECT id, title, abstract, tldr, keywords FROM papers")
            count = con.execute("SELECT count(*) FROM papers").fetchone()[0]
            con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
                ("schema_version", str(SCHEMA_VERSION)),
                ("fingerprint", fp),
                ("data_release", _release_tag(data_dir)),
                ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
                ("papers", str(count)),
            ])
            con.commit()
        finally:
            con.close()
        os.replace(tmp, index_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return count


def _connect_ro(index_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{index_path.resolve().as_uri()}?mode=ro", uri=True)


def _stored_fingerprint(index_path: Path) -> str | None:
    if not index_path.exists():
        return None
    try:
        con = _connect_ro(index_path)
        try:
            row = con.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def open_index(data_dir: Path, index_path: Path) -> sqlite3.Connection:
    """A read-only connection to an index of data/ as it is now, rebuilding it first if needed."""
    if not conference_ids(data_dir):
        raise NoData(f"no conference data under {data_dir}; run `uv run python -m scripts.sync_data`")
    fp = fingerprint(data_dir)
    if _stored_fingerprint(index_path) != fp:
        logger.info("Building the search index from %s", data_dir)
        count = build_index(data_dir, index_path, fp)
        logger.info("Indexed %d papers into %s", count, index_path)
    con = _connect_ro(index_path)
    con.row_factory = sqlite3.Row
    return con


def index_meta(con: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in con.execute("SELECT key, value FROM meta")}
