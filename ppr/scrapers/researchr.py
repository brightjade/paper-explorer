"""SE conferences (ICSE, FSE, ASE, ISSTA) from their conf.researchr.org research tracks.

All four venues run their programs on researchr, which lists a track's
accepted papers once acceptances go out -- months before DBLP indexes the
proceedings (on 2026-10-14 researchr had ICSE, ASE and ISSTA 2026; DBLP had
none of them). Only the research track is collected: it is each venue's main
paper track, and DBLP's tocs mix in NIER, tool-demo and industry papers for
some venues but not others (ASE 2025: 389 on DBLP, 246 research papers).

researchr decides *which* papers are in the track. For years DBLP has indexed,
an entry's `dblp` key supplies each matched paper's *record* -- DBLP's title,
authors and DOI -- so re-crawled rows equal the ones already in `data/` and keep
their enrichment. Track pages are plain paths: researchr's robots.txt
disallows `/*?` and asks for `Crawl-delay: 2`.
"""

import logging
import re
import time
from functools import partial

import requests
from bs4 import BeautifulSoup

from ppr import dblp_client
from ppr.matching import title_key
from ppr.models import Paper
from ppr.net import PROJECT_USER_AGENT

logger = logging.getLogger(__name__)

BASE_URL = "https://conf.researchr.org"
HEADERS = {"User-Agent": PROJECT_USER_AGENT}
MIN_INTERVAL = 2.0
TIMEOUT = 60

# Below this share of research-track papers found on DBLP, the entry's `dblp`
# key is wrong (another venue's toc, a renamed volume), not merely behind.
# Measured 2026-10-14: 95-100% on all twelve 2023-2025 venue-years.
MIN_DBLP_JOIN = 0.8

# FSE 2023 prefixes remote talks' titles with "[Remote] ".
_SESSION_TAG = re.compile(r"^\[[^\]]{1,20}\]\s*")

_last_request = 0.0

RESEARCHR_CONFERENCES = {
    # ICSE
    "icse_2023": {"url": "https://conf.researchr.org/track/icse-2023/icse-2023-technical-track", "track": "Technical Track", "dblp": {"key": "db/conf/icse/icse2023.bht"}},
    "icse_2024": {"url": "https://conf.researchr.org/track/icse-2024/icse-2024-research-track", "track": "Research Track", "dblp": {"key": "db/conf/icse/icse2024.bht"}},
    "icse_2025": {"url": "https://conf.researchr.org/track/icse-2025/icse-2025-research-track", "track": "Research Track", "dblp": {"key": "db/conf/icse/icse2025.bht"}},
    # FSE (PACMSE from 2024; pacmse2 is shared with ISSTA 2025)
    "fse_2023": {"url": "https://conf.researchr.org/track/fse-2023/fse-2023-research-papers", "track": "Research Papers", "dblp": {"key": "db/conf/sigsoft/fse2023.bht"}},
    "fse_2024": {"url": "https://conf.researchr.org/track/fse-2024/fse-2024-research-papers", "track": "Research Papers", "dblp": {"key": "db/journals/pacmse/pacmse1.bht"}},
    "fse_2025": {"url": "https://conf.researchr.org/track/fse-2025/fse-2025-research-papers", "track": "Research Papers", "dblp": {"key": "db/journals/pacmse/pacmse2.bht", "number": "FSE"}},
    "fse_2026": {"url": "https://conf.researchr.org/track/fse-2026/fse-2026-research-papers", "track": "Research Papers"},
    # ASE (DBLP's key prefix is 'kbse')
    "ase_2023": {"url": "https://conf.researchr.org/track/ase-2023/ase-2023-papers", "track": "Research Papers", "dblp": {"key": "db/conf/kbse/ase2023.bht"}},
    "ase_2024": {"url": "https://conf.researchr.org/track/ase-2024/ase-2024-research", "track": "Research Papers", "dblp": {"key": "db/conf/kbse/ase2024.bht"}},
    "ase_2025": {"url": "https://conf.researchr.org/track/ase-2025/ase-2025-papers", "track": "Research Papers", "dblp": {"key": "db/conf/kbse/ase2025.bht"}},
    "ase_2026": {"url": "https://conf.researchr.org/track/ase-2026/ase-2026-research-track", "track": "Research Papers"},
    # ISSTA (PACMSE from 2025)
    "issta_2023": {"url": "https://conf.researchr.org/track/issta-2023/issta-2023-technical-papers", "track": "Technical Papers", "dblp": {"key": "db/conf/issta/issta2023.bht"}},
    "issta_2024": {"url": "https://conf.researchr.org/track/issta-2024/issta-2024-papers", "track": "Technical Papers", "dblp": {"key": "db/conf/issta/issta2024.bht"}},
    "issta_2025": {"url": "https://conf.researchr.org/track/issta-2025/issta-2025-papers", "track": "Research Papers", "dblp": {"key": "db/journals/pacmse/pacmse2.bht", "number": "ISSTA"}},
}


