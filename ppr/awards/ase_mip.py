"""ASE's Most Influential Paper award: www.ase-conferences.org/most-influential-papers.

Each prize year is an <h3> "ASE <year> MIP:" followed by one <p> per paper:
"<strong>ASE 2016</strong> - <title> - <authors><br/>DOI <a>". Titles can hold
" - " of their own; author lists never do, so the title ends at the last one.
robots.txt sets no delay; one fetch per run serves every year.
"""

import re

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

MIP_URL = "https://www.ase-conferences.org/most-influential-papers"
LABEL = "Most Influential Paper Award"
_HEADING = re.compile(r"^ASE (\d{4}) MIP:?$")
_EDITION = re.compile(r"^ASE \d{4}\s*-\s*")

_cache: dict[str, dict[str, list[Award]]] = {}


def _title(p) -> str:
    head = []
    for child in p.children:
        if getattr(child, "name", None) == "br":
            break
        head.append(child.get_text(" ") if hasattr(child, "get_text") else str(child))
    text = " ".join(" ".join(head).split())
    if not _EDITION.match(text):
        return ""  # a paragraph of prose, not an entry
    title, sep, _authors = _EDITION.sub("", text).rpartition(" - ")
    return title.strip() if sep else ""


def parse_mip(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    kind = classify(LABEL)
    out: dict[str, list[Award]] = {}
    headings = 0
    for h3 in soup.find_all("h3"):
        m = _HEADING.match(" ".join(h3.get_text(" ").split()))
        if not m:
            continue
        headings += 1
        el = h3.find_next_sibling()
        while el is not None and el.name != "h3":
            if el.name == "p" and (title := _title(el)):
                link = el.find("a")
                out.setdefault(f"ase_{m.group(1)}", []).append(Award(
                    label=LABEL, kind=kind, title=title, via="ase_mip", source=url,
                    url=link.get("href", "") if link else ""))
            el = el.find_next_sibling()
    if not headings:
        raise ValueError(f"{url}: no 'ASE <year> MIP' headings -- did the page change?")
    return out


def ase_mip(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    if MIP_URL not in _cache:
        response = fetch.get(MIP_URL)
        response.raise_for_status()
        _cache[MIP_URL] = parse_mip(response.text, MIP_URL)
    return list(_cache[MIP_URL].get(conf_id, []))
