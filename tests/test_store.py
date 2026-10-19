import json

import pytest

from ppr.models import Paper
from ppr.store import (
    ShrinkError,
    carry_over,
    crawl_view,
    normalize_title,
    read_papers,
    save_crawl,
    save_enriched,
)


def _paper(**kw) -> Paper:
    base = dict(title="A Paper", link="L", authors=["X"], selection="oral")
    base.update(kw)
    return Paper(**base)


def _enriched(**kw) -> Paper:
    base = dict(citation_count=10, influential_citation_count=1, reference_count=20, tldr="T",
                publication_date="2025-01-01", fields_of_study=["CS"], open_access_pdf="pdf",
                external_ids={"CorpusId": 1}, match_status="matched")
    base.update(kw)
    return _paper(**base)


class TestNormalizeTitle:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_title("  A   Paper\nTitle ") == "a paper title"


class TestCarryOver:
    def test_copies_enrichment_but_not_identity(self):
        raw = _paper(title="A Paper", link="NEW", authors=["New"])
        prior = _paper(
            title="A Paper",
            link="OLD",
            authors=["Old"],
            citation_count=10,
            influential_citation_count=2,
            reference_count=20,
            tldr="Prior summary",
            publication_date="2024-01-01",
            fields_of_study=["CS"],
            open_access_pdf="https://old.pdf",
            external_ids={"CorpusId": 55},
            match_status="matched",
        )
        carry_over(raw, prior)
        assert raw.citation_count == 10
        assert raw.influential_citation_count == 2
        assert raw.reference_count == 20
        assert raw.tldr == "Prior summary"
        assert raw.publication_date == "2024-01-01"
        assert raw.fields_of_study == ["CS"]
        assert raw.open_access_pdf == "https://old.pdf"
        assert raw.external_ids == {"CorpusId": 55}
        assert raw.match_status == "matched"
        assert raw.link == "NEW"
        assert raw.authors == ["New"]

    def test_prior_abstract_fills_only_when_raw_is_empty(self):
        raw = _paper(abstract="")
        carry_over(raw, _paper(abstract="Prior abstract"))
        assert raw.abstract == "Prior abstract"

        raw2 = _paper(abstract="Fresh abstract")
        carry_over(raw2, _paper(abstract="Prior abstract"))
        assert raw2.abstract == "Fresh abstract"


