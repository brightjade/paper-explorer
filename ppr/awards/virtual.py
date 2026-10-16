"""Conference "virtual sites": NeurIPS/ICML/ICLR/ECCV awards_detail, CVPR award candidates.

awards_detail has one table row per award: the label in the first cell, one
`div.displaycards` per paper in the second. Cards come in two markups -- the
classic one with classes, and a 2025 redesign with inline styles and none --
sometimes on one page, so each card is read on its own. The cookie banner is a
two-cell table too; rows without cards are skipped. An empty page is still a
200 (ICLR never filled in 2025's or 2026's), so an empty result means "nothing
published here", not a failure. robots.txt disallows /static and ?page= URLs;
neither is ever requested.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

HOSTS = {
    "neurips": "https://neurips.cc",
    "icml": "https://icml.cc",
    "iclr": "https://iclr.cc",
    "eccv": "https://eccv.ecva.net",
}

_EVENT_HREF = re.compile(r"^/virtual/\d{4}/")
# NeurIPS 2023 titles its test-of-time card "Test of Time Award Talk:<paper>".
_TALK_PREFIX = re.compile(r"^test of time award talk:\s*", re.I)
# NeurIPS 2025 titles it just "Test of Time Award"; the paper is a markdown link in the abstract.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_TOT_SUFFIX = re.compile(r"\s*\(test of time award\)\s*$", re.I)
_GENERIC_TOT = {"test of time award", "test of time"}


def _text(el) -> str:
    return " ".join(el.get_text(" ").split())


def _test_of_time(card, title: str, href: str, page_url: str) -> tuple[str, str]:
    """The paper a test-of-time card is for, and the link to show with it."""
    title = _TALK_PREFIX.sub("", title)
    if title.lower() in _GENERIC_TOT:
        details = card.find("details")
        m = _MD_LINK.search(details.get_text(" ")) if details else None
        if m:
            return _TOT_SUFFIX.sub("", " ".join(m.group(1).split())), m.group(2)
    return title, (urljoin(page_url, href) if href else "")


def parse_awards_detail(html: str, url: str, prefix: str) -> list[Award]:
    soup = BeautifulSoup(html, "html.parser")
    awards: list[Award] = []
    for tr in soup.select("table tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        cards = cells[1].select("div.displaycards")
        if not cards:
            continue
        label = _text(cells[0])
        kind = classify(label, prefix)
        if kind is None:
            continue
        for card in cards:
            link = card.select_one("a.small-title") or card.find("a", href=_EVENT_HREF)
            if link is None:
                continue
            title, extra = _text(link), ""
            if kind == "test_of_time":
                title, extra = _test_of_time(card, title, link.get("href", ""), url)
            if title:
                awards.append(Award(label=label, kind=kind, title=title, via="virtual",
                                    source=url, url=extra))
    return awards


def parse_award_candidates(html: str, url: str) -> list[Award]:
    soup = BeautifulSoup(html, "html.parser")
    return [Award(label="Award Candidate", kind="candidate", title=_text(a), via="virtual", source=url)
            for a in soup.select("div.event-card h3.event-title a")]


def _text_or_none(url: str) -> str | None:
    """The page's text, or None when it does not exist (yet)."""
    response = fetch.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def awards_detail(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    prefix = conf_id.rsplit("_", 1)[0]
    url = f"{HOSTS[prefix]}/virtual/{year}/awards_detail"
    html = _text_or_none(url)
    return parse_awards_detail(html, url, prefix) if html else []


def cvpr_candidates(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    url = f"https://cvpr.thecvf.com/virtual/{year}/events/AwardCandidates{year}"
    html = _text_or_none(url)
    return parse_award_candidates(html, url) if html else []
