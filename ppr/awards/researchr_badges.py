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

# Track pages of years the crawler does not own (2013-2022 come from DBLP),
# read only for their award badges. URLs and track names are the ones the
# 2026-10-16 research fetched. FSE 2020-21 and ASE 2019 live on alias hosts of
# the researchr engine (their robots.txt sets no delay; fetch.get waits 2s).
# ICSE 2017-18, ISSTA 2018 and FSE 2018-19 show no readable badges: SIGSOFT's
# list covers them.
ARCHIVE_TRACKS = {
    "icse_2019": {"url": "https://conf.researchr.org/track/icse-2019/icse-2019-Technical-Papers",
                  "track": "Technical Track"},
    "icse_2020": {"url": "https://conf.researchr.org/track/icse-2020/icse-2020-papers", "track": "Technical Papers"},
    "icse_2021": {"url": "https://conf.researchr.org/track/icse-2021/icse-2021-papers", "track": "Technical Track"},
    "icse_2022": {"url": "https://conf.researchr.org/track/icse-2022/icse-2022-papers", "track": "Technical Track"},
    "fse_2020": {"url": "https://2020.esec-fse.org/track/fse-2020-papers", "track": "Research Papers"},
    "fse_2021": {"url": "https://2021.esec-fse.org/track/fse-2021-papers", "track": "Research Papers"},
    "fse_2022": {"url": "https://conf.researchr.org/track/fse-2022/fse-2022-research-papers",
                 "track": "Research Papers"},
    "ase_2019": {"url": "https://2019.aseconf.org/track/ase-2019-papers", "track": "Research Papers"},
    "ase_2020": {"url": "https://conf.researchr.org/track/ase-2020/ase-2020-papers", "track": "Research Papers"},
    "ase_2021": {"url": "https://conf.researchr.org/track/ase-2021/ase-2021-papers", "track": "Research Papers"},
    "ase_2022": {"url": "https://conf.researchr.org/track/ase-2022/ase-2022-research-papers",
                 "track": "Research Papers"},
    "issta_2019": {"url": "https://conf.researchr.org/track/issta-2019/issta-2019-Technical-Papers",
                   "track": "Technical Papers"},
    "issta_2020": {"url": "https://conf.researchr.org/track/issta-2020/issta-2020-papers",
                   "track": "Technical Papers"},
    "issta_2021": {"url": "https://conf.researchr.org/track/issta-2021/issta-2021-technical-papers",
                   "track": "Technical Papers"},
    "issta_2022": {"url": "https://conf.researchr.org/track/issta-2022/issta-2022-technical-papers",
                   "track": "Technical Papers"},
}


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
    conf = RESEARCHR_CONFERENCES.get(conf_id) or ARCHIVE_TRACKS.get(conf_id)
    if conf is None:
        return []
    response = fetch.get(conf["url"])
    response.raise_for_status()
    track, rows = parse_track_page(response.text)
    if track != conf["track"]:
        raise ValueError(f"{conf_id}: {conf['url']} is the {track!r} track, registered as {conf['track']!r}")
    return badge_awards(rows, conf_id.rsplit("_", 1)[0], conf["url"])