class TestReadPapers:
    def test_missing_file_is_empty(self, tmp_path):
        assert read_papers(tmp_path / "nope.jsonl") == []

    def test_empty_file_is_empty(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        path.write_text("")
        assert read_papers(path) == []

    def test_reads_papers(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        path.write_text(
            json.dumps({"title": "A", "link": "L", "authors": ["X"]}) + "\n"
        )
        papers = read_papers(path)
        assert len(papers) == 1
        assert papers[0].title == "A"


class TestSaveEnriched:
    def test_sorts_by_citations_descending(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        save_enriched(
            [
                _paper(title="low", citation_count=1),
                _paper(title="high", citation_count=100),
                _paper(title="mid", citation_count=50),
            ],
            path,
        )
        titles = [json.loads(l)["title"] for l in path.read_text().splitlines()]
        assert titles == ["high", "mid", "low"]

    def test_uncited_papers_sort_last(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        save_enriched(
            [_paper(title="unknown"), _paper(title="zero", citation_count=0)], path
        )
        titles = [json.loads(l)["title"] for l in path.read_text().splitlines()]
        assert titles == ["zero", "unknown"]

    def test_replaces_existing_file(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        path.write_text("stale\n")
        save_enriched([_paper(title="fresh", citation_count=1)], path)
        assert "stale" not in path.read_text()
        assert "fresh" in path.read_text()

    def test_failure_mid_write_leaves_original_intact(self, tmp_path, monkeypatch):
        path = tmp_path / "2025.jsonl"
        original = json.dumps({"title": "original", "link": "L", "authors": ["X"]})
        path.write_text(original + "\n")

        def _boom(self):
            raise OSError("disk full")

        monkeypatch.setattr(Paper, "to_json", _boom)
        with pytest.raises(OSError):
            save_enriched([_paper(title="new")], path)
        assert path.read_text() == original + "\n"

    def test_leaves_no_temp_file_behind(self, tmp_path):
        path = tmp_path / "2025.jsonl"
        save_enriched([_paper(citation_count=1)], path)
        assert list(tmp_path.iterdir()) == [path]


class TestAbstractProvenance:
    def test_an_s2_abstract_travels_with_its_marker(self):
        raw = carry_over(_paper(), _enriched(abstract="S2", abstract_source="s2"))
        assert (raw.abstract, raw.abstract_source) == ("S2", "s2")

    def test_a_crawl_abstract_wins_and_stays_unmarked(self):
        raw = carry_over(_paper(abstract="OpenReview"), _enriched(abstract="S2", abstract_source="s2"))
        assert (raw.abstract, raw.abstract_source) == ("OpenReview", "")


class TestCrawlView:
    def test_leaves_exactly_what_the_crawl_gave(self):
        p = _enriched(abstract="S2", abstract_source="s2", keywords=["k"], forum_id="f", venue_date="2025-05-01")
        assert crawl_view(p) == _paper(keywords=["k"], forum_id="f", venue_date="2025-05-01")

    def test_keeps_a_crawl_abstract(self):
        assert crawl_view(_enriched(abstract="OpenReview")).abstract == "OpenReview"


class TestSaveCrawl:
    def test_a_first_crawl_writes_the_papers(self, tmp_path):
        path = tmp_path / "iclr" / "2026.jsonl"
        assert save_crawl([_paper(title="A"), _paper(title="B")], path) == path
        assert [p.title for p in read_papers(path)] == ["A", "B"]

    def test_a_recrawl_keeps_enrichment_and_takes_the_crawl_fields(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title="A", authors=["Old"], selection="poster")], path)
        save_crawl([_paper(title="A", authors=["New"], selection="oral")], path)
        [p] = read_papers(path)
        assert (p.authors, p.selection) == (["New"], "oral")
        assert (p.citation_count, p.external_ids, p.match_status) == (10, {"CorpusId": 1}, "matched")

    def test_title_drift_is_refused_before_it_wipes_enrichment(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_paper(title=f"P{i}", external_ids={"CorpusId": i + 1}) for i in range(10)], path)
        before = path.read_bytes()
        with pytest.raises(ShrinkError, match="keep a Semantic Scholar ID"):
            save_crawl([_paper(title=f"Q{i}") for i in range(10)], path)
        assert path.read_bytes() == before

    def test_a_crawl_keeping_half_the_enrichment_is_written(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_paper(title=f"P{i}", external_ids={"CorpusId": i + 1}) for i in range(10)], path)
        save_crawl([_paper(title=f"{c}{i}") for c in "PQ" for i in range(5)], path)
        assert sum(1 for p in read_papers(path) if p.external_ids.get("CorpusId")) == 5

    def test_an_unenriched_file_never_blocks_a_retitled_crawl(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_paper(title=f"P{i}") for i in range(10)], path)
        save_crawl([_paper(title=f"Q{i}") for i in range(10)], path)
        assert sorted(p.title for p in read_papers(path)) == sorted(f"Q{i}" for i in range(10))

    def test_titles_match_across_case_and_spacing(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title="A  Paper")], path)
        save_crawl([_paper(title="a paper")], path)
        assert read_papers(path)[0].citation_count == 10

    def test_a_paper_the_crawl_no_longer_lists_is_dropped(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title=t) for t in "ABC"], path)
        save_crawl([_paper(title="A"), _paper(title="B")], path)
        assert sorted(p.title for p in read_papers(path)) == ["A", "B"]

    def test_a_new_paper_arrives_unenriched_after_the_enriched_ones(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title="Old")], path)
        save_crawl([_paper(title="New"), _paper(title="Old")], path)
        assert [(p.title, p.citation_count) for p in read_papers(path)] == [("Old", 10), ("New", None)]

    def test_duplicate_titles_all_keep_enrichment(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title="Same")], path)
        save_crawl([_paper(title="Same", link="1"), _paper(title="Same", link="2")], path)
        assert sorted((p.link, p.citation_count) for p in read_papers(path)) == [("1", 10), ("2", 10)]

    def test_refuses_to_shrink_below_half_and_leaves_the_file(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title=f"P{i}") for i in range(10)], path)
        before = path.read_bytes()
        with pytest.raises(ShrinkError, match=r"returned 4 papers.*10 on disk"):
            save_crawl([_paper(title=f"P{i}") for i in range(4)], path)
        assert path.read_bytes() == before

    def test_the_refusal_names_the_way_to_accept_a_real_shrink(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title=f"P{i}") for i in range(10)], path)
        with pytest.raises(ShrinkError, match="delete"):
            save_crawl([], path)

    def test_exactly_half_is_kept(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title=f"P{i}") for i in range(10)], path)
        save_crawl([_paper(title=f"P{i}") for i in range(5)], path)
        assert len(read_papers(path)) == 5

    def test_zero_papers_over_nothing_is_fine(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        save_crawl([], path)
        assert read_papers(path) == []

    def test_a_file_of_blank_lines_counts_as_empty(self, tmp_path):
        path = tmp_path / "2026.jsonl"
        path.write_text("\n\n")
        save_crawl([], path)
        assert read_papers(path) == []

    def test_a_failed_write_leaves_the_old_file_and_no_temp(self, tmp_path, monkeypatch):
        path = tmp_path / "2026.jsonl"
        save_enriched([_enriched(title="A")], path)
        before = path.read_bytes()

        def boom(*_):
            raise OSError("disk full")

        monkeypatch.setattr("ppr.store.os.replace", boom)
        with pytest.raises(OSError):
            save_crawl([_paper(title="A")], path)
        assert path.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir()] == ["2026.jsonl"]
