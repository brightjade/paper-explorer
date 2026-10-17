"""ISSTA's Impact Paper and Retrospective Paper awards, on www.issta.org.

Two <h2> sections, each a <ul> of "<year>: <authors>. <a>Title</a> (published
in ISSTA <year>)". The Retrospective award ran 2018-2020 only. robots.txt sets
no delay; one fetch per run serves every year.
"""

import re

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

ISSTA_URL = "https://www.issta.org/"
SECTIONS = {
    "issta-impact-paper-awards": "Impact Paper Award",
    "issta-retrospective-paper-awards": "Retrospective Paper Award",
}
_YEAR = re.compile(r"^(\d{4}):")

_cache: dict[str, dict[str, list[Award]]] = {}


def parse_issta(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, list[Award]] = {}
    found = 0
    for section_id, label in SECTIONS.items():
        h2 = soup.find("h2", id=section_id)
        ul = h2.find_next_sibling("ul") if h2 else None
        if ul is None:
            continue
        found += 1
        for li in ul.find_all("li", recursive=False):
            m = _YEAR.match(li.get_text(strip=True))
            link = li.find("a")
            title = " ".join(link.get_text(" ").split()) if link else ""
            if m and title:
                out.setdefault(f"issta_{m.group(1)}", []).append(Award(
                    label=label, kind=classify(label), title=title, via="issta_impact", source=url,
                    url=link.get("href", "")))
    if not found:
        raise ValueError(f"{url}: no impact or retrospective section -- did the page change?")
    return out


def issta_impact(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    if ISSTA_URL not in _cache:
        response = fetch.get(ISSTA_URL)
        response.raise_for_status()
        _cache[ISSTA_URL] = parse_issta(response.text, ISSTA_URL)
    return list(_cache[ISSTA_URL].get(conf_id, []))
