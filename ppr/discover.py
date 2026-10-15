"""Find conference-years that have published a list we have not registered."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ppr import dblp_client
from ppr.venues import MANUAL_SOURCES, REGISTRY_STEM, Venue

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

    ids = {p.stem for p in CONFIGS_DIR.glob("*.yaml") if p.stem != REGISTRY_STEM}
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

    Looks from the venue's earliest known year through next year -- the extra
    year catches a venue that publishes ahead of schedule, as OpenReview venues
    routinely do. A venue with nothing registered yields nothing: there is no
    baseline to extrapolate from, and an unregistered venue is caught by the
    registry drift test instead.
    """
    known = {
        int(cid.rsplit("_", 1)[1])
        for cid in known_ids
        if cid.rsplit("_", 1)[0] == prefix and cid.rsplit("_", 1)[1].isdigit()
    }
    if not known:
        return []

    return [
        year
        for year in range(min(known), today_year + 2)
        if _matches_cadence(year, cadence) and year not in known
    ]


# A page-scraping probe must clear this to count as live. Above the 9 links
# CVPR 2026's stub page yields, far below the smallest proceedings tracked
# (ISSTA 2025, 110 papers). DBLP and OpenReview report exact record counts,
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
    # toc candidate hit or which parser counted the page; rebuilding that later
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


def _dblp_toc_candidates(venue: Venue, year: int) -> list[dict]:
    """Every toc key worth trying for this venue-year, in order.

    Most venues have one stable key. FSE and ISSTA do not: both migrated to
    shared PACMSE journal volumes (FSE from 2024, ISSTA from 2025), whose
    volume number is not the year -- pacmse1 is 2024, pacmse2 is 2025. A single
    `{year}` template cannot express that, so those venues list several
    candidates and the probe takes the first that returns hits.

    FSE and ISSTA can even share the *same* volume -- pacmse2 holds both FSE
    2025 and ISSTA 2025 -- distinguished only by each entry's `number` field.
    A candidate can carry a `number` filter for exactly this case; the plain
    string form is shorthand for "no filter, trust `@total`".
    """
    toc = venue.probe["toc"]
    templates = list(toc) if isinstance(toc, list) else [toc]

    candidates = []
    for template in templates:
        if isinstance(template, dict):
            key = template["key"].format(year=year, pacmse_vol=year - 2023)
            candidates.append({"key": key, "number": template.get("number")})
        else:
            key = template.format(year=year, pacmse_vol=year - 2023)
            candidates.append({"key": key, "number": None})
    return candidates


def _probe_dblp(venue: Venue, year: int) -> ProbeResult:
    """Try each candidate toc key; the first with hits wins.

    Stopping at anything other than `not-yet` (in particular, `unreachable`)
    matters as much as stopping at a hit: a candidate throttled into
    `unreachable` must not be papered over by a later candidate's `not-yet`,
    or a throttled sweep would misreport as "nothing new".
    """
    candidates = _dblp_toc_candidates(venue, year)
    last = None
    for candidate in candidates:
        last = _probe_dblp_key(venue, year, candidate["key"], number=candidate["number"])
        if last.status != "not-yet":
            return last
    return last


def _probe_dblp_key(venue: Venue, year: int, key: str, number: str | None = None) -> ProbeResult:
    """Count one toc key's papers through DBLP's SPARQL endpoint.

    When `number` is set, the key names a shared PACMSE volume and only the
    entries filed under that venue's issue are counted -- the same filter the
    DBLP scraper crawls with.
    """
    url = f"https://dblp.org/db/{key.removeprefix('db/').removesuffix('.bht')}.html"
    try:
        total = dblp_client.toc_count([key], number=number)
    except dblp_client.DblpUnavailable as exc:
        return _result(venue, year, "unreachable", 0, url, str(exc))

    status = "live" if total > 0 else "not-yet"
    registration = {"key": key, "number": number} if number else {"key": key}
    return _result(venue, year, status, total, url, registration=registration)


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

    status = "live" if notes else "not-yet"
    return _result(venue, year, status, len(notes), url, registration={"venue_id": venue_id})


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
            results.append(probe(venue, year, openreview_client=openreview_client))
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
