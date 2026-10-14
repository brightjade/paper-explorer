"""Tests for the CVF Open Access parser, CVF accepted-papers parser, and ECVA parser."""

from ppr.scrapers.cvf import CVF_CONFERENCES, SCRAPERS, _parse_accepted, _parse_ecva, _parse_openaccess

# Minimal fixture that mirrors the real CVF Open Access HTML structure.
# Structure observed from https://openaccess.thecvf.com/WACV2023:
#   <dl>
#     <dt class="ptitle"><br><a href="/content/.../paper.html">Title</a></dt>
#     <dd>  <!-- authors: one <form class="authsearch"> per author -->
#       <form ...><input name="query_author" value="First Last"/><a>...</a></form>
#       ...
#     </dd>
#     <dd>  <!-- links: pdf, supp, bibtex -->
#       [<a href="/content/.../papers/X_paper.pdf">pdf</a>]
#       ...
#     </dd>
#   </dl>
FIXTURE_HTML = """\
<!DOCTYPE html>
<html>
<body>
<div id="content">
  <dl>
    <dt class="ptitle"><br><a href="/content/WACV2023/html/Foo_Some_Great_Paper_WACV_2023_paper.html">Some Great Paper</a></dt>
    <dd>
      <form class="authsearch" action="/WACV2023" method="post">
        <input type="hidden" name="query_author" value="Alice Smith"/>
        <a href="#">Alice Smith</a>,
      </form>
      <form class="authsearch" action="/WACV2023" method="post">
        <input type="hidden" name="query_author" value="Bob Jones"/>
        <a href="#">Bob Jones</a>
      </form>
    </dd>
    <dd>
      [<a href="/content/WACV2023/papers/Foo_Some_Great_Paper_WACV_2023_paper.pdf">pdf</a>]
      [<a href="/content/WACV2023/supplemental/Foo_Some_Great_Paper_WACV_2023_supplemental.pdf">supp</a>]
    </dd>
    <dt class="ptitle"><br><a href="/content/WACV2023/html/Bar_Another_Wonderful_Study_WACV_2023_paper.html">Another Wonderful Study</a></dt>
    <dd>
      <form class="authsearch" action="/WACV2023" method="post">
        <input type="hidden" name="query_author" value="Carol White"/>
        <a href="#">Carol White</a>
      </form>
    </dd>
    <dd>
      [<a href="/content/WACV2023/papers/Bar_Another_Wonderful_Study_WACV_2023_paper.pdf">pdf</a>]
    </dd>
  </dl>
</div>
</body>
</html>
"""

BASE_URL = "https://openaccess.thecvf.com"


