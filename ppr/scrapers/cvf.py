"""Scraper for CV conferences from CVF Open Access, CVF accepted-papers pages, and ECVA.

Covers CVPR, ICCV, WACV (via openaccess.thecvf.com or conference accepted-papers pages)
and ECCV (via ecva.net).
"""

import logging
from functools import partial
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ppr.models import Paper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def _parse_openaccess(html: str, base_url: str) -> list[Paper]:
    """Parse papers from a CVF Open Access HTML page.

    The page structure uses a definition list (<dl>):
    - <dt class="ptitle"> holds the paper title in an <a> tag.
    - The first following <dd> holds one <form class="authsearch"> per author;
      each form contains a hidden <input name="query_author"> whose value is
      the author's full name in "First Last" order.
    - The second following <dd> holds links including the PDF (href contains
      '/papers/' and ends with '.pdf').
    """
    soup = BeautifulSoup(html, "html.parser")
    papers: list[Paper] = []

    for dt in soup.select("dt.ptitle"):
        # Extract title from the anchor inside the dt
        title_a = dt.select_one("a")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        if not title:
            continue

        # Collect the two <dd> siblings that follow this <dt>
        dds: list = []
        sib = dt.next_sibling
        while sib and len(dds) < 2:
            if hasattr(sib, "name") and sib.name == "dd":
                dds.append(sib)
            sib = sib.next_sibling

        if not dds:
            continue

        # Authors from the first <dd>: hidden inputs with name="query_author"
        author_inputs = dds[0].select("input[name=query_author]")
        authors = [inp.get("value", "").strip() for inp in author_inputs]
        authors = [a for a in authors if a]

        # PDF link from the second <dd> (if present, else fall back to first)
        pdf_href = ""
        link_dd = dds[1] if len(dds) > 1 else dds[0]
        for a_tag in link_dd.select("a[href]"):
            href = a_tag.get("href", "")
            if "/papers/" in href and href.endswith(".pdf"):
                pdf_href = href
                break

        if pdf_href:
            link = urljoin(base_url, pdf_href)
        else:
            # Fallback: use the HTML page link from the title anchor
            href = title_a.get("href", "")
            link = urljoin(base_url, href) if href else ""

        papers.append(Paper(
            title=title,
            link=link,
            authors=authors,
            selection="main",
        ))

    logger.info("Parsed %d papers from %s", len(papers), base_url)
    return papers


def _parse_accepted(html: str) -> list[Paper]:
    """Parse papers from a CVF accepted-papers page (e.g. ICCV 2025, WACV 2026).

    These pages are used before papers appear on CVF Open Access.  Each paper
    occupies a <tr> whose first <td> contains the title and authors:

        <td>
          <strong>Paper Title Here</strong>    <!-- or <a href="..."> for papers
                                                    with a project page -->
          Session name<br>
          <div class="indented">
            <i>Author One · Author Two · Author Three</i>
          </div>
        </td>

    Authors are separated by U+00B7 MIDDLE DOT (·).  Because PDFs are not yet
    published, ``link`` is always set to ``""``.
    """
    soup = BeautifulSoup(html, "html.parser")
    papers: list[Paper] = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        td = tds[0]

        # Extract title — prefer <strong>, fall back to first <a> with href
        strong = td.find("strong")
        if strong:
            title = strong.get_text(strip=True)
        else:
            a_tag = td.find("a", href=True)
            if a_tag:
                title = a_tag.get_text(strip=True)
            else:
                continue

        if not title:
            continue

        # Authors live in <i> inside <div class="indented">
        indented = td.find("div", class_="indented")
        authors: list[str] = []
        if indented:
            i_tag = indented.find("i")
            if i_tag:
                raw = i_tag.get_text(strip=True)
                authors = [a.strip() for a in raw.split("\u00b7") if a.strip()]

        papers.append(Paper(
            title=title,
            link="",
            authors=authors,
            selection="main",
        ))

    logger.info("Parsed %d papers from accepted-papers page", len(papers))
    return papers


