"""The CVF's awards registry: one page with every CVPR, ICCV and ECCV prize.

https://www.thecvf.com/?page_id=413 (robots.txt: Crawl-delay 10) lists each
prize under an <h1>, with a table of year / "title" / authors rows. It is the
only machine-readable source for CVPR 2024 and 2026 and for ICCV's winners,
and it carries the three test-of-time prizes: Longuet-Higgins (CVPR),
Helmholtz (ICCV) and Koenderink (ECCV). It is fetched once per run and shared
by all three venues. Only 2024 marks student honorable mentions
("(Student Paper)"); the other years' show as plain honorable mentions.
"""

import re

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import UnknownAwardLabel, classify
from ppr.awards.model import Award

REGISTRY_URL = "https://www.thecvf.com/?page_id=413"

# <h1> text -> (venue prefix, the label the site shows)
SECTIONS = {
    "Longuet-Higgins Prize": ("cvpr", "Longuet-Higgins Prize"),
    "Helmholtz Prize": ("iccv", "Helmholtz Prize"),
    "Koenderink Prize": ("eccv", "Koenderink Prize"),
    "CVPR Best Paper Award": ("cvpr", "Best Paper"),
    "CVPR Best Student Paper Award": ("cvpr", "Best Student Paper"),
    "CVPR Best Paper Honorable Mention Award": ("cvpr", "Best Paper Honorable Mention"),
    "ICCV Best Paper Award (Marr Prize)": ("iccv", "Best Paper (Marr Prize)"),
    "ICCV Best Student Paper Award": ("iccv", "Best Student Paper"),
    "ICCV Best Paper Honorable Mention Award": ("iccv", "Best Paper Honorable Mention"),
    "ECCV Best Paper Award": ("eccv", "Best Paper"),
    "ECCV Best Paper Honorable Mention Award": ("eccv", "Best Paper Honorable Mention"),
}
# A section for one of our venues that SECTIONS does not know is a new prize: hold, don't guess.
_OUR_VENUES = re.compile(r"^(CVPR|ICCV|ECCV)\b")
_YEAR = re.compile(r"^\d{4}$")
_QUOTED = re.compile(r"^[“\"](.*?)[”\"]\s*(?:\((.*?)\))?\s*$")

_cache: dict[str, dict[str, list[Award]]] = {}


def parse_registry(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, list[Award]] = {}
    known = 0
    for h1 in soup.find_all("h1"):
        name = " ".join(h1.get_text(" ").split())
        if name not in SECTIONS:
            if _OUR_VENUES.match(name):
                raise UnknownAwardLabel(f"CVF registry has a section we do not know: {name!r}")
            continue
        known += 1
        prefix, label = SECTIONS[name]
        table = h1.find_next("table")
        if table is None or table.find_previous("h1") is not h1:
            continue
        for tr in table.find_all("tr"):
            cells = [" ".join(td.get_text(" ").split()) for td in tr.find_all("td")]
            if len(cells) < 2 or not _YEAR.match(cells[0]):
                continue
            m = _QUOTED.match(cells[1])
            title, note = (m.group(1).strip(), m.group(2)) if m else (cells[1], None)
            row_label = label
            if note and note.lower() == "student paper" and label == "Best Paper Honorable Mention":
                row_label = "Best Student Paper Honorable Mention"
            out.setdefault(f"{prefix}_{cells[0]}", []).append(Award(
                label=row_label, kind=classify(row_label, prefix), title=title,
                via="cvf_registry", source=url))
    if not known:
        raise ValueError(f"{url}: none of the known award sections -- did the page change?")
    return out


def cvf_registry(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    if REGISTRY_URL not in _cache:
        response = fetch.get(REGISTRY_URL)
        response.raise_for_status()
        _cache[REGISTRY_URL] = parse_registry(response.text, REGISTRY_URL)
    return list(_cache[REGISTRY_URL].get(conf_id, []))