def track_url(conf: str, year: int, slug: str) -> str:
    return f"{BASE_URL}/track/{conf}-{year}/{conf}-{year}-{slug}"


def get(url: str) -> requests.Response:
    """GET a researchr page, no sooner than the site's crawl delay after the last."""
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT)


def parse_track_page(text: str) -> tuple[str, list[dict]]:
    """The page's track name, and the Accepted Papers rows that belong to it.

    The track name is the middle of the page title ("ICSE 2025 - Research Track
    - ICSE 2025"). Rows come from `#event-overview` only -- the schedule lists
    the same papers again -- and a row whose `prog-track` names another track
    (a journal-first paper in a research session) is dropped.
    """
    soup = BeautifulSoup(text, "html.parser")
    parts = [p.strip() for p in (soup.title.get_text() if soup.title else "").split(" - ")]
    track = parts[1] if len(parts) >= 3 else ""
    overview = soup.select_one("#event-overview")
    if not track or overview is None:
        return track, []

    rows: list[dict] = []
    seen: set[str] = set()
    for anchor in overview.select("a[data-event-modal]"):
        event = anchor["data-event-modal"]
        cell = anchor.parent
        prog = cell.select_one("div.prog-track")
        if event in seen or prog is None or prog.get_text(strip=True) != track:
            continue
        seen.add(event)
        for badge in anchor.select("span.pull-right"):
            badge.decompose()
        title = _SESSION_TAG.sub("", " ".join(anchor.get_text().split()))
        performers = cell.select_one("div.performers")
        names = performers.get_text().split(",") if performers else []
        preprint = cell.select_one("a.publication-link")
        rows.append({
            "title": title,
            "authors": [" ".join(n.split()) for n in names if n.strip()],
            "link": preprint["href"] if preprint and preprint.get("href") else "",
        })
    return track, rows


def _backfill_from_dblp(conf_id: str, papers: list[Paper], dblp: dict) -> list[Paper]:
    """Swap in DBLP's record for every research-track paper DBLP has.

    Raises `DblpUnavailable` when DBLP does not answer, and `ValueError` when too
    few papers match: a crawl that promised DOIs must not quietly ship without.
    """
    records = dblp_client.toc_papers(dblp["key"], number=dblp.get("number"))
    by_key = {title_key(r["title"]): r for r in records if r["link"]}

    out: list[Paper] = []
    joined = 0
    for paper in papers:
        record = by_key.get(title_key(paper.title))
        if record is None:
            out.append(paper)
            continue
        joined += 1
        out.append(Paper(title=record["title"], link=record["link"],
                         authors=record["authors"], selection=paper.selection))

    rate = joined / len(papers) if papers else 0.0
    logger.info("%s: %d/%d research-track papers matched DBLP %s (%.0f%%)",
                conf_id, joined, len(papers), dblp["key"], rate * 100)
    if rate < MIN_DBLP_JOIN:
        raise ValueError(
            f"{conf_id}: only {joined}/{len(papers)} research-track papers matched "
            f"DBLP {dblp['key']} -- is the key right?"
        )
    return out


def _scrape_researchr(conf_id: str) -> list[Paper]:
    conf = RESEARCHR_CONFERENCES[conf_id]
    response = get(conf["url"])
    response.raise_for_status()
    track, rows = parse_track_page(response.text)
    if track != conf["track"]:
        raise ValueError(
            f"{conf_id}: {conf['url']} is the {track!r} track, registered as {conf['track']!r}"
        )
    papers = [
        Paper(title=r["title"], link=r["link"] or conf["url"], authors=r["authors"], selection="main")
        for r in rows
    ]
    if "dblp" in conf:
        papers = _backfill_from_dblp(conf_id, papers, conf["dblp"])
    logger.info("Scraped %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_researchr, conf_id) for conf_id in RESEARCHR_CONFERENCES}
