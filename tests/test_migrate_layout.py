import json

import pytest

from ppr.awards.model import read_awards
from ppr.layout import conference_ids, papers_path
from ppr.models import Paper
from ppr.store import read_papers
from scripts.migrate_layout import MigrationError, migrate, verify


def _p(title, **kw):
    return Paper(title=title, link="L", authors=["A"], **kw)


def _write(path, papers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(p.to_json() + "\n" for p in papers), encoding="utf-8")


@pytest.fixture
def old(tmp_path):
    root = tmp_path / "old"
    _write(root / "iclr_2025" / "papers.jsonl", [
        _p("Crawl Abstract", abstract="From OpenReview."), _p("No Abstract"), _p("Same"), _p("Same")])
    _write(root / "iclr_2025" / "papers_enriched.jsonl", [
        _p("No Abstract", abstract="From S2.", citation_count=9),
        _p("Crawl Abstract", abstract="From OpenReview.", citation_count=5),
        _p("Same", citation_count=1), _p("Same", citation_count=1)])
    _write(root / "usenix_security_2024" / "papers.jsonl", [_p("Never Enriched")])
    (root / "iclr_2025" / "awards.json").write_text(json.dumps({"conf_id": "iclr_2025", "awards": [
        {"label": "Outstanding Paper", "kind": "award", "title": "Same", "via": "v", "source": "s"}]}))
    (root / "pipeline_state.json").write_text('{"deferred_streak": {}}\n')
    (root / "citation_updated.txt").write_text("2026-10-18\n")
    return root


def test_migrates_papers_awards_and_root_files(old, tmp_path):
    new = tmp_path / "new"
    assert migrate(old, new) == {"iclr_2025": 4, "usenix_security_2024": 1}
    assert conference_ids(new) == ["iclr_2025", "usenix_security_2024"]
    papers = read_papers(papers_path(new, "iclr_2025"))
    assert [(p.title, p.abstract_source) for p in papers] == [
        ("No Abstract", "s2"), ("Crawl Abstract", ""), ("Same", ""), ("Same", "")]
    assert [p.title for p in read_papers(papers_path(new, "usenix_security_2024"))] == ["Never Enriched"]
    assert [a.title for a in read_awards(new, "iclr_2025")] == ["Same"]
    assert (new / "pipeline_state.json").read_text() == '{"deferred_streak": {}}\n'
    assert (new / "citation_updated.txt").read_text() == "2026-10-18\n"
    verify(old, new)


def test_records_are_the_enriched_ones_byte_for_byte_apart_from_the_marker(old, tmp_path):
    new = tmp_path / "new"
    migrate(old, new)
    enriched = (old / "iclr_2025" / "papers_enriched.jsonl").read_text().splitlines()
    migrated = [json.loads(line) for line in papers_path(new, "iclr_2025").read_text().splitlines()]
    assert [json.dumps({k: v for k, v in m.items() if k != "abstract_source"}, ensure_ascii=False)
            for m in migrated] == enriched


def test_different_papers_in_the_two_files_fail_and_write_nothing(old, tmp_path):
    _write(old / "iclr_2025" / "papers.jsonl", [_p("Crawl Abstract"), _p("No Abstract"), _p("Same"), _p("New")])
    new = tmp_path / "new"
    with pytest.raises(MigrationError, match="iclr_2025.*ppr enrich"):
        migrate(old, new)
    assert not new.exists() or not any(new.iterdir())


def test_refuses_a_non_empty_target(old, tmp_path):
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / "x").write_text("")
    with pytest.raises(MigrationError, match="not empty"):
        migrate(old, tmp_path / "new")


@pytest.mark.parametrize("name", ["notes.txt", ".papers_enriched.tmp.jsonl"])
def test_refuses_a_file_it_does_not_know(old, tmp_path, name):
    (old / "iclr_2025" / name).write_text("")
    with pytest.raises(MigrationError, match=name.replace(".", r"\.")):
        migrate(old, tmp_path / "new")


def test_verify_catches_a_lost_paper(old, tmp_path):
    new = tmp_path / "new"
    migrate(old, new)
    path = papers_path(new, "iclr_2025")
    path.write_text("".join(path.read_text().splitlines(keepends=True)[1:]))
    with pytest.raises(MigrationError, match="iclr_2025"):
        verify(old, new)
