"""RSS from roboticsproceedings.org, the conference's own proceedings site.

Every volume lives at `/rss{NN}/index.html` in the same static table: a
`pNNN.html` link per paper with the authors in an `<i>` beneath it. The volume
is the edition (2026 is XXII, `rss22`), and each paper's DOI is
`10.15607/RSS.<year>.<ROMAN>.<NNN>` -- checked against volumes 19-22 -- so one
request per volume yields DOI links without fetching paper pages.
"""

import logging
import re
from functools import partial

import requests
from bs4 import BeautifulSoup

from ppr.models import Paper
from ppr.net import PROJECT_USER_AGENT

logger = logging.getLogger(__name__)

BASE_URL = "https://roboticsproceedings.org"
HEADERS = {"User-Agent": PROJECT_USER_AGENT}
TIMEOUT = 60
DOI_PREFIX = "10.15607/RSS"

_PAPER_PAGE = re.compile(r"p(\d{3})\.html")
_NUMERALS = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))

ROBOTICSPROCEEDINGS_CONFERENCES = {
    "rss_2023": {"volume": 19},
    "rss_2024": {"volume": 20},
    "rss_2025": {"volume": 21},
    "rss_2026": {"volume": 22},
}


def index_url(volume: int) -> str:
    return f"{BASE_URL}/rss{volume:02d}/index.html"


def roman(n: int) -> str:
    out = ""
    for value, numeral in _NUMERALS:
        while n >= value:
            out += numeral
            n -= value
    return out


def _is_paper_link(href) -> bool:
    return bool(href) and _PAPER_PAGE.fullmatch(href) is not None


def parse_index(text: str, year: int, volume: int) -> list[Paper]:
    """Every paper in a volume's table of contents."""
    soup = BeautifulSoup(text, "html.parser")
    papers: list[Paper] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=_is_paper_link):
        number = _PAPER_PAGE.fullmatch(anchor["href"]).group(1)
        if number in seen:
            continue
        seen.add(number)
        italic = anchor.find_next("i")
        # The <i> must sit under *this* paper's link, not the next row's.
        if italic is not None and italic.find_previous("a", href=_is_paper_link) is not anchor:
            italic = None
        names = italic.get_text().split(",") if italic is not None else []
        papers.append(Paper(
            title=" ".join(anchor.get_text().split()),
            link=f"https://doi.org/{DOI_PREFIX}.{year}.{roman(volume)}.{number}",
            authors=[" ".join(n.split()) for n in names if n.strip()],
            selection="main",
        ))
    return papers


def _scrape_roboticsproceedings(conf_id: str) -> list[Paper]:
    year = int(conf_id.rsplit("_", 1)[1])
    volume = ROBOTICSPROCEEDINGS_CONFERENCES[conf_id]["volume"]
    response = requests.get(index_url(volume), headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    papers = parse_index(response.text, year, volume)
    logger.info("Scraped %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {
    conf_id: partial(_scrape_roboticsproceedings, conf_id)
    for conf_id in ROBOTICSPROCEEDINGS_CONFERENCES
}