def _parse_ecva(html: str, year: int | None = None) -> list[Paper]:
    """Parse papers from the ECVA papers page (https://www.ecva.net/papers.php).

    The page contains papers from multiple ECCV years in accordion sections.
    When *year* is given, only the matching section is parsed.

    Page structure uses a definition list inside ``<div id="content">``:

    - ``<dt class="ptitle">`` holds the paper title in an ``<a>`` tag with a
      relative href.
    - The first following ``<dd>`` holds all authors as plain comma-separated
      text in "First Last" order. Individual names may carry a trailing ``*``
      (corresponding author marker) that is stripped.
    - The second following ``<dd>`` holds links; the first ``<a href>`` whose
      href ends with ``.pdf`` and does not contain ``supp`` is the main PDF.

    PDF hrefs are relative to ``ECVA_BASE_URL`` and are made absolute with
    :func:`urllib.parse.urljoin`.
    """
    soup = BeautifulSoup(html, "html.parser")
    papers: list[Paper] = []

    # Narrow scope to the matching year's accordion section if year is given.
    scope = soup
    if year is not None:
        for btn in soup.select("button.accordion"):
            if str(year) in btn.get_text():
                # The accordion-content div follows the button
                accordion_div = btn.find_next_sibling("div", class_="accordion-content")
                if accordion_div:
                    scope = accordion_div
                    break
        else:
            logger.warning("No accordion section found for ECCV %d", year)
            return []

    for dt in scope.select("dt.ptitle"):
        title_a = dt.select_one("a")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        if not title:
            continue

        # Collect up to two <dd> siblings that immediately follow this <dt>
        dds: list = []
        sib = dt.next_sibling
        while sib and len(dds) < 2:
            if hasattr(sib, "name") and sib.name == "dd":
                dds.append(sib)
            sib = sib.next_sibling

        if not dds:
            continue

        # Authors: plain comma-separated text in the first <dd>.
        # Strip trailing '*' (corresponding-author marker) from each name.
        raw_authors = dds[0].get_text(strip=True)
        authors = [
            a.rstrip("*").strip()
            for a in raw_authors.split(",")
            if a.rstrip("*").strip()
        ]

        # PDF link: first href ending with '.pdf' that is not a supplement.
        pdf_href = ""
        link_dd = dds[1] if len(dds) > 1 else dds[0]
        for a_tag in link_dd.select("a[href]"):
            href = a_tag.get("href", "")
            if href.endswith(".pdf") and "supp" not in href:
                pdf_href = href
                break

        if pdf_href:
            link = urljoin(ECVA_BASE_URL + "/", pdf_href)
        else:
            href = title_a.get("href", "")
            link = urljoin(ECVA_BASE_URL + "/", href) if href else ""

        papers.append(Paper(
            title=title,
            link=link,
            authors=authors,
            selection="main",
        ))

    logger.info("Parsed %d papers from ecva.net", len(papers))
    return papers


CVF_BASE_URL = "https://openaccess.thecvf.com"
ECVA_BASE_URL = "https://www.ecva.net"

CVF_CONFERENCES = {
    # CVF Open Access (published proceedings)
    "cvpr_2023": {"url": f"{CVF_BASE_URL}/CVPR2023?day=all", "parser": "openaccess"},
    "cvpr_2024": {"url": f"{CVF_BASE_URL}/CVPR2024?day=all", "parser": "openaccess"},
    "cvpr_2025": {"url": f"{CVF_BASE_URL}/CVPR2025?day=all", "parser": "openaccess"},
    "cvpr_2026": {"url": f"{CVF_BASE_URL}/CVPR2026?day=all", "parser": "openaccess"},
    "iccv_2023": {"url": f"{CVF_BASE_URL}/ICCV2023?day=all", "parser": "openaccess"},
    "wacv_2023": {"url": f"{CVF_BASE_URL}/WACV2023", "parser": "openaccess"},
    "wacv_2024": {"url": f"{CVF_BASE_URL}/WACV2024", "parser": "openaccess"},
    "wacv_2025": {"url": f"{CVF_BASE_URL}/WACV2025", "parser": "openaccess"},
    # CVF Accepted Papers (pre-publication)
    "iccv_2025": {"url": "https://iccv.thecvf.com/Conferences/2025/AcceptedPapers", "parser": "accepted"},
    "wacv_2026": {"url": "https://wacv.thecvf.com/Conferences/2026/AcceptedPapers", "parser": "accepted"},
    # ECVA
    "eccv_2024": {"url": f"{ECVA_BASE_URL}/papers.php", "parser": "ecva", "year": 2024},
}


def _scrape_cvf(conf_id: str) -> list[Paper]:
    """Scrape papers for a CVF/ECVA conference."""
    conf = CVF_CONFERENCES[conf_id]
    url = conf["url"]
    parser_type = conf["parser"]

    logger.info("Scraping %s from %s (parser=%s)", conf_id, url, parser_type)
    response = requests.get(url, headers=HEADERS, timeout=120)
    response.raise_for_status()

    if parser_type == "openaccess":
        papers = _parse_openaccess(response.text, CVF_BASE_URL)
    elif parser_type == "accepted":
        papers = _parse_accepted(response.text)
    elif parser_type == "ecva":
        papers = _parse_ecva(response.text, year=conf.get("year"))
    else:
        raise ValueError(f"Unknown parser type: {parser_type}")

    logger.info("Found %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_cvf, conf_id) for conf_id in CVF_CONFERENCES}
