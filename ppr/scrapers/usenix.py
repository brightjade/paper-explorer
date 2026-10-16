"""Scraper for USENIX Security conference accepted papers.

USENIX publishes accepted papers on their Drupal-based website. The
technical-sessions page lists every paper as an `article.node-paper`: the title
in `h2 a`, and a people-text block whose first <p> names the authors -- names
as plain text, each group's affiliation in an <em> -- and whose later <p>s are
notes such as "Distinguished Paper Award Winner", which the awards collector
reads (`ppr/awards/usenix_notes.py`).
Requires a browser User-Agent header to avoid 403 responses.
"""

import logging
import re
from functools import partial

import requests
from bs4 import BeautifulSoup, NavigableString

from ppr.models import Paper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

USENIX_CONFERENCES = {
    "usenix_security_2023": "usenixsecurity23",
    "usenix_security_2024": "usenixsecurity24",
    "usenix_security_2025": "usenixsecurity25",
    "usenix_security_2026": "usenixsecurity26",
}

# Names are split on commas and the word "and" ("A, B, and C"); \b keeps
# "Alexandra" and "Ferdinand" whole.
_NAME_SEPARATOR = re.compile(r",|\band\b")


def sessions_url(conf_id: str) -> str:
    return f"https://www.usenix.org/conference/{USENIX_CONFERENCES[conf_id]}/technical-sessions"


def _authors(p) -> list[str]:
    """Names are the text outside <em>; affiliations are inside it.

    Reading the block as one string lost every author but the first of a group
    sharing an affiliation and took ';'-separated affiliations for names. A <p>
    with no <em> is not an author line (the 2026 Test-of-Time panel's
    "Originally presented at ...").
    """
    if p is None or p.find("em") is None:
        return []
    text = "".join(c for c in p.children if isinstance(c, NavigableString))
    return [name for name in (" ".join(part.split()) for part in _NAME_SEPARATOR.split(text)) if name]


def parse_sessions(markup: str | bytes) -> list[dict]:
    """One {"title", "link", "authors", "notes"} per paper article on the page."""
    soup = BeautifulSoup(markup, "html.parser")
    rows = []
    for article in soup.select("article.node-paper"):
        link_tag = article.select_one("h2 a")
        title = link_tag.get_text(strip=True) if link_tag else ""
        if not title:
            continue
        href = link_tag.get("href", "")
        if href and not href.startswith("http"):
            href = f"https://www.usenix.org{href}"
        people = article.select(".field-name-field-paper-people-text p")
        rows.append({
            "title": title,
            "link": href,
            "authors": _authors(people[0] if people else None),
            "notes": [" ".join(p.get_text(" ").split()) for p in people[1:]],
        })
    return rows


def _scrape_usenix(conf_id: str) -> list[Paper]:
    """Scrape all accepted papers from a USENIX Security technical-sessions page."""
    url = sessions_url(conf_id)
    logger.info("Scraping %s from %s", conf_id, url)
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    papers = [Paper(title=r["title"], link=r["link"], authors=r["authors"], selection="main")
              for r in parse_sessions(response.content)]
    logger.info("Found %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_usenix, conf_id) for conf_id in USENIX_CONFERENCES}
