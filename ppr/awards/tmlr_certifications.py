"""TMLR certifications as awards: Outstanding -> award, Featured -> honorable mention.

A paper carries a `certifications` list on its OpenReview note. Unlike the other
venues' awards this is read live from OpenReview every month, not from the crawl:
Outstanding is awarded after publication, and past years are not recrawled, so
papers.jsonl can be stale. A paper's year is its publication (`pdate`) year, the
same one the `tmlr_<year>` ids use. A paper with several certifications gets one
entry, of its highest kind.
"""

import functools
from typing import Iterable

from ppr.api_client import create_openreview_client, note_pdate
from ppr.awards.labels import KIND_ORDER, classify
from ppr.awards.model import Award

SOURCE_URL = "https://openreview.net/group?id=TMLR"


def certification_awards(notes: Iterable, year: int) -> list[Award]:
    out: list[Award] = []
    for note in notes:
        published = note_pdate(note)
        if published is None or published.year != year:
            continue
        labels = (note.content.get("certifications") or {}).get("value") or []
        ranked = [(KIND_ORDER[kind], label, kind) for label in labels
                  if (kind := classify(label, "tmlr")) is not None]
        if not ranked:
            continue
        _, label, kind = min(ranked, key=lambda r: r[0])
        out.append(Award(label=label, kind=kind, title=note.content["title"]["value"],
                         via="tmlr", source=SOURCE_URL, forum_id=note.forum))
    return out


@functools.cache
def _accepted_notes() -> list:
    """Every published TMLR paper; cached so one login and one fetch serve every year in a run."""
    notes = create_openreview_client().get_all_notes(
        invitation="TMLR/-/Submission", content={"venueid": "TMLR"})
    if not notes:
        raise ValueError("OpenReview returned no accepted TMLR papers")
    return notes


def tmlr_certifications(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    return certification_awards(_accepted_notes(), year)
