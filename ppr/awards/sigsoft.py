"""SIGSOFT's distinguished-paper list: a backfill for SE years researchr shows no badges for.

www2.sigsoft.org/awards/distinguishedpaper/ (www.sigsoft.org redirects there;
its robots.txt asks for Crawl-Delay 20) lists winners per conference under
<h3>s like "... (FSE 2025)", one <li> "Authors: Title" per paper. Titles have
colons of their own ("Mystique: Automated ..."); author lists never do, so the
split is at the first ": ". The list is curated and lags by months, so it runs
only when no earlier source found winners.

Before 2015 an entry reads "Authors, Title" instead ("A, B, and C, Title:
Subtitle"): a section is in that form when one of its entries has no ": " at
all, and its titles start after the first ", " that follows the authors'
"and <name>". Every 2013-2014 entry has one (checked against the 2026-10-15 page).
"""

import re

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

SIGSOFT_URL = "https://www2.sigsoft.org/awards/distinguishedpaper/"
LABEL = "ACM SIGSOFT Distinguished Paper Award"
_VENUE = re.compile(r"\((?:ESEC/)?(ICSE|FSE|ASE|ISSTA) (\d{4})\)")
_OLD_FORM = re.compile(r"^.*?\band\s+[^,]+,\s+(.+)$")


def _titles(items: list[str]) -> list[str]:
    if any(": " not in item for item in items):
        return [m.group(1) for item in items if (m := _OLD_FORM.match(item))]
    return [title for item in items if (title := item.partition(": ")[2])]


_cache: dict[str, dict[str, list[Award]]] = {}


def parse_sigsoft(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    winners = soup.select_one("h2#winners")
    if winners is None:
        raise ValueError(f"{url}: no #winners heading -- did the page change?")
    kind = classify(LABEL)
    out: dict[str, list[Award]] = {}
    for h3 in winners.find_all_next("h3"):
        m = _VENUE.search(h3.get_text(" "))
        if not m:
            continue
        ul = h3.find_next_sibling("ul")
        if ul is None or ul.find_previous_sibling("h3") is not h3:
            continue
        conf_id = f"{m.group(1).lower()}_{m.group(2)}"
        items = [" ".join(li.get_text(" ").split()) for li in ul.find_all("li", recursive=False)]
        for title in _titles(items):
            out.setdefault(conf_id, []).append(
                Award(label=LABEL, kind=kind, title=title, via="sigsoft", source=url))
    return out


def sigsoft_backfill(conf_id: str, year: int, earlier: list[Award]) -> list[Award] | None:
    if any(a.kind == "award" for a in earlier):
        return None  # researchr or a manual file already has the winners
    if SIGSOFT_URL not in _cache:
        response = fetch.get(SIGSOFT_URL)
        response.raise_for_status()
        _cache[SIGSOFT_URL] = parse_sigsoft(response.text, SIGSOFT_URL)
    return list(_cache[SIGSOFT_URL].get(conf_id, []))
