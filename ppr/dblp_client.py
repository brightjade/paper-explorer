"""Single point of contact with DBLP, through its SPARQL endpoint.

On 2026-10-14 dblp.org put the Anubis proof-of-work bot wall in front of
everything it serves: the search API, the HTML and XML pages and both mirrors
answer every client with HTTP 202 and a challenge page, and its robots.txt
disallows /search/publ. `sparql.dblp.org` is the sanctioned path -- its
robots.txt allows /sparql -- and `dblp:listedOnTocPage` reproduces the search
API's `toc:` queries exactly (all 23 conference-years we crawled from DBLP,
once proceedings volumes are excluded).

Four subsystems read DBLP: discovery, count validation, the DBLP scraper and
the researchr scraper's DOI backfill. They share this module so they share one
pacing clock and one refusal to hand back anything but a real answer: every
public function returns a complete result or raises `DblpUnavailable`. There is
deliberately no "return 0 on failure" path -- a throttled query silently read
as a count is how `ppr validate` once reported mismatches that were not real.
"""

import html
import logging
import re
import time

import requests

from ppr.net import PROJECT_USER_AGENT, parse_retry_after

logger = logging.getLogger(__name__)

ENDPOINT = "https://sparql.dblp.org/sparql"

# sparql.dblp.org/robots.txt (checked 2026-10-14): `Allow: /sparql`,
# `Crawl-delay: 10`. A server-stated figure beats a guess.
MIN_INTERVAL = 10.0
MAX_RETRIES = 5
# Overload shows up as bare 500/503s as well as 429s, and they clear within
# seconds; treating them as terminal turns throttling into a wrong answer.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
TIMEOUT = 60

HEADERS = {
    "User-Agent": PROJECT_USER_AGENT,
    "Accept": "application/sparql-results+json",
}

PREFIXES = "PREFIX dblp: <https://dblp.org/rdf/schema#>\n"

_KEY = re.compile(r"[A-Za-z0-9/_.-]+")

# When the last request went out, on the monotonic clock. Module state because
# the interval is a property of the host, not of any one caller.
_last_request = 0.0


class DblpUnavailable(Exception):
    """DBLP never answered: walled, throttled, erroring, truncated or unparseable.

    Distinct from "DBLP answered with zero hits", which is a real answer a
    caller may act on. This exception means the caller knows nothing, and must
    not report a count.
    """


def _wait_for_turn() -> None:
    """Sleep until `MIN_INTERVAL` has passed since the last request went out."""
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


