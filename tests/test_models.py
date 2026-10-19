import json

from ppr.models import Paper


class TestPaper:
    def test_abstract_source_round_trips(self):
        p = Paper(title="T", link="L", authors=["A"], abstract="x", abstract_source="s2")
        assert Paper.from_dict(json.loads(p.to_json())) == p

    def test_an_unmarked_abstract_leaves_no_key(self):
        assert "abstract_source" not in Paper(title="T", link="L", authors=["A"], abstract="x").to_dict()

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


def test_venue_date_round_trips():
    p = Paper(title="T", link="L", authors=["A"], venue_date="2025-02-03")
    assert Paper.from_dict(p.to_dict()).venue_date == "2025-02-03"


def test_empty_venue_date_is_absent_from_to_dict():
    assert "venue_date" not in Paper(title="T", link="L", authors=["A"]).to_dict()
