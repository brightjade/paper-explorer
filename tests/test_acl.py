from ppr.scrapers.acl import _parse_anthology, _parse_paper_list, _parse_paper_paragraphs
from bs4 import BeautifulSoup


ANTHOLOGY_HTML = """<html><body>
<div class="d-sm-flex align-items-stretch mb-3">
<span class="d-block">
<strong><a href="/2024.eacl-long.0/" class="align-middle">Proceedings of the 18th Conference</a></strong><br/>
<a href="/people/a/alice-editor/">Alice Editor</a>
</span></div>
<div class="d-sm-flex align-items-stretch mb-3">
<span class="d-block">
<strong><a href="/2024.eacl-long.1/" class="align-middle">Efficient Fine-tuning of Language Models</a></strong><br/>
<a href="/people/a/alice-smith/">Alice Smith</a> |
<a href="/people/b/bob-jones/">Bob Jones</a>
</span></div>
<div class="d-sm-flex align-items-stretch mb-3">
<span class="d-block">
<strong><a href="/2024.eacl-long.2/" class="align-middle">Multilingual Evaluation Benchmarks</a></strong><br/>
<a href="/people/c/carol-lee/">Carol Lee</a>
</span></div>
</body></html>"""


class TestParseAnthology:
    def test_extracts_papers(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        assert len(papers) == 2

    def test_paper_title(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        assert papers[0].title == "Efficient Fine-tuning of Language Models"

    def test_paper_authors(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        assert papers[0].authors == ["Alice Smith", "Bob Jones"]

    def test_paper_link(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        assert papers[0].link == "https://aclanthology.org/2024.eacl-long.1/"

    def test_selection(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        assert papers[0].selection == "main"

    def test_skips_proceedings_header(self):
        papers = _parse_anthology(ANTHOLOGY_HTML, "main")
        titles = [p.title for p in papers]
        assert "Proceedings of the 18th Conference" not in titles


# ACL Anthology wraps the first letter of a fixed-case word in its own span, so
# a title's text is split across nodes. `get_text(strip=True)` strips each node
# and joins with nothing, welding the words together: "of" + "L" + "atvian"
# becomes "ofLatvian". Semantic Scholar cannot match a query like that, which is
# how 521 papers across the four anthology-scraped venues sat permanently
# unenriched. Verified against https://aclanthology.org/volumes/2024.lrec-main/.
FIXED_CASE_HTML = """<html><body>
<div class="d-sm-flex align-items-stretch mb-3">
<span class="d-block">
<strong><a href="/2024.lrec-main.20/" class="align-middle">A Computational Model of <span class="acl-fixed-case">L</span>atvian Morphology</a></strong><br/>
<a href="/people/d/dana-krumina/">Dana <span class="acl-fixed-case">K</span>rumina</a>
</span></div>
<div class="d-sm-flex align-items-stretch mb-3">
<span class="d-block">
<strong><a href="/2024.lrec-main.21/" class="align-middle"><span class="acl-fixed-case">S</span>lovak<span class="acl-fixed-case">S</span>um: A Large Scale Dataset</a></strong><br/>
<a href="/people/e/erik-novak/">Erik Novak</a>
</span></div>
</body></html>"""


class TestParseAnthologyFixedCase:
    def test_title_keeps_spaces_around_fixed_case_spans(self):
        papers = _parse_anthology(FIXED_CASE_HTML, "main")
        assert papers[0].title == "A Computational Model of Latvian Morphology"

    def test_title_does_not_invent_spaces_inside_a_word(self):
        # "SlovakSum" is one word split across three nodes — joining with a
        # separator would wrongly yield "Slovak Sum".
        papers = _parse_anthology(FIXED_CASE_HTML, "main")
        assert papers[1].title == "SlovakSum: A Large Scale Dataset"

    def test_author_names_keep_spaces_around_fixed_case_spans(self):
        papers = _parse_anthology(FIXED_CASE_HTML, "main")
        assert papers[0].authors == ["Dana Krumina"]


class TestParseAuthorDelimiter:
    def test_comma_separated(self):
        html = '<ul><li><strong>Title</strong><em>Alice, Bob, Carol</em></li></ul>'
        soup = BeautifulSoup(html, "html.parser")
        papers = _parse_paper_list(soup, "main")
        assert papers[0].authors == ["Alice", "Bob", "Carol"]

    def test_and_separator(self):
        html = '<ul><li><strong>Title</strong><em>Alice, Bob and Carol</em></li></ul>'
        soup = BeautifulSoup(html, "html.parser")
        papers = _parse_paper_list(soup, "main")
        assert papers[0].authors == ["Alice", "Bob", "Carol"]

    def test_comma_and_mixed(self):
        html = '<ul><li><strong>Title</strong><em>Alice Smith, Bob Jones and Carol Lee</em></li></ul>'
        soup = BeautifulSoup(html, "html.parser")
        papers = _parse_paper_list(soup, "main")
        assert papers[0].authors == ["Alice Smith", "Bob Jones", "Carol Lee"]

    def test_semicolon_separated_paragraph(self):
        # EMNLP 2026's industry page: <p><strong>Title</strong><br/><em>A; B; C</em></p>
        html = '<p><strong>Title</strong><br/><em>Nicolas Bougie; Gian Maria Marconi; jufeng chen</em></p>'
        papers = _parse_paper_paragraphs(BeautifulSoup(html, "html.parser"), "industry")
        assert papers[0].authors == ["Nicolas Bougie", "Gian Maria Marconi", "jufeng chen"]


def test_emnlp_2026_is_registered_with_the_three_tracks(monkeypatch):
    from ppr.scrapers import SCRAPERS, acl

    calls = []
    monkeypatch.setattr(acl, "_scrape_paragraph_pages", lambda base, pages: calls.append((base, pages)) or [])
    SCRAPERS["emnlp_2026"]()
    assert calls == [("https://2026.emnlp.org", {
        "main": "/program/main_papers/",
        "findings": "/program/find_papers/",
        "industry": "/program/ind_papers/",
    })]
