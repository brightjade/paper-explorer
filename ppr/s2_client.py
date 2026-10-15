"""Single point of contact with the Semantic Scholar Graph API.

Owns pacing and retry so every endpoint inherits the same backoff behavior.
Returns raw API dicts; mapping onto `Paper` attributes belongs in ppr/enrich.py.
"""

import asyncio
import logging
import random

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.semanticscholar.org/graph/v1"
MATCH_URL = f"{API_BASE}/paper/search/match"
BATCH_URL = f"{API_BASE}/paper/batch"
BULK_URL = f"{API_BASE}/paper/search/bulk"

# POST /paper/batch accepts at most 500 IDs per request.
BATCH_CHUNK_SIZE = 500

ENRICHMENT_FIELDS = (
    "title,authors,citationCount,abstract,influentialCitationCount,"
    "referenceCount,tldr,publicationDate,fieldsOfStudy,openAccessPdf,externalIds"
)

# /paper/search/bulk rejects `tldr` outright (400 Unrecognized or unsupported
# fields), unlike /paper/batch and /paper/search/match which both accept it.
BULK_FIELDS = ",".join(f for f in ENRICHMENT_FIELDS.split(",") if f != "tldr")

MAX_RETRIES = 8


class S2Client:
    def __init__(self, api_key: str | None = None, min_interval: float = 1.0):
        self.headers = {"x-api-key": api_key} if api_key else {}
        self._min_interval = min_interval
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def _rate_limit(self) -> None:
        """Enforce a minimum gap between requests, across all callers."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    @staticmethod
    def _backoff(attempt: int) -> float:
        return (2**attempt) + random.uniform(0, 1)

    async def _request_with_retry(
        self, client: httpx.AsyncClient, method: str, url: str, **kwargs
    ) -> httpx.Response | None:
        """Issue one request, retrying throttles and transport errors.

        Semantic Scholar returns 403 (not 429) when its shared anonymous pool is
        saturated. That is transient and IP-independent, so it is retried rather
        than treated as an auth failure.
        """
        for attempt in range(MAX_RETRIES):
            await self._rate_limit()
            try:
                response = await client.request(
                    method, url, headers=self.headers, **kwargs
                )
            except httpx.RequestError as exc:
                logger.debug("Transport error on %s: %s", url, exc)
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code in (429, 403) or response.status_code >= 500:
                await asyncio.sleep(self._backoff(attempt))
                continue

            return response

        logger.warning("Giving up on %s after %d attempts", url, MAX_RETRIES)
        return None

    async def match_title(
        self, client: httpx.AsyncClient, title: str
    ) -> dict | None:
        """Look one paper up by title. Returns the raw entry, or None."""
        response = await self._request_with_retry(
            client,
            "GET",
            MATCH_URL,
            params={"query": title, "fields": ENRICHMENT_FIELDS},
        )
        if response is None or response.status_code == 404:
            return None
        try:
            return response.json()["data"][0]
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def get_batch(
        self, client: httpx.AsyncClient, ids: list[str]
    ) -> list[dict | None]:
        """Look papers up by ID, 500 per request.

        `ids` are prefixed Semantic Scholar identifiers (`CorpusId:…`, `DOI:…`).
        The returned list is positionally aligned with `ids`; an entry is None
        when Semantic Scholar had no record, or when its chunk failed outright.
        """
        results: list[dict | None] = []
        for start in range(0, len(ids), BATCH_CHUNK_SIZE):
            chunk = ids[start : start + BATCH_CHUNK_SIZE]
            response = await self._request_with_retry(
                client,
                "POST",
                BATCH_URL,
                params={"fields": ENRICHMENT_FIELDS},
                json={"ids": chunk},
            )
            if response is None or response.status_code != 200:
                logger.warning(
                    "Batch chunk of %d IDs failed; leaving them unchanged",
                    len(chunk),
                )
                results.extend([None] * len(chunk))
                continue
            try:
                entries = response.json()
            except ValueError:
                entries = None
            # A 200 whose body is not a list (an error envelope, say) carries no
            # per-ID data. Fail the chunk like any other, so one odd response
            # costs 500 papers rather than the whole conference.
            if not isinstance(entries, list):
                logger.warning(
                    "Batch chunk of %d IDs returned an unexpected body; "
                    "leaving them unchanged",
                    len(chunk),
                )
                results.extend([None] * len(chunk))
                continue
            # Defend against a short response so alignment with `ids` holds.
            if len(entries) < len(chunk):
                entries = list(entries) + [None] * (len(chunk) - len(entries))
            results.extend(entries[: len(chunk)])
        return results

    async def bulk_search(
        self, client: httpx.AsyncClient, venue: str, year: int
    ) -> list[dict]:
        """Fetch every paper Semantic Scholar indexes for a venue and year.

        Coverage is partial and depends on Semantic Scholar's own venue naming,
        so callers must treat this as an optimization: an empty result means
        fall back to per-title matching, not that the venue has no papers.
        """
        collected: list[dict] = []
        params = {"venue": venue, "year": str(year), "fields": BULK_FIELDS}
        while True:
            response = await self._request_with_retry(
                client, "GET", BULK_URL, params=params
            )
            if response is None or response.status_code != 200:
                logger.warning("Bulk search failed for %s %s", venue, year)
                return collected
            try:
                payload = response.json()
            except ValueError:
                return collected
            # Prefetch is an optimization: an unexpected body shape means stop
            # and let the caller fall back to per-title matching.
            if not isinstance(payload, dict):
                logger.warning(
                    "Bulk search for %s %s returned an unexpected body", venue, year
                )
                return collected

            page = payload.get("data") or []
            if not page:
                return collected
            collected.extend(page)

            token = payload.get("token")
            if not token:
                return collected
            params = dict(params, token=token)
