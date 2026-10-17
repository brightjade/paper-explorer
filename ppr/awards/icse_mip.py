"""ICSE's Most Influential Paper award: icse-conferences.org/mostinfluential.html.

One table row per prize: the award year in the first cell; authors, the paper
as a link and its edition ("ICSE-35, 2013") in the second. A year can hold two
rows (2010). A prize belongs to the conference that gave it (icse_<award
year>); build_data finds the paper itself in the earlier edition. robots.txt
sets no delay; the page is fetched once per run and shared by every year.
"""

import re

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

MIP_URL = "https://icse-conferences.org/mostinfluential.html"
LABEL = "Most Influential Paper Award"
_YEAR = re.compile(r"^\d{4}$")

_cache: dict[str, dict[str, list[Award]]] = {}


def parse_mip(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    kind = classify(LABEL)
    out: dict[str, list[Award]] = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2 or not _YEAR.match(cells[0].get_text(strip=True)):
            continue
        link = cells[1].find("a")
        title = " ".join(link.get_text(" ").split()) if link else ""
        if title:
            out.setdefault(f"icse_{cells[0].get_text(strip=True)}", []).append(Award(
                label=LABEL, kind=kind, title=title, via="icse_mip", source=url, url=link.get("href", "")))
    if not out:
        raise ValueError(f"{url}: no award rows -- did the page change?")
    return out


def icse_mip(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    if MIP_URL not in _cache:
        response = fetch.get(MIP_URL)
        response.raise_for_status()
        _cache[MIP_URL] = parse_mip(response.text, MIP_URL)
    return list(_cache[MIP_URL].get(conf_id, []))
