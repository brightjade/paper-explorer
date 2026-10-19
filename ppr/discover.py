"""Find conference-years that have published a list we have not registered."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from ppr import dblp_client
from ppr.api_client import note_pdate
from ppr.archive import first_live_year
from ppr.scrapers import crossref, researchr, roboticsproceedings
from ppr.layout import crawl_config_ids
from ppr.venues import MANUAL_SOURCES, Venue

logger = logging.getLogger(__name__)

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


def known_conference_ids() -> set[str]:
    """Every conference ID the project has registered a source for.

    Derived from committed files -- OpenReview configs plus the scraper
    registry -- rather than from `data/`. A conference is known once it is
    registered, not once it happens to have been crawled, and `data/` is
    gitignored, so a CI checkout would not have it to scan.
    """
    from ppr.scrapers import SCRAPERS

    ids = set(crawl_config_ids(CONFIGS_DIR))
    return ids | set(SCRAPERS.keys())


def _matches_cadence(year: int, cadence: str) -> bool:
    if cadence == "biennial-odd":
        return year % 2 == 1
    if cadence == "biennial-even":
        return year % 2 == 0
    return True


def missing_years(
    prefix: str, cadence: str, known_ids: set[str], today_year: int
) -> list[int]:
    """Conference-years for `prefix` that could plausibly exist but are unregistered.

    Looks from the venue's earliest known year -- but never earlier than the
    first non-archive year (`ppr/archive.py`) -- through next year. The extra
    year catches a venue that publishes ahead of schedule, as OpenReview venues
    routinely do; the archive floor keeps the 2013-2022 backfill's gaps (IJCAI
    2014, NAACL 2014/2017/2020) from being probed every month. A venue with
    nothing registered yields nothing: there is no baseline to extrapolate
    from, so its first year is registered by hand.
    """
    known = {
        int(cid.rsplit("_", 1)[1])
        for cid in known_ids
        if cid.rsplit("_", 1)[0] == prefix and cid.rsplit("_", 1)[1].isdigit()
    }
    if not known:
        return []

    start = max(min(known), first_live_year(today_year))
    return [
        year
        for year in range(start, today_year + 2)
        if _matches_cadence(year, cadence) and year not in known
    ]


# A page-scraping probe must clear this to count as live. Above the 9 links
# CVPR 2026's stub page yields, far below the smallest proceedings tracked
# (ISSTA 2025's research track, 107 papers). DBLP and OpenReview report exact record counts,
# so any count above zero is real for them.
MIN_LIVE_PAPERS = 50

# Pacing, retries and the DBLP endpoint itself live in `ppr/dblp_client.py`,
# shared with `ppr/validate.py`. These headers are for the page-scraping probes
# below (CVF, ECVA, USENIX), which several of those sites require.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


@dataclass
class ProbeResult:
    conf_id: str
    prefix: str
    year: int
    status: str  # live | empty | not-yet | unreachable | needs-manual
    count: int
    url: str
    note: str = ""
    # What the probe actually matched, in the shape ppr/autoregister.py hands
    # to the registry writers. Recorded here because only the probe knows which
    # track slug matched or which parser counted the page; rebuilding that later
    # from the venue template is the guesswork registration must not do.
    registration: dict = field(default_factory=dict)


def _result(
    venue: Venue, year: int, status: str, count: int, url: str, note: str = "",
    registration: dict | None = None,
) -> ProbeResult:
    return ProbeResult(
        conf_id=f"{venue.prefix}_{year}", prefix=venue.prefix, year=year,
        status=status, count=count, url=url, note=note,
        registration=registration or {},
    )


def _classify_page(count: int) -> str:
    """A reachable page with too few papers is `empty`, never `not-yet`.

    The distinction matters: `not-yet` is the ordinary state of an unpublished
    conference, while `empty` past the venue's announce month is the signature
    of a selector the site outgrew. Collapsing them would make a redesign
    indistinguishable from a quiet month.
    """
    return "live" if count >= MIN_LIVE_PAPERS else "empty"


def _probe_cvf(venue: Venue, year: int) -> ProbeResult:
    url = venue.probe["url"].format(year=year)
    try:
        response = requests.get(url, headers=HEADERS, timeout=60)
    except requests.RequestException as exc:
        return _result(venue, year, "unreachable", 0, url, f"{type(exc).__name__}")

    if response.status_code == 404:
        return _result(venue, year, "not-yet", 0, url)
    if response.status_code != 200:
        return _result(venue, year, "unreachable", 0, url, f"HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    scope = soup

    # ECVA publishes every ECCV year on one page, so presence of the year's
    # marker decides whether it is there at all -- and the count must be
    # scoped to that year's accordion section the way ppr/scrapers/cvf.py's
    # _parse_ecva does, since the page lists every ECCV year's papers at once.
    marker = venue.probe.get("marker")
    if marker:
        if marker.format(year=year) not in response.text:
            return _result(venue, year, "not-yet", 0, url)

        scope = None
        for btn in soup.select("button.accordion"):
            if str(year) in btn.get_text():
                scope = btn.find_next_sibling("div", class_="accordion-content")
                break
        if scope is None:
            # The marker text is on the page, so the year is genuinely
            # published -- but no accordion section parsed for it. That is
            # the broken-selector signature `_classify_page` exists to catch,
            # not an unpublished conference, so this must not read as `not-yet`.
            return _result(
                venue, year, "empty", 0, url,
                "year marker present but its accordion section did not parse",
            )

    count = len(scope.select("dt.ptitle"))
    registration = (
        {"url": url, "parser": "ecva", "year": year} if marker
        else {"url": url, "parser": "openaccess"}
    )
    return _result(venue, year, _classify_page(count), count, url, registration=registration)


def _probe_usenix(venue: Venue, year: int) -> ProbeResult:
    slug = venue.probe["slug"].format(yy=f"{year % 100:02d}")
    url = f"https://www.usenix.org/conference/{slug}/technical-sessions"
    try:
        response = requests.get(url, headers=HEADERS, timeout=60)
    except requests.RequestException as exc:
        return _result(venue, year, "unreachable", 0, url, f"{type(exc).__name__}")

    if response.status_code == 404:
        return _result(venue, year, "not-yet", 0, url)
    if response.status_code != 200:
        return _result(venue, year, "unreachable", 0, url, f"HTTP {response.status_code}")

    count = len(BeautifulSoup(response.text, "html.parser").select("article.node-paper"))
    return _result(venue, year, _classify_page(count), count, url, registration={"slug": slug})


def _probe_dblp(venue: Venue, year: int) -> ProbeResult:
    """Count the year's toc page through DBLP's SPARQL endpoint."""
    key = venue.probe["toc"].format(year=year)
    url = f"https://dblp.org/db/{key.removeprefix('db/').removesuffix('.bht')}.html"
    try:
        total = dblp_client.toc_count([key])
    except dblp_client.DblpUnavailable as exc:
        return _result(venue, year, "unreachable", 0, url, str(exc))

    status = "live" if total > 0 else "not-yet"
    return _result(venue, year, status, total, url, registration={"key": key})


def _probe_openreview(venue: Venue, year: int, client) -> ProbeResult:
    venue_id = venue.probe["venue_id"].format(year=year)
    url = f"https://openreview.net/group?id={venue_id}"

    if client is None:
        return _result(
            venue, year, "unreachable", 0, url,
            "no OpenReview credentials -- venue not probed",
        )
    try:
        notes = client.get_all_notes(content={"venueid": venue_id})
    except Exception as exc:  # openreview-py raises its own exception types
        return _result(venue, year, "unreachable", 0, url, f"{type(exc).__name__}")

    if venue.rolling:
        # One venueid spans every year; a paper belongs to the year it was published.
        notes = [n for n in notes if (d := note_pdate(n)) is not None and d.year == year]

    status = "live" if notes else "not-yet"
    return _result(venue, year, status, len(notes), url, registration={"venue_id": venue_id})


def _probe_researchr(venue: Venue, year: int) -> ProbeResult:
    """Try each candidate track slug; the first page that exists decides.

    Slugs are not year-invariant (ICSE used `technical-track` in 2023 and
    `research-track` since; ASE went `papers`, `research`, `papers`,
    `research-track`), so the venue lists candidates and the probe records the
    one that matched. A 404 means "no such track" and the next slug is tried. A
    page that exists answers for the year even with no rows yet, because the
    research track's page goes up with the call for papers: that is `empty`,
    and `stale_empty` flags it if the announce month passes.
    """
    conf = venue.probe["conf"]
    url = ""
    for slug in venue.probe["track_slugs"]:
        url = researchr.track_url(conf, year, slug)
        try:
            response = researchr.get(url)
        except requests.RequestException as exc:
            return _result(venue, year, "unreachable", 0, url, type(exc).__name__)
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            return _result(venue, year, "unreachable", 0, url, f"HTTP {response.status_code}")
        track, rows = researchr.parse_track_page(response.text)
        return _result(venue, year, _classify_page(len(rows)), len(rows), url,
                       registration={"url": url, "track": track})
    return _result(venue, year, "not-yet", 0, url)


def _probe_crossref(venue: Venue, year: int) -> ProbeResult:
    """Count the records filed under the year's exact proceedings title.

    An exact count, like DBLP's: any record means IEEE has published. The count
    includes a handful of front-matter records the crawl drops, well inside
    autoregister's 10% check.
    """
    prefix = venue.probe["prefix"]
    container = venue.probe["container"].format(year=year)
    url = f"{crossref.API_URL}?filter={quote(crossref.work_filter(prefix, container), safe=':,/')}"
    try:
        total = crossref.count(prefix, container)
    except crossref.CrossrefUnavailable as exc:
        return _result(venue, year, "unreachable", 0, url, str(exc))
    status = "live" if total > 0 else "not-yet"
    return _result(venue, year, status, total, url,
                   registration={"prefix": prefix, "container": container})


def _probe_roboticsproceedings(venue: Venue, year: int) -> ProbeResult:
    """Count the papers in the year's proceedings volume (2026 is rss22)."""
    volume = year - venue.probe["volume_offset"]
    url = roboticsproceedings.index_url(volume)
    try:
        response = requests.get(url, headers=roboticsproceedings.HEADERS, timeout=60)
    except requests.RequestException as exc:
        return _result(venue, year, "unreachable", 0, url, f"{type(exc).__name__}")
    if response.status_code == 404:
        return _result(venue, year, "not-yet", 0, url)
    if response.status_code != 200:
        return _result(venue, year, "unreachable", 0, url, f"HTTP {response.status_code}")
    count = len(roboticsproceedings.parse_index(response.text, year, volume))
    return _result(venue, year, _classify_page(count), count, url,
                   registration={"volume": volume})


