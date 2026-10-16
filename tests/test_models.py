import json

from ppr.models import Paper


class TestPaper:
    def test_to_dict_full(self):
        paper = Paper(
            title="Test Paper",
            link="https://openreview.net/pdf?id=abc123",
            authors=["Alice", "Bob"],
            keywords=["ML", "NLP"],
            abstract="A test abstract.",
            forum_id="abc123",
        )
        d = paper.to_dict()
        assert d["title"] == "Test Paper"
        assert d["authors"] == ["Alice", "Bob"]
        assert d["keywords"] == ["ML", "NLP"]
        assert d["abstract"] == "A test abstract."
        assert d["forum_id"] == "abc123"
        assert "citation_count" not in d  # None is excluded

    def test_to_dict_minimal(self):
        paper = Paper(title="Min", link="http://x", authors=["A"])
        d = paper.to_dict()
        assert d["title"] == "Min"
        assert d["authors"] == ["A"]
        assert "abstract" not in d  # empty string excluded
        assert "forum_id" not in d
        assert "citation_count" not in d

    def test_to_dict_includes_citation_when_set(self):
        paper = Paper(
            title="T", link="L", authors=[], citation_count=42
        )
        d = paper.to_dict()
        assert d["citation_count"] == 42

    def test_to_dict_includes_zero_citation(self):
        paper = Paper(title="T", link="L", authors=[], citation_count=0)
        d = paper.to_dict()
        assert d["citation_count"] == 0

    def test_to_json(self):
        paper = Paper(title="Test", link="http://x", authors=["A"])
        j = paper.to_json()
        parsed = json.loads(j)
        assert parsed["title"] == "Test"

    def test_from_dict(self):
        data = {
            "title": "Test",
            "link": "http://x",
            "authors": ["A", "B"],
            "keywords": ["k1"],
            "abstract": "abs",
            "citation_count": 10,
            "forum_id": "xyz",
        }
        paper = Paper.from_dict(data)
        assert paper.title == "Test"
        assert paper.authors == ["A", "B"]
        assert paper.citation_count == 10

    def test_from_dict_minimal(self):
        data = {"title": "T", "link": "L"}
        paper = Paper.from_dict(data)
        assert paper.title == "T"
        assert paper.authors == []
        assert paper.keywords == []
        assert paper.abstract == ""
        assert paper.citation_count is None

    def test_keywords_as_list(self):
        paper = Paper(
            title="T", link="L", authors=[], keywords=["deep learning", "NLP"]
        )
        assert isinstance(paper.keywords, list)
        assert len(paper.keywords) == 2

    def test_new_enrichment_fields(self):
        paper = Paper(
            title="T",
            link="L",
            authors=["A"],
            citation_count=42,
            influential_citation_count=5,
            reference_count=30,
            tldr="A short summary.",
            publication_date="2025-01-15",
            fields_of_study=["Computer Science"],
            open_access_pdf="https://arxiv.org/pdf/1234.pdf",
            external_ids={"ArXiv": "1234.5678", "DOI": "10.1234/test"},
        )
        d = paper.to_dict()
        assert d["influential_citation_count"] == 5
        assert d["reference_count"] == 30
        assert d["tldr"] == "A short summary."
        assert d["publication_date"] == "2025-01-15"
        assert d["fields_of_study"] == ["Computer Science"]
        assert d["open_access_pdf"] == "https://arxiv.org/pdf/1234.pdf"
        assert d["external_ids"] == {"ArXiv": "1234.5678", "DOI": "10.1234/test"}

    def test_to_dict_excludes_empty_collections(self):
        paper = Paper(title="T", link="L", authors=["A"])
        d = paper.to_dict()
        assert "fields_of_study" not in d
        assert "external_ids" not in d

    def test_from_dict_with_new_fields(self):
        data = {
            "title": "T",
            "link": "L",
            "authors": ["A"],
            "influential_citation_count": 3,
            "reference_count": 20,
            "tldr": "Summary",
            "publication_date": "2025-06-01",
            "fields_of_study": ["CS", "Math"],
            "open_access_pdf": "https://example.com/paper.pdf",
            "external_ids": {"DOI": "10.1234"},
        }
        paper = Paper.from_dict(data)
        assert paper.influential_citation_count == 3
        assert paper.reference_count == 20
        assert paper.tldr == "Summary"
        assert paper.fields_of_study == ["CS", "Math"]
        assert paper.open_access_pdf == "https://example.com/paper.pdf"
        assert paper.external_ids == {"DOI": "10.1234"}


import pytest

from ppr.models import EmptyOverwriteError, write_papers


def _paper(title: str) -> Paper:
    return Paper(title=title, link=f"https://x.test/{title}", authors=["A"])


class TestWritePapers:
    def test_writes_one_json_object_per_line(self, tmp_path):
        path = tmp_path / "papers.jsonl"
        write_papers([_paper("P1"), _paper("P2")], path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert [json.loads(line)["title"] for line in lines] == ["P1", "P2"]

    def test_creates_missing_parent_directories(self, tmp_path):
        path = tmp_path / "iclr_2027" / "papers.jsonl"
        assert write_papers([_paper("P1")], path) == path
        assert path.exists()

    def test_replaces_rather_than_appends(self, tmp_path):
        path = tmp_path / "papers.jsonl"
        write_papers([_paper("P1"), _paper("P2")], path)
        write_papers([_paper("P3")], path)
        assert path.read_text(encoding="utf-8").strip().split("\n") == [
            _paper("P3").to_json()
        ]

    def test_refuses_to_replace_a_populated_file_with_nothing(self, tmp_path):
        """A broken source -- an OpenReview exception swallowed into `[]`, or a
        selector a site redesign outgrew -- must not truncate a good crawl."""
        path = tmp_path / "papers.jsonl"
        write_papers([_paper("P1"), _paper("P2")], path)
        before = path.read_bytes()

        with pytest.raises(EmptyOverwriteError) as exc:
            write_papers([], path)

        assert path.read_bytes() == before
        assert "2" in str(exc.value)

    def test_zero_papers_for_a_new_conference_is_allowed(self, tmp_path):
        """The guard is about erasing real data, not about writing nothing."""
        path = tmp_path / "papers.jsonl"
        write_papers([], path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""

    def test_zero_papers_over_an_already_empty_file_is_allowed(self, tmp_path):
        path = tmp_path / "papers.jsonl"
        path.write_text("\n\n", encoding="utf-8")
        write_papers([], path)
        assert path.read_text(encoding="utf-8") == ""

    def test_a_smaller_but_nonzero_crawl_still_writes(self, tmp_path):
        """Only zero is refused here. Proportional shrinkage is `ppr/enrich.py`'s
        MIN_RAW_RATIO guard to judge, on the file this one produces."""
        path = tmp_path / "papers.jsonl"
        write_papers([_paper(f"P{i}") for i in range(100)], path)
        write_papers([_paper("P1")], path)
        assert path.read_text(encoding="utf-8").strip().split("\n") == [
            _paper("P1").to_json()
        ]


def test_venue_date_round_trips():
    p = Paper(title="T", link="L", authors=["A"], venue_date="2025-02-03")
    assert Paper.from_dict(p.to_dict()).venue_date == "2025-02-03"


def test_empty_venue_date_is_absent_from_to_dict():
    assert "venue_date" not in Paper(title="T", link="L", authors=["A"]).to_dict()
