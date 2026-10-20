import json
import sqlite3

import pytest

from ppr.search import index
from ppr.search.index import NoData, assign_pids, build_index, open_index, pid_for
from tests.search_helpers import CDR, ERASE, ICLR, MU, make_dataset, write_papers


@pytest.fixture
def dataset(tmp_path):
    return make_dataset(tmp_path), tmp_path / ".cache" / "search.sqlite"


def _by_title(con):
    return {row["title"]: row for row in con.execute("SELECT * FROM papers")}


def test_builds_every_paper_with_awards_and_ids(dataset):
    rows = _by_title(open_index(*dataset))
    assert len(rows) == 5
    mu = rows[MU]
    assert (mu["conf_id"], mu["venue"], mu["venue_name"], mu["year"]) == ("iclr_2024", "iclr", "ICLR", 2024)
    assert json.loads(mu["awards"]) == [{"label": "Outstanding Paper", "kind": "award"}]
    assert (mu["arxiv"], mu["corpus_id"], mu["forum_id"]) == ("2401.00001", 101, "abc123XYZ9")
    assert mu["authors"] == "Ann Lee; Bo Kim" and mu["keywords"] == "unlearning; privacy"
    assert mu["pid"] == pid_for("iclr_2024", MU)
    assert rows[ERASE]["arxiv"] == "2303.07345"
    assert rows[CDR]["doi"] == "10.5555/cdr.1"
    assert json.loads(rows[CDR]["awards"]) == []


def test_fts_matches_stems(dataset):
    con = open_index(*dataset)
    hits = con.execute("SELECT p.title FROM fts JOIN papers p ON p.id = fts.rowid WHERE fts MATCH ?",
                       ('"unlearn"',)).fetchall()
    assert [h[0] for h in hits] == [MU]


def test_reuses_an_index_whose_fingerprint_matches(dataset, monkeypatch):
    open_index(*dataset).close()
    monkeypatch.setattr(index, "build_index", lambda *a, **k: pytest.fail("rebuilt an up-to-date index"))
    open_index(*dataset).close()


def test_rebuilds_when_a_year_file_changes(dataset):
    data_dir, path = dataset
    open_index(data_dir, path).close()
    write_papers(data_dir, "iclr_2024", ICLR[:2])
    assert open_index(data_dir, path).execute("SELECT count(*) FROM papers").fetchone()[0] == 4


def test_rebuilds_when_awards_change(dataset):
    data_dir, path = dataset
    open_index(data_dir, path).close()
    (data_dir / "iclr" / "awards.json").write_text(json.dumps({"2024": []}), encoding="utf-8")
    con = open_index(data_dir, path)
    assert con.execute("SELECT count(*) FROM papers WHERE awards != '[]'").fetchone()[0] == 0


def test_failed_build_keeps_the_old_index(dataset, monkeypatch):
    data_dir, path = dataset
    open_index(data_dir, path).close()
    before = path.read_bytes()
    write_papers(data_dir, "iclr_2024", ICLR[:1])

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(index, "_rows", boom)
    with pytest.raises(RuntimeError):
        open_index(data_dir, path)
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".search-*.tmp"))


def test_pids_survive_a_rebuild_and_a_reordering(dataset):
    data_dir, path = dataset
    first = {r["title"]: r["pid"] for r in open_index(data_dir, path).execute("SELECT title, pid FROM papers")}
    write_papers(data_dir, "iclr_2024", list(reversed(ICLR)))  # next month's citation order
    build_index(data_dir, path)
    second = {r["title"]: r["pid"] for r in open_index(data_dir, path).execute("SELECT title, pid FROM papers")}
    assert first == second


def test_repeated_titles_get_suffixes_in_author_order():
    papers = [{"title": "Same Title", "authors": ["Zed"]},
              {"title": "Same Title", "authors": ["Amy"]},
              {"title": "Other", "authors": []}]
    base = pid_for("acl_2020", "Same Title")
    assert assign_pids("acl_2020", papers) == [f"{base}.2", base, pid_for("acl_2020", "Other")]


def test_pid_shape():
    assert pid_for("usenix_security_2025", "A Title").startswith("usenix_security_2025:")
    assert len(pid_for("iclr_2024", MU).split(":")[1]) == 8


def test_no_conference_data_is_an_error(tmp_path):
    with pytest.raises(NoData, match="sync_data"):
        open_index(tmp_path / "data", tmp_path / ".cache" / "search.sqlite")


def test_connection_is_read_only(dataset):
    con = open_index(*dataset)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM papers")


def test_meta_records_the_release_and_count(dataset):
    data_dir, path = dataset
    (data_dir.parent / ".data-release.json").write_text(
        json.dumps({"tag": "data-2026-10-19", "files": {}}), encoding="utf-8")
    meta = index.index_meta(open_index(data_dir, path))
    assert meta["data_release"] == "data-2026-10-19"
    assert meta["papers"] == "5"
    assert meta["schema_version"] == str(index.SCHEMA_VERSION)
