"""Scraper for IJCAI accepted papers from the conference website.

IJCAI 2023-2025 are sourced from DBLP (see ppr/scrapers/dblp.py), but the
IJCAI 2026 proceedings are not yet indexed on DBLP. The 2026 site lists every
accepted paper as an <li class="ij-paper"> entry carrying title, authors,
abstract, and topic keywords -- richer than DBLP -- so 2026 uses this dedicated
scraper. The split is by year: 2026 comes from this scraper (the conference
site), 2023-2025 from ppr/scrapers/dblp.py via DBLP.
"""

import logging
from functools import partial

import requests
from bs4 import BeautifulSoup

from ppr.models import Paper

logger = logging.getLogger(__name__)

# The IJCAI site rejects the default python-requests User-Agent, so present a
# browser UA (same precaution as the USENIX scraper).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

IJCAI_CONFERENCES = {
    "ijcai_2026": {"url": "https://2026.ijcai.org/accepted-papers/"},
}


def _parse_ijcai(html: str) -> list[Paper]:
    """Parse papers from the IJCAI 2026 accepted-papers page.

    Each paper is an <li class="ij-paper"> with:
      - <h3 class="ij-ptitle"> title
      - <div class="ij-authors"> containing <span class="ij-author"> names
        (separated by <span class="ij-sep">, which is excluded)
      - <details class="ij-abs"><div class="ij-abstract"> abstract (optional)
      - <div class="ij-keywords"> with <span class="ij-kw" title="Area -> Topic">
        elements; the hierarchical label lives in the title attribute (optional)

    An optional <div class="ij-oslink"> holds an author-supplied code link, not
    the paper itself, so it is ignored and `link` is left empty (no canonical
    paper URL exists pre-publication; enrichment matches by title).
    """
    soup = BeautifulSoup(html, "html.parser")
    papers = []
    for li in soup.find_all("li", class_="ij-paper"):
        title_tag = li.find("h3", class_="ij-ptitle")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title:
            continue

        authors_div = li.find("div", class_="ij-authors")
        authors = []
        if authors_div:
            authors = [
                span.get_text(strip=True)
                for span in authors_div.find_all("span", class_="ij-author")
                if span.get_text(strip=True)
            ]

        abstract_tag = li.find("div", class_="ij-abstract")
        abstract = abstract_tag.get_text(strip=True) if abstract_tag else ""

        keywords = []
        kw_div = li.find("div", class_="ij-keywords")
        if kw_div:
            for kw in kw_div.find_all("span", class_="ij-kw"):
                label = kw.get("title") or kw.get_text(strip=True)
                if label:
                    keywords.append(label.strip())

        papers.append(Paper(
            title=title,
            link="",
            authors=authors,
            selection="main",
            abstract=abstract,
            keywords=keywords,
        ))

    return papers


def _scrape_ijcai(conf_id: str) -> list[Paper]:
    """Scrape papers for an IJCAI conference served from its own website."""
    conf = IJCAI_CONFERENCES[conf_id]
    url = conf["url"]
    logger.info("Scraping %s from %s", conf_id, url)
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    papers = _parse_ijcai(response.text)
    logger.info("Found %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_ijcai, conf_id) for conf_id in IJCAI_CONFERENCES}