class TestParseOpenaccess:
    def test_extracts_correct_number_of_papers(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        assert len(papers) == 2

    def test_correct_titles(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        assert papers[0].title == "Some Great Paper"
        assert papers[1].title == "Another Wonderful Study"

    def test_correct_authors_first_paper(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        assert papers[0].authors == ["Alice Smith", "Bob Jones"]

    def test_correct_authors_second_paper(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        assert papers[1].authors == ["Carol White"]

    def test_correct_pdf_links_absolute(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        assert papers[0].link == (
            "https://openaccess.thecvf.com"
            "/content/WACV2023/papers/Foo_Some_Great_Paper_WACV_2023_paper.pdf"
        )
        assert papers[1].link == (
            "https://openaccess.thecvf.com"
            "/content/WACV2023/papers/Bar_Another_Wonderful_Study_WACV_2023_paper.pdf"
        )

    def test_selection_is_main(self):
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        for paper in papers:
            assert paper.selection == "main"

    def test_skips_dt_without_anchor(self):
        html = """\
        <dl>
          <dt class="ptitle"><br></dt>
          <dd><form><input name="query_author" value="No One"/></form></dd>
          <dd>[<a href="/content/X/papers/X_paper.pdf">pdf</a>]</dd>
        </dl>
        """
        papers = _parse_openaccess(html, BASE_URL)
        assert len(papers) == 0

    def test_fallback_to_html_link_when_no_pdf(self):
        """When no PDF link is present in the links dd, fall back to the HTML page link."""
        html = """\
        <dl>
          <dt class="ptitle"><br><a href="/content/WACV2023/html/X_paper.html">No PDF Paper</a></dt>
          <dd>
            <form><input name="query_author" value="Dan Brown"/></form>
          </dd>
          <dd>
            [<a href="/content/WACV2023/supplemental/X_supp.pdf">supp</a>]
          </dd>
        </dl>
        """
        papers = _parse_openaccess(html, BASE_URL)
        assert len(papers) == 1
        assert papers[0].link == (
            "https://openaccess.thecvf.com/content/WACV2023/html/X_paper.html"
        )

    def test_empty_html_returns_empty_list(self):
        papers = _parse_openaccess("<html><body></body></html>", BASE_URL)
        assert papers == []

    def test_authors_already_in_first_last_order(self):
        """CVF authors are in 'First Last' format, not 'Last, First'."""
        papers = _parse_openaccess(FIXTURE_HTML, BASE_URL)
        # Verify no comma-separated "Last, First" format is present
        for paper in papers:
            for author in paper.authors:
                assert "," not in author, f"Unexpected comma in author: {author!r}"


# ---------------------------------------------------------------------------
# Fixture for _parse_accepted
# ---------------------------------------------------------------------------
# Mirrors the real HTML structure observed at:
#   https://wacv.thecvf.com/Conferences/2026/AcceptedPapers
#   https://iccv.thecvf.com/Conferences/2025/AcceptedPapers
#
# Key observations:
#   - Each paper is in a <tr>; title in first <td> inside <strong>.
#   - Papers with a project page have <a href="..."> instead of <strong>.
#   - Authors are in <i> inside <div class="indented">, separated by U+00B7 (·).
#   - No PDF links exist on these pre-publication pages.
ACCEPTED_FIXTURE_HTML = """\
<!DOCTYPE html>
<html>
<body>
<table>
  <!-- Paper 1: title in <strong>, three authors -->
  <tr>
    <td>
      <strong>Alpha Paper: A Study in Depth</strong>
      Poster Session 1<br>
      <div class="indented">
        <i>Alice Smith · Bob Jones · Carol White</i>
      </div>
    </td>
    <td></td>
    <td style="width:20%;">Hall A 101</td>
  </tr>
  <!-- Paper 2: title in <a> (project page), two authors -->
  <tr style="background-color: #f3f3f3">
    <td>
      <a href="https://example.com/beta" target="_blank">Beta Research: New Directions</a>
      Poster Session 2<br>
      <div class="indented">
        <i>Dan Brown · Eve Davis</i>
      </div>
    </td>
    <td></td>
    <td style="width:20%;">Hall B 202</td>
  </tr>
  <!-- Section header row using <th> elements — should be skipped (no <td>) -->
  <tr>
    <th colspan="3">Session Header Text</th>
  </tr>
  <!-- Row with a <td> but no title (no <strong> and no <a href>) — skipped -->
  <tr>
    <td>Just some descriptive text, no title tag</td>
  </tr>
</table>
</body>
</html>
"""


class TestParseAccepted:
    def test_extracts_papers(self):
        """All paper rows (strong or linked title + indented authors) are extracted."""
        papers = _parse_accepted(ACCEPTED_FIXTURE_HTML)
        assert len(papers) == 2

    def test_paper_title(self):
        papers = _parse_accepted(ACCEPTED_FIXTURE_HTML)
        assert papers[0].title == "Alpha Paper: A Study in Depth"
        assert papers[1].title == "Beta Research: New Directions"

    def test_authors_split_on_middledot(self):
        """Authors are split on U+00B7 MIDDLE DOT and stripped."""
        papers = _parse_accepted(ACCEPTED_FIXTURE_HTML)
        assert papers[0].authors == ["Alice Smith", "Bob Jones", "Carol White"]
        assert papers[1].authors == ["Dan Brown", "Eve Davis"]

    def test_no_pdf_link(self):
        """link is empty string because PDFs are not yet published."""
        papers = _parse_accepted(ACCEPTED_FIXTURE_HTML)
        for paper in papers:
            assert paper.link == ""

    def test_selection_is_main(self):
        papers = _parse_accepted(ACCEPTED_FIXTURE_HTML)
        for paper in papers:
            assert paper.selection == "main"

    def test_empty_html_returns_empty_list(self):
        papers = _parse_accepted("<html><body></body></html>")
        assert papers == []

    def test_skips_rows_without_authors(self):
        """Rows that have a <strong> but no indented author block are still included
        (with an empty authors list); rows with no title at all are skipped."""
        html = """\
        <table>
          <tr>
            <td>
              <strong>Title Only Paper</strong>
              No author block here
            </td>
          </tr>
          <tr>
            <td>No title, no authors</td>
          </tr>
        </table>
        """
        papers = _parse_accepted(html)
        # The first row has a title but no authors — still a valid paper entry
        assert len(papers) == 1
        assert papers[0].title == "Title Only Paper"
        assert papers[0].authors == []


# ---------------------------------------------------------------------------
# Fixture for _parse_ecva
# ---------------------------------------------------------------------------
# Mirrors the real HTML structure observed at https://www.ecva.net/papers.php.
#
# Key observations:
#   - Papers are inside <div id="content"><dl> inside an accordion section.
#   - Each paper: <dt class="ptitle"><a href="papers/...php">Title</a></dt>
#   - First <dd>: plain-text comma-separated authors in "First Last" order;
#     some authors have a trailing '*' (corresponding-author marker).
#   - Second <dd>: links including the PDF (relative href ending with .pdf,
#     no "supp" in path) and an optional supplementary PDF.
#   - PDF hrefs are relative; base URL is https://www.ecva.net.
ECVA_FIXTURE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<body>
<div class="py-6 container">
  <h2>ECCV Conference Papers</h2>
  <button class="accordion">ECCV 2024 Papers</button>
  <div class="accordion-content">
  <div id="content"> <dl>
    <!-- Paper 1: two authors, one with asterisk -->
    <dt class="ptitle"><br>
<a href="papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php">
First Great Paper</a>
</dt><dd>
Alice Smith*, Bob Jones</dd>
<dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00004.pdf'>pdf</a>]
<div class="link2">
[<a href='papers/eccv_2024/papers_ECCV/papers/00004-supp.pdf'>supplementary material</a>]
</div>
</dd>
    <!-- Paper 2: single author with asterisk -->
    <dt class="ptitle"><br>
<a href="papers/eccv_2024/papers_ECCV/html/6_ECCV_2024_paper.php">
Second Interesting Paper</a>
</dt><dd>
Carol White*</dd>
<dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00006.pdf'>pdf</a>]
</dd>
  </dl>
  </div>
  </div>
</div>
</body>
</html>
"""

ECVA_BASE_URL = "https://www.ecva.net"


class TestParseEcva:
    def test_extracts_papers(self):
        """Both paper entries in the fixture are extracted."""
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        assert len(papers) == 2

    def test_paper_title(self):
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        assert papers[0].title == "First Great Paper"
        assert papers[1].title == "Second Interesting Paper"

    def test_paper_authors(self):
        """Authors are in 'First Last' format; trailing '*' is stripped."""
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        assert papers[0].authors == ["Alice Smith", "Bob Jones"]
        assert papers[1].authors == ["Carol White"]

    def test_paper_pdf_link(self):
        """PDF link is the main PDF (no 'supp') made absolute with ecva.net base."""
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        assert papers[0].link == (
            "https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00004.pdf"
        )
        assert papers[1].link == (
            "https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00006.pdf"
        )

    def test_selection_is_main(self):
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        for paper in papers:
            assert paper.selection == "main"

    def test_no_asterisks_in_author_names(self):
        """No '*' should appear in any parsed author name."""
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        for paper in papers:
            for author in paper.authors:
                assert "*" not in author, f"Unexpected '*' in author: {author!r}"

    def test_authors_in_first_last_format(self):
        """Authors must not contain a comma (not 'Last, First' format)."""
        papers = _parse_ecva(ECVA_FIXTURE_HTML)
        for paper in papers:
            for author in paper.authors:
                assert "," not in author, f"Unexpected comma in author: {author!r}"

    def test_empty_html_returns_empty_list(self):
        papers = _parse_ecva("<html><body></body></html>")
        assert papers == []

    def test_filters_by_year(self):
        """When year is given, only papers from that accordion section are returned."""
        html = """\
        <div class="py-6 container">
          <button class="accordion">ECCV 2022 Papers</button>
          <div class="accordion-content">
          <div id="content"><dl>
            <dt class="ptitle"><br><a href="papers/eccv_2022/html/1.php">Old Paper</a></dt>
            <dd>Author A</dd>
            <dd>[<a href='papers/eccv_2022/papers/00001.pdf'>pdf</a>]</dd>
          </dl></div>
          </div>
          <button class="accordion">ECCV 2024 Papers</button>
          <div class="accordion-content">
          <div id="content"><dl>
            <dt class="ptitle"><br><a href="papers/eccv_2024/html/2.php">New Paper</a></dt>
            <dd>Author B</dd>
            <dd>[<a href='papers/eccv_2024/papers/00002.pdf'>pdf</a>]</dd>
          </dl></div>
          </div>
        </div>
        """
        papers = _parse_ecva(html, year=2024)
        assert len(papers) == 1
        assert papers[0].title == "New Paper"

    def test_no_year_returns_all(self):
        """When year is None, all papers from all sections are returned."""
        html = """\
        <div class="py-6 container">
          <button class="accordion">ECCV 2022 Papers</button>
          <div class="accordion-content">
          <div id="content"><dl>
            <dt class="ptitle"><br><a href="papers/eccv_2022/html/1.php">Old Paper</a></dt>
            <dd>Author A</dd>
            <dd>[<a href='papers/eccv_2022/papers/00001.pdf'>pdf</a>]</dd>
          </dl></div>
          </div>
          <button class="accordion">ECCV 2024 Papers</button>
          <div class="accordion-content">
          <div id="content"><dl>
            <dt class="ptitle"><br><a href="papers/eccv_2024/html/2.php">New Paper</a></dt>
            <dd>Author B</dd>
            <dd>[<a href='papers/eccv_2024/papers/00002.pdf'>pdf</a>]</dd>
          </dl></div>
          </div>
        </div>
        """
        papers = _parse_ecva(html)
        assert len(papers) == 2

    def test_skips_dt_without_anchor(self):
        html = """\
        <dl>
          <dt class="ptitle"><br></dt>
          <dd>No One</dd>
          <dd>[<a href='papers/eccv_2024/papers_ECCV/papers/99999.pdf'>pdf</a>]</dd>
        </dl>
        """
        papers = _parse_ecva(html)
        assert len(papers) == 0


class TestCvfScrapersDict:
    def test_all_conferences_registered(self):
        for conf_id in CVF_CONFERENCES:
            assert conf_id in SCRAPERS, f"{conf_id} not in SCRAPERS"

    def test_expected_conference_ids(self):
        expected = {
            "cvpr_2023", "cvpr_2024", "cvpr_2025", "cvpr_2026",
            "iccv_2023", "iccv_2025",
            "wacv_2023", "wacv_2024", "wacv_2025", "wacv_2026",
            "eccv_2024",
        }
        # A subset, not equality: the monthly pipeline registers new
        # conference-years on its own, and an equality check would fail every
        # one of them. Dropping an existing registration still fails here.
        assert expected <= set(CVF_CONFERENCES.keys())

    def test_scrapers_are_callable(self):
        for conf_id, scraper in SCRAPERS.items():
            assert callable(scraper), f"{conf_id} scraper is not callable"
