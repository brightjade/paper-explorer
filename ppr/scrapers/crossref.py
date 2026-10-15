"""ICRA and IROS from Crossref, by exact proceedings title.

IEEE deposits every ICRA and IROS paper with Crossref under one container
title per year ("2026 IEEE International Conference on Robotics and Automation
(ICRA)"), and the deposit lands when IEEE Xplore publishes -- ICRA 2026 had
1,882 records in October 2026, four months after the conference and before
DBLP had any. The scope is the proceedings, the same as DBLP's toc for
2023-2025 (ICRA 2025: 1,604 papers both ways once front matter is dropped);
RA-L journal papers presented at the conference are not in it.

No `mailto`: Crossref's polite pool wants a contact address, and this project
does not send the user's to a third party. The public pool is paced instead.
"""

import html
import logging
import re
import time
from functools import partial

import requests

from ppr.models import Paper
from ppr.net import PROJECT_USER_AGENT, parse_retry_after

logger = logging.getLogger(__name__)

API_URL = "https://api.crossref.org/works"
HEADERS = {"User-Agent": PROJECT_USER_AGENT}
MIN_INTERVAL = 1.0
MAX_RETRIES = 5
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
TIMEOUT = 60
ROWS = 1000

_MARKUP = re.compile(r"<[^>]+>")
_last_request = 0.0

CROSSREF_CONFERENCES = {
}


class CrossrefUnavailable(Exception):
    """Crossref did not answer, or answered with fewer records than it counted."""


def work_filter(prefix: str, container: str) -> str:
    if "," in container:
        raise ValueError(
            f"container title {container!r} contains a comma, which Crossref's "
            "comma-separated filter list cannot express"
        )
    return f"prefix:{prefix},type:proceedings-article,container-title:{container}"


def _get(params: dict) -> dict:
    """One paced, retried Crossref request; returns its `message`."""
    global _last_request
    last_failure = ""
    for attempt in range(MAX_RETRIES):
        elapsed = time.monotonic() - _last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_request = time.monotonic()
        try:
            response = requests.get(API_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_failure = type(exc).__name__
            time.sleep(2**attempt)
            continue
        if response.status_code in RETRYABLE_STATUSES:
            last_failure = f"HTTP {response.status_code}"
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            time.sleep(retry_after if retry_after is not None else 2**attempt)
            continue
        if response.status_code != 200:
            raise CrossrefUnavailable(f"HTTP {response.status_code}")
        try:
            return response.json()["message"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CrossrefUnavailable("unparseable response") from exc
    raise CrossrefUnavailable(f"{last_failure} after {MAX_RETRIES} attempts")


def count(prefix: str, container: str) -> int:
    """How many records Crossref holds for this proceedings title."""
    message = _get({"filter": work_filter(prefix, container), "rows": 0})
    return int(message["total-results"])


def fetch_items(prefix: str, container: str) -> list[dict]:
    """Every record for this proceedings title, by deep-paging cursor."""
    items: list[dict] = []
    cursor = "*"
    total = 0
    while True:
        message = _get({"filter": work_filter(prefix, container), "rows": ROWS,
                        "cursor": cursor, "select": "DOI,title,author"})
        batch = message.get("items") or []
        total = int(message["total-results"])
        items.extend(batch)
        if not batch or len(items) >= total:
            break
        cursor = message["next-cursor"]
    if len(items) != total:
        raise CrossrefUnavailable(f"cursor ended at {len(items)} of {total} records")
    return items


def clean_title(raw: str) -> str:
    """Plain text: tags removed first (so an escaped `&lt;` is never read as a
    tag), then entities, then whitespace collapsed. Tags are removed outright,
    not replaced by a space: `(PDM<sup>2</sup>)` is `(PDM2)`."""
    return " ".join(html.unescape(_MARKUP.sub("", raw)).split())


def _author(entry: dict) -> str:
    name = " ".join(part for part in (entry.get("given", ""), entry.get("family", "")) if part)
    return " ".join((name or entry.get("name", "")).split())


def parse_items(items: list[dict]) -> list[Paper]:
    """Crossref works to papers, front matter dropped.

    Front matter ("Conference Information", "Program", "Welcome", "Table of
    Contents", "Top Menu", the author index) is deposited as a
    proceedings-article too, and is exactly the set of items with no author.
    """
    papers: list[Paper] = []
    for item in items:
        authors = [a for a in (_author(e) for e in item.get("author") or []) if a]
        title = clean_title((item.get("title") or [""])[0])
        if not authors or not title:
            continue
        papers.append(Paper(title=title, link=f"https://doi.org/{item['DOI']}",
                            authors=authors, selection="main"))
    return papers


def _scrape_crossref(conf_id: str) -> list[Paper]:
    conf = CROSSREF_CONFERENCES[conf_id]
    papers = parse_items(fetch_items(conf["prefix"], conf["container"]))
    logger.info("Scraped %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_crossref, conf_id) for conf_id in CROSSREF_CONFERENCES}
