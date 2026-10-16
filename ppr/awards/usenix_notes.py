"""USENIX Security award notes on the technical-sessions page.

A paper's people-text block carries its awards as <p>s after the author line:
"Distinguished Paper Award Winner", "Distinguished Artifact Award Winner", or
one note naming two prizes ("Distinguished Paper Award Winner and Co-Winner of
the 2023 Internet Defense Prize"). Only notes naming an award are read: speaker
bios and the Test-of-Time panel's "Read the paper" share the block.
"""

import re

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award
from ppr.scrapers.usenix import parse_sessions, sessions_url

_AWARD_NOTE = re.compile(r"Award Winner|Internet Defense Prize")
_SECOND_PRIZE = re.compile(r"\s+and\s+(?=(?:Co-|Runner-Up\s+)?Winner\b)")


def split_note(note: str) -> list[str]:
    return [part.strip() for part in _SECOND_PRIZE.split(note) if part.strip()]


def note_awards(rows: list[dict], url: str) -> list[Award]:
    out: list[Award] = []
    for row in rows:
        for note in row["notes"]:
            if not _AWARD_NOTE.search(note):
                continue
            for label in split_note(note):
                kind = classify(label, "usenix_security")
                if kind is not None:
                    out.append(Award(label=label, kind=kind, title=row["title"], via="usenix", source=url))
    return out


def usenix_awards(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    url = sessions_url(conf_id)
    response = fetch.get(url)
    response.raise_for_status()
    rows = parse_sessions(response.content)
    if not rows:
        raise ValueError(f"{url}: no paper articles -- did the page change?")
    return note_awards(rows, url)