def select(query: str) -> list[dict]:
    """Run one paced, retried SPARQL SELECT; return its result bindings.

    POSTed, because a toc list as long as ECCV 2024's 89 volumes does not fit
    in a GET URL.
    """
    last_failure = ""
    for attempt in range(MAX_RETRIES):
        _wait_for_turn()
        try:
            response = requests.post(
                ENDPOINT, data={"query": PREFIXES + query}, headers=HEADERS, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            last_failure = type(exc).__name__
            logger.debug("DBLP request failed (%s); retrying", last_failure)
            time.sleep(2**attempt)
            continue

        if response.status_code in RETRYABLE_STATUSES:
            last_failure = f"HTTP {response.status_code}"
            # DBLP's own Retry-After beats a guessed exponential backoff when
            # it sends one; fall back to 2**attempt when it doesn't.
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            time.sleep(retry_after if retry_after is not None else 2**attempt)
            continue

        if response.status_code == 202:
            # Anubis's proof-of-work page. Retrying does not get past it, and we
            # do not try to: report it for what it is.
            raise DblpUnavailable("bot challenge (HTTP 202)")
        if response.status_code != 200:
            raise DblpUnavailable(f"HTTP {response.status_code}")

        try:
            payload = response.json()
            bindings = payload["results"]["bindings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise DblpUnavailable(
                "bot challenge or unparseable response (HTTP 200, not SPARQL JSON)"
            ) from exc

        total = (payload.get("meta") or {}).get("result-size-total")
        if total is not None:
            try:
                complete = int(total) == len(bindings)
            except (TypeError, ValueError) as exc:
                raise DblpUnavailable(f"unparseable result-size-total {total!r}") from exc
            if not complete:
                raise DblpUnavailable(f"truncated result ({len(bindings)} of {total} rows)")
        return bindings

    raise DblpUnavailable(f"{last_failure} after {MAX_RETRIES} attempts")


def toc_iri(key: str) -> str:
    """`db/conf/icse/icse2025.bht` -> `https://dblp.org/db/conf/icse/icse2025`.

    Keys come from our own registry, but they are spliced into a query, so a
    key that could close the IRI is refused rather than sent.
    """
    if not _KEY.fullmatch(key):
        raise ValueError(f"not a DBLP toc key: {key!r}")
    return "https://dblp.org/" + key.removesuffix(".bht")


def _toc_pattern(keys: list[str], number: str | None) -> str:
    values = " ".join(f"<{toc_iri(k)}>" for k in keys)
    pattern = f"VALUES ?toc {{ {values} }} ?pub dblp:listedOnTocPage ?toc . "
    if number:
        # PACMSE volumes hold FSE and ISSTA together; the issue names the venue.
        if not _KEY.fullmatch(number):
            raise ValueError(f"not a PACMSE issue name: {number!r}")
        pattern += f'?pub dblp:publishedInJournalVolumeIssue ?issue . FILTER(STR(?issue) = "{number}") '
    # The proceedings volume itself is listed on its own toc page; it is not a paper.
    return pattern + "FILTER NOT EXISTS { ?pub a dblp:Editorship }"


def toc_count(keys: list[str], number: str | None = None) -> int:
    """Count the papers on one or more toc pages, in one query."""
    if not keys:
        raise ValueError("toc_count needs at least one toc key")
    rows = select(f"SELECT (COUNT(DISTINCT ?pub) AS ?n) WHERE {{ {_toc_pattern(keys, number)} }}")
    try:
        return int(rows[0]["n"]["value"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise DblpUnavailable("unparseable count") from exc


def clean_author(name: str) -> str:
    """Strip DBLP's disambiguation suffix: 'Hao Zhong 0001' -> 'Hao Zhong'."""
    return re.sub(r"\s+\d{4}$", "", name)


# ASE 2015 suffixes each title with its track, " (T)" technical or " (N)" new
# ideas; no other venue-year in the dataset does (checked 2026-10-17).
_TRACK_MARKER = re.compile(r"\s+\([TN]\)$")


def clean_title(title: str) -> str:
    """Unescape entities, drop the trailing period DBLP puts on every title, and ASE 2015's track marker."""
    title = html.unescape(title)
    title = title[:-1] if title.endswith(".") else title
    return _TRACK_MARKER.sub("", title)


def _pick_link(links: set[str]) -> str:
    dois = sorted(link for link in links if link.startswith("https://doi.org/"))
    if dois:
        return dois[0]
    return min(links) if links else ""


def toc_papers(key: str, number: str | None = None) -> list[dict]:
    """Every paper on a toc page as `{"title", "link", "authors"}`.

    Titles and authors go through `clean_title` and `clean_author`, so rows
    built from these match the ones already in `data/`. A paper with several
    document pages appears once per page in the result; its link is the DOI when
    it has one, chosen the same way every time.
    """
    rows = select(
        "SELECT ?pub ?title ?link ?ord ?name WHERE { "
        f"{_toc_pattern([key], number)} ?pub dblp:title ?title . "
        "OPTIONAL { ?pub dblp:primaryDocumentPage ?link } "
        "OPTIONAL { ?pub dblp:hasSignature ?sig . ?sig a dblp:AuthorSignature ; "
        "dblp:signatureOrdinal ?ord ; dblp:signatureDblpName ?name . } "
        "} ORDER BY ?pub ?ord"
    )
    pubs: dict[str, dict] = {}
    for row in rows:
        pub = pubs.setdefault(
            row["pub"]["value"],
            {"title": clean_title(row["title"]["value"]), "links": set(), "authors": {}},
        )
        if "link" in row:
            pub["links"].add(row["link"]["value"])
        if "ord" in row:
            pub["authors"][int(row["ord"]["value"])] = clean_author(row["name"]["value"])
    return [
        {
            "title": p["title"],
            "link": _pick_link(p["links"]),
            "authors": [p["authors"][k] for k in sorted(p["authors"])],
        }
        for p in pubs.values()
    ]
