"""USENIX Security award notes on the technical-sessions page.

A paper's people-text block carries its awards: "Distinguished Paper Award
Winner", "Awarded Best Paper!" (2013-16), "Facebook Internet Defense Prize
Winner!", or one note naming two prizes ("Distinguished Paper Award Winner and
First Prize winner of the 2020 Internet Defense Prize"). Only notes naming an
award are read; "Note: ..." lines (2020: co-authors declining the prize),
speaker bios and the Test-of-Time panel's "Read the paper" are not.

The URL is built from the year, not from the crawler's registry: 2013-2022 are
crawled from DBLP, and only their award notes are read here.
"""

import re

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award
from ppr.scrapers.usenix import parse_sessions

SESSIONS_URL = "https://www.usenix.org/conference/usenixsecurity{yy:02d}/technical-sessions"

_AWARD_NOTE = re.compile(r"Award Winner|Internet Defense Prize|Awarded Best")
_SECOND_PRIZE = re.compile(
    r"\s+and\s+(?=(?:Co-|Runner-Up\s+|(?:First|Second|Third)\s+Prize\s+)?[Ww]inner\b)")
_NOT_AN_AWARD = re.compile(r"^Note:")


def sessions_url(year: int) -> str:
    return SESSIONS_URL.format(yy=year % 100)


def _label(part: str) -> str:
    part = part.strip().rstrip("!").strip()
    return part[:1].upper() + part[1:]


def split_note(note: str) -> list[str]:
    return [_label(part) for part in _SECOND_PRIZE.split(note) if part.strip()]


def note_awards(rows: list[dict], url: str) -> list[Award]:
    out: list[Award] = []
    for row in rows:
        for note in row["notes"]:
            if not _AWARD_NOTE.search(note) or _NOT_AN_AWARD.match(note):
                continue
            for label in split_note(note):
                kind = classify(label, "usenix_security")
                if kind is not None:
                    out.append(Award(label=label, kind=kind, title=row["title"], via="usenix", source=url))
    return out


def usenix_awards(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    url = sessions_url(year)
    response = fetch.get(url)
    response.raise_for_status()
    rows = parse_sessions(response.content)
    if not rows:
        raise ValueError(f"{url}: no paper articles -- did the page change?")
    return note_awards(rows, url)