def probe(venue: Venue, year: int, *, openreview_client=None) -> ProbeResult:
    """Ask one source whether a conference-year's paper list is up.

    The answer is a parsed paper count, never an HTTP status code: measured on
    2026-07-29, CVPR 2026 returned 200 with a stub and zero papers while WACV
    2027 returned 404 with a 29KB body. Status-code logic gets both backwards.
    """
    if venue.source in MANUAL_SOURCES:
        url = venue.probe.get("url", "").format(year=year)
        return _result(
            venue, year, "needs-manual", 0, url,
            "registration needs a hand-written scraper",
        )
    if venue.source == "dblp":
        return _probe_dblp(venue, year)
    if venue.source == "cvf":
        return _probe_cvf(venue, year)
    if venue.source == "usenix":
        return _probe_usenix(venue, year)
    if venue.source == "researchr":
        return _probe_researchr(venue, year)
    if venue.source == "crossref":
        return _probe_crossref(venue, year)
    if venue.source == "roboticsproceedings":
        return _probe_roboticsproceedings(venue, year)
    if venue.source == "openreview":
        return _probe_openreview(venue, year, openreview_client)
    raise ValueError(f"no probe for source {venue.source!r}")


def discover(
    registry: dict[str, Venue],
    known_ids: set[str],
    today_year: int,
    *,
    openreview_client=None,
) -> list[ProbeResult]:
    """Probe every plausibly-missing conference-year across the registry."""
    results: list[ProbeResult] = []
    for prefix, venue in sorted(registry.items()):
        for year in missing_years(prefix, venue.cadence, known_ids, today_year):
            logger.info("Probing %s %s...", venue.name, year)
            try:
                results.append(probe(venue, year, openreview_client=openreview_client))
            except Exception as exc:  # one venue's crash must not cost the others their run
                logger.exception("Probe of %s %s raised", venue.name, year)
                results.append(_result(
                    venue, year, "unreachable", 0, "",
                    f"probe raised {type(exc).__name__}: {exc}",
                ))
    return results


