"""SE award badges on conf.researchr.org research-track pages.

researchr puts a paper's awards in the same badge spans as artifact-evaluation
badges, topic tags and attendance notes. So, unlike every other source, a badge
no rule knows is not a reason to hold the conference: only badges that name an
award are kept, and the rest are logged at debug level.
"""

import logging

from ppr.awards import fetch
from ppr.awards.labels import UnknownAwardLabel, classify
from ppr.awards.model import Award
from ppr.scrapers.researchr import RESEARCHR_CONFERENCES, parse_track_page

logger = logging.getLogger(__name__)


def badge_awards(rows: list[dict], prefix: str, url: str) -> list[Award]:
    out: list[Award] = []
    for row in rows:
        for badge in row["badges"]:
            try:
                kind = classify(badge, prefix)
            except UnknownAwardLabel:
                logger.debug("%s: badge %r is not an award", url, badge)
                continue
            if kind is not None:
                out.append(Award(label=badge, kind=kind, title=row["title"], via="researchr", source=url))
    return out


def researchr_badges(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    conf = RESEARCHR_CONFERENCES.get(conf_id)
    if conf is None:
        return []
    response = fetch.get(conf["url"])
    response.raise_for_status()
    track, rows = parse_track_page(response.text)
    if track != conf["track"]:
        raise ValueError(f"{conf_id}: {conf['url']} is the {track!r} track, registered as {conf['track']!r}")
    return badge_awards(rows, conf_id.rsplit("_", 1)[0], conf["url"])
