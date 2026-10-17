"""USENIX Test of Time Awards: www.usenix.org/conferences/test-of-time-awards.

One page for every USENIX conference: an <h2> per year, an <h3> per
conference ("USENIX Security '24"), then one <div class="test"> per paper with
the title linked in p.title. Only USENIX Security entries are read, keyed by
the <h3>'s own year. Fetched once per run, with the browser UA and 10s delay
fetch.get uses for www.usenix.org.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

TOT_URL = "https://www.usenix.org/conferences/test-of-time-awards"
LABEL = "Test of Time Award"
_SECURITY = re.compile(r"^USENIX Security ['’](\d{2})$")

_cache: dict[str, dict[str, list[Award]]] = {}


def parse_tot(html: str, url: str) -> dict[str, list[Award]]:
    soup = BeautifulSoup(html, "html.parser")
    kind = classify(LABEL)
    out: dict[str, list[Award]] = {}
    for h3 in soup.find_all("h3"):
        m = _SECURITY.match(" ".join(h3.get_text(" ").split()))
        if not m:
            continue
        conf_id = f"usenix_security_{2000 + int(m.group(1))}"
        el = h3.find_next_sibling()
        while el is not None and el.name not in ("h2", "h3"):
            link = el.select_one("p.title a") if el.name == "div" and "test" in (el.get("class") or []) else None
            title = " ".join(link.get_text(" ").split()) if link else ""
            if title:
                out.setdefault(conf_id, []).append(Award(
                    label=LABEL, kind=kind, title=title, via="usenix_tot", source=url,
                    url=urljoin("https://www.usenix.org", link.get("href", ""))))
            el = el.find_next_sibling()
    if not out:
        raise ValueError(f"{url}: no USENIX Security entries -- did the page change?")
    return out


def usenix_tot(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    if TOT_URL not in _cache:
        response = fetch.get(TOT_URL)
        response.raise_for_status()
        _cache[TOT_URL] = parse_tot(response.text, TOT_URL)
    return list(_cache[TOT_URL].get(conf_id, []))