def stale_empty(
    results: list[ProbeResult],
    registry: dict[str, Venue],
    today_month: int,
    today_year: int,
) -> list[ProbeResult]:
    """`empty` results whose announce month has passed -- probable broken selectors.

    A page that responds but yields no papers is normal before the venue
    publishes. After the month it usually publishes in, the likelier
    explanation is that the site changed and our selector no longer matches.

    The year check is not redundant with the month check. `missing_years`
    always proposes `today_year + 1`, so a month-only comparison would flag
    every next-year candidate from `announce_month + 1` onward -- a `cvpr_2027`
    stub in December 2026 satisfies `2 < 12`. That conference has not happened
    yet, so its stub is the ordinary pre-publication state, and reporting it as
    a probable broken selector would spend the credibility of the one channel
    this design depends on.
    """
    return [
        r
        for r in results
        if r.status == "empty"
        and r.year <= today_year
        and r.prefix in registry
        and registry[r.prefix].announce_month < today_month
    ]


def format_discover_table(results: list[ProbeResult]) -> str:
    """Human-readable sweep report, live venues first."""
    order = {"live": 0, "needs-manual": 1, "empty": 2, "unreachable": 3, "not-yet": 4}
    rows = sorted(results, key=lambda r: (order.get(r.status, 9), r.conf_id))

    lines = [
        "",
        f"{'Conference':<24} {'Status':<14} {'Papers':>7}  URL",
        "-" * 100,
    ]
    for r in rows:
        count = str(r.count) if r.count else "-"
        note = f"  ({r.note})" if r.note else ""
        lines.append(f"{r.conf_id:<24} {r.status:<14} {count:>7}  {r.url}{note}")

    live = [r for r in results if r.status == "live"]
    manual = [r for r in results if r.status == "needs-manual"]
    lines.append("")
    if live:
        lines.append(
            f"{len(live)} new list(s) ready to register: "
            + ", ".join(f"{r.conf_id} ({r.count})" for r in live)
        )
    else:
        lines.append("no new lists ready to register.")
    if manual:
        lines.append(
            f"{len(manual)} venue(s) need a hand-written scraper: "
            + ", ".join(r.conf_id for r in manual)
        )
    return "\n".join(lines)


def results_to_json(results: list[ProbeResult], stale: list[ProbeResult] | None = None) -> str:
    """Machine-readable sweep report for the scheduled workflow.

    `stale_empty` is computed here rather than left to the caller: the workflow
    that consumes this is JavaScript and has no access to the registry's
    announce months, so the broken-selector signal has to arrive precomputed.
    """
    return json.dumps(
        {
            "results": [
                {
                    "conf_id": r.conf_id, "prefix": r.prefix, "year": r.year,
                    "status": r.status, "count": r.count, "url": r.url, "note": r.note,
                    "registration": r.registration,
                }
                for r in results
            ],
            "live_count": sum(1 for r in results if r.status == "live"),
            "stale_empty": [r.conf_id for r in (stale or [])],
        },
        indent=2,
    )
