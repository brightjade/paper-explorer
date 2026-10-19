"""Per-conference enrichment: path selection, merging, guards, atomic writes."""

import argparse
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TextIO

import httpx
from tqdm import tqdm

from ppr.archive import plan_enrich
from ppr.matching import MATCHED, MATCHED_FUZZY, REJECT, match_verdict, title_key
from ppr.layout import checkpoint_path, papers_path
from ppr.models import Paper
from ppr.s2_client import BATCH_CHUNK_SIZE, S2Client
from ppr.store import (
    MIN_COVERAGE_RATIO,
    carry_over,
    check_enrichment_coverage,
    crawl_view,
    enrichment_coverage,
    normalize_title,
    read_papers,
    save_enriched,
)

logger = logging.getLogger(__name__)


def apply_enrichment(paper: Paper, entry: dict | None) -> Paper:
    """Merge one raw Semantic Scholar record into `paper`, in place.

    A None entry — or one with no citation count — means the API had nothing to
    say, so the existing record is left exactly as it was. Crawl-owned fields
    (title, authors, link, selection, keywords, forum_id) are never touched.
    """
    if entry is None or entry.get("citationCount") is None:
        return paper

    paper.citation_count = entry.get("citationCount")
    paper.influential_citation_count = entry.get("influentialCitationCount")
    paper.reference_count = entry.get("referenceCount")
    paper.publication_date = entry.get("publicationDate") or ""
    paper.fields_of_study = entry.get("fieldsOfStudy") or []

    pdf = entry.get("openAccessPdf")
    paper.open_access_pdf = pdf.get("url", "") if isinstance(pdf, dict) else ""

    paper.external_ids = entry.get("externalIds") or {}

    tldr = entry.get("tldr")
    tldr_text = tldr.get("text", "") if isinstance(tldr, dict) else ""
    if tldr_text:
        paper.tldr = tldr_text

    if not paper.abstract and entry.get("abstract"):
        paper.abstract = entry["abstract"]
        paper.abstract_source = "s2"

    return paper


def unbind(paper: Paper) -> Paper:
    """Sever a binding that failed verification, in place.

    Everything Semantic Scholar contributed goes, because all of it described
    a different paper -- an abstract it filled in included. A crawl's own
    abstract (OpenReview's) stays: `crawl_view` tells them apart by
    `abstract_source`. The paper is left looking exactly like one that was
    never matched, which is what puts it back in the retry queue.
    """
    crawl_view(paper)
    paper.match_status = "not_found"
    return paper


class Checkpoint:
    """Append-only log of papers whose Semantic Scholar lookup has finished.

    The year file is written once, at the end, so without this a run
    killed at 277 of 381 papers loses all 277 lookups — and the cold paths cost
    roughly a second per paper, so a large conference is hours of work with
    nothing to show for an interruption. Each finished paper is appended and
    flushed as it completes; a later run reads the file back and skips those
    papers. It is deleted once the year file lands, which supersedes it.

    Flushing (not fsync) is deliberate: the failure this protects against is the
    process dying, not the machine, and fsync per paper would be pure cost.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: TextIO | None = None

    def restore(self) -> dict[str, Paper]:
        """Papers a previous run already looked up, keyed by normalized title.

        A file left behind by a killed process can end in a half-written line,
        so unparseable lines are dropped rather than failing the run — the
        papers they describe simply get looked up again. The file is then
        rewritten from what did parse, because appending onto a torn line would
        swallow the next good record into it and lose that paper as well.
        """
        if not self.path.exists():
            return {}
        done: dict[str, Paper] = {}
        torn = False
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    paper = Paper.from_dict(json.loads(line))
                except (ValueError, KeyError):
                    torn = True
                    continue
                done[normalize_title(paper.title)] = paper
        if torn:
            logger.warning(
                "Dropping an unparseable line from %s — the papers it covered "
                "will be looked up again",
                self.path,
            )
            self._rewrite(list(done.values()))
        return done

    def _rewrite(self, papers: list[Paper]) -> None:
        """Replace the file with `papers`, atomically.

        Only used to heal a torn file, so that every later append lands on a
        line of its own.
        """
        self.close()
        tmp = self.path.with_suffix(self.path.suffix + ".rewrite")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for paper in papers:
                    f.write(paper.to_json() + "\n")
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def record(self, papers: list[Paper]) -> None:
        """Append finished papers and flush, so a kill loses only what is in flight."""
        if not papers:
            return
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")
        for paper in papers:
            self._file.write(paper.to_json() + "\n")
        self._file.flush()

    def discard(self) -> None:
        self.close()
        self.path.unlink(missing_ok=True)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "Checkpoint":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# Semantic Scholar's own venue strings, for bulk prefetch. Only entries verified
# against the live API belong here — a prefix that is absent simply skips
# prefetch and falls back to per-title matching, which is always correct.
# Each string below was probed against /paper/search/bulk and returned a total
# within the same order of magnitude as our own count for that venue-year. S2
# resolves an acronym and its expansion to the same venue, so both forms return
# identical totals; the expansion is preferred where the acronym is ambiguous.
# TMLR is the exception: only the abbreviated journal name "Trans. Mach. Learn.
# Res." returns papers; the full name and "TMLR" both return 0.
S2_VENUE_NAMES: dict[str, str] = {
    "aaai": "AAAI Conference on Artificial Intelligence",
    "acl": "Annual Meeting of the Association for Computational Linguistics",
    "coling": "International Conference on Computational Linguistics",
    "cvpr": "CVPR",
    "eccv": "European Conference on Computer Vision",
    "emnlp": "Conference on Empirical Methods in Natural Language Processing",
    "iccv": "IEEE International Conference on Computer Vision",
    "iclr": "International Conference on Learning Representations",
    "icml": "International Conference on Machine Learning",
    "ijcai": "International Joint Conference on Artificial Intelligence",
    "naacl": "NAACL",
    "neurips": "Neural Information Processing Systems",
    "tmlr": "Trans. Mach. Learn. Res.",
    "usenix_security": "USENIX Security Symposium",
    "wacv": "WACV",
}

# Year offsets bulk prefetch covers besides the conference's own year. S2 dates
# a TMLR paper by its arXiv version, which precedes the OpenReview publication
# year we file it under: S2's 2022 holds 445 TMLR papers against our 216.
_BULK_YEAR_OFFSETS: dict[str, tuple[int, ...]] = {"tmlr": (-1, 0)}


def bulk_years(prefix: str, year: int) -> list[int]:
    """The S2 years to prefetch for a venue-year, oldest first."""
    return [year + offset for offset in _BULK_YEAR_OFFSETS.get(prefix, (0,))]


class Deadline:
    """When per-title matching must stop. A `None` budget never passes.

    Only the `/search/match` loop consults it. That loop runs at ~0.3 req/s and
    is the one part of a run whose length the data, not the code, decides --
    an unindexed 6,000-paper venue alone is ~5.5 hours, past GitHub's job
    limit. Everything else finishes in about half an hour and always runs.
    """

    def __init__(self, budget_seconds: float | None, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._at = None if budget_seconds is None else clock() + budget_seconds

    def passed(self) -> bool:
        return self._at is not None and self._clock() >= self._at


NO_DEADLINE = Deadline(None)

_DURATION = re.compile(r"(\d+)([smh])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_duration(text: str) -> int:
    match = _DURATION.fullmatch(text)
    if not match:
        raise argparse.ArgumentTypeError(f"expected <int>s, <int>m or <int>h, got {text!r}")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def order_newest_first(conf_ids: list[str]) -> list[str]:
    """Newest year first, so a short budget goes where Semantic Scholar is
    still indexing. Old years' leftovers are mostly papers S2 will never have,
    and bulk prefetch still runs for them every month."""
    def year(conf_id: str) -> int:
        tail = conf_id.rpartition("_")[2]
        return int(tail) if tail.isdigit() else 0
    return sorted(conf_ids, key=lambda c: (-year(c), c))


@dataclass
class EnrichResult:
    conf_id: str
    status: str  # "enriched" | "skipped" | "failed" | "nothing-to-do" | "not-due"
    path: str = ""  # "refresh" | "id-cold" | "title-cold" | ""
    total: int = 0
    refreshed: int = 0
    cold: int = 0
    resumed: int = 0
    unbound: int = 0
    deferred: int = 0  # papers left unmatched when the time budget ran out; a subset of cold
    untried: int = 0  # archive papers batch-only mode never title-matched; a subset of cold
    reason: str = ""


def corpus_id_of(paper: Paper) -> str | None:
    """The paper's Semantic Scholar corpus ID, if a previous run found one."""
    corpus = (paper.external_ids or {}).get("CorpusId")
    return f"CorpusId:{corpus}" if corpus else None


def doi_id_of(paper: Paper) -> str | None:
    """A DOI recorded by the crawler, if this venue's source provides one."""
    prefix = "https://doi.org/"
    if paper.link and paper.link.startswith(prefix):
        return f"DOI:{paper.link[len(prefix):]}"
    return None


def route_papers(
    raw: list[Paper],
    prior_by_title: dict[str, Paper],
    *,
    full: bool,
) -> tuple[list[Paper], list[Paper], list[Paper]]:
    """Split raw papers into (refresh, doi_cold, title_cold).

    Papers are mutated in place: each one that has prior enrichment receives it
    via carry_over before being routed, so a lookup that comes back empty falls
    back to the previous values rather than to nothing.

    A paper whose prior enrichment carries no CorpusId is always routed cold.
    Semantic Scholar indexes a conference weeks to months after we crawl it, so
    "not found" is a statement about a moment, not about the paper; the monthly
    run is what turns it back into a question.
    """
    refresh: list[Paper] = []
    doi_cold: list[Paper] = []
    title_cold: list[Paper] = []

    for paper in raw:
        prior = prior_by_title.get(normalize_title(paper.title))
        if prior is not None and not full:
            carry_over(paper, prior)

        if not full and prior is not None and corpus_id_of(prior):
            refresh.append(paper)
        else:
            (doi_cold if doi_id_of(paper) else title_cold).append(paper)

    return refresh, doi_cold, title_cold


def _dominant_path(refresh: list, doi_cold: list, title_cold: list) -> str:
    """Label the run by whichever path handled the most papers."""
    counts = {"refresh": len(refresh), "id-cold": len(doi_cold), "title-cold": len(title_cold)}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] else ""


Record = Callable[[list[Paper]], None]


async def _run_batch(
    client: S2Client,
    http: httpx.AsyncClient,
    papers: list[Paper],
    id_of,
    *,
    mode: str,
    record: Record,
) -> tuple[list[Paper], int]:
    """Look papers up by ID and merge the results in place.

    `mode` is "verify" for the CorpusId refresh, which re-checks that the
    record still describes the paper we crawled, or "set" for the DOI path,
    where the identifier is authoritative and no title check applies.

    Returns (papers the lookup left unsettled, count of papers accepted on
    fuzzy evidence). Unsettled is a refresh binding rejected and cleared, or a
    DOI Semantic Scholar answered with nothing. Neither is checkpointed here:
    the caller retries both (an unbound paper with a DOI tries that first), and
    only the retry records them. Chunked at the size the API accepts per
    request, so progress is checkpointed a request at a time; this path is
    fast enough that finer granularity would buy nothing.
    """
    unsettled: list[Paper] = []
    fuzzy = 0
    if not papers:
        return unsettled, fuzzy
    for start in range(0, len(papers), BATCH_CHUNK_SIZE):
        chunk = papers[start : start + BATCH_CHUNK_SIZE]
        entries = await client.get_batch(http, [id_of(p) for p in chunk])
        settled: list[Paper] = []
        for paper, entry in zip(chunk, entries):
            # A None entry means the API had nothing to say — never that
            # verification failed. get_batch reports a failed chunk as 500
            # Nones, so unbinding here would sever them all over one hiccup.
            if mode == "verify" and entry is not None:
                verdict = match_verdict(paper.title, paper.authors, entry)
                if verdict == REJECT:
                    unbind(paper)
                    unsettled.append(paper)
                    continue
                paper.match_status = verdict
                if verdict == MATCHED_FUZZY:
                    fuzzy += 1
            if mode == "set" and entry is None:
                # Semantic Scholar can hold the paper without this DOI (DBLP
                # records DOIs it never linked), and a failed chunk is all
                # Nones too: either way the title path is still worth asking.
                unsettled.append(paper)
                continue
            apply_enrichment(paper, entry)
            if mode == "set":
                paper.match_status = "matched"
            settled.append(paper)
        # Unsettled papers are deliberately left out: they are checkpointed
        # only once their cold retry finishes, so a crash between the two
        # stages cannot freeze a paper as unsettled-but-never-retried.
        record(settled)
    return unsettled, fuzzy


async def _run_title_cold(
    client: S2Client,
    http: httpx.AsyncClient,
    papers: list[Paper],
    conf_id: str,
    record: Record,
    deadline: Deadline = NO_DEADLINE,
) -> tuple[int, int]:
    """Prefetch the venue in bulk, then match the remainder one at a time.

    Returns (fuzzy, deferred): the count of papers accepted on fuzzy evidence,
    for the caller to fold into one per-conference log alongside the refresh
    path's own count, and the count the deadline left unattempted.
    """
    if not papers:
        return 0, 0

    prefix, _, year_str = conf_id.rpartition("_")
    venue = S2_VENUE_NAMES.get(prefix)
    index: dict[str, dict] = {}
    if venue and year_str.isdigit():
        for bulk_year in bulk_years(prefix, int(year_str)):
            for entry in await client.bulk_search(http, venue, bulk_year):
                title = entry.get("title")
                if title:
                    index.setdefault(title_key(title), entry)
        logger.info(
            "Bulk prefetch for %s returned %d indexed papers", conf_id, len(index)
        )

    misses: list[Paper] = []
    prefetched: list[Paper] = []
    for paper in papers:
        entry = index.get(title_key(paper.title))
        if entry is None:
            misses.append(paper)
            continue
        apply_enrichment(paper, entry)
        # An index hit is an exact title_key equality by construction, so it
        # is trusted directly — no need to consult match_verdict.
        paper.match_status = MATCHED
        prefetched.append(paper)
    record(prefetched)

    if misses:
        logger.info(
            "%s: %d papers not covered by bulk prefetch, matching by title",
            conf_id,
            len(misses),
        )
    # Checkpointed one paper at a time: this loop is the slow path, a second or
    # more per paper, so per-paper granularity is what makes resume worth having.
    deferred = 0
    for i, paper in enumerate(tqdm(misses, desc=f"Matching {conf_id}", unit="paper")):
        if deadline.passed():
            # Left exactly as routed: carried-over values, or none for a new
            # paper. Not "not_found" -- nobody asked. Retry-by-default picks
            # them up on the next run.
            deferred = len(misses) - i
            logger.info("%s: time budget spent, %d papers deferred", conf_id, deferred)
            break
        entry = await client.match_title(http, paper.title)
        # /search/match answers an unindexed paper with its nearest fuzzy
        # neighbour rather than with nothing, so an unchecked data[0] is how a
        # paper ends up wearing a stranger's citations. Only a justified match
        # is allowed to bind.
        verdict = (
            match_verdict(paper.title, paper.authors, entry)
            if entry is not None
            else REJECT
        )
        if verdict == REJECT:
            paper.match_status = "not_found"
        else:
            apply_enrichment(paper, entry)
            paper.match_status = verdict
        record([paper])

    return sum(1 for p in papers if p.match_status == MATCHED_FUZZY), deferred


async def enrich_conference(
    conf_id: str,
    client: S2Client,
    data_dir: Path,
    *,
    full: bool = False,
    deadline: Deadline = NO_DEADLINE,
    batch_only: bool = False,
) -> EnrichResult:
    """Enrich a single conference, choosing the cheapest workable path.

    Progress is checkpointed as it happens, so a run killed partway through the
    cold paths resumes instead of starting over. The checkpoint only ever
    shortcuts lookups: guards and the final write still see the whole paper set,
    so a resumed run produces exactly the file an uninterrupted one would.

    `batch_only` is the archive mode (see `ppr/archive.py`): the refresh and
    DOI batches run, title matching does not, DOI misses included. A paper
    reaches the archive already title-tried by a full run (its live years, or
    the named run that backfilled it), and Semantic Scholar finished indexing
    these years long ago, so a title it could not match then it will not match
    now; those papers are written as routed and counted `untried`.
    """
    path = papers_path(data_dir, conf_id)
    checkpoint = Checkpoint(checkpoint_path(data_dir, conf_id))
    if full:
        # --full exists to discard prior enrichment; resuming onto a checkpoint
        # written by an earlier run would quietly keep the very values it is
        # meant to throw away.
        checkpoint.discard()

    papers = read_papers(path)
    # The file as this run found it, read a second time so `papers` can be
    # mutated: each paper's prior enrichment, and the coverage guard's baseline.
    before = read_papers(path)

    if not papers:
        # A success path like any other, so it clears the checkpoint too;
        # leaving one here would let it be consumed by a later, unrelated crawl.
        checkpoint.discard()
        return EnrichResult(conf_id, "nothing-to-do")

    if full:
        for paper in papers:
            crawl_view(paper)

    # The file stays authoritative for membership: the checkpoint contributes
    # enrichment to papers still listed and nothing else, so one it holds that
    # the latest crawl dropped stays dropped.
    done = checkpoint.restore()
    todo: list[Paper] = []
    for paper in papers:
        finished = done.get(normalize_title(paper.title))
        if finished is None:
            todo.append(paper)
        else:
            carry_over(paper, finished)
    resumed = len(papers) - len(todo)
    if resumed:
        logger.info(
            "Resuming %s: %d of %d papers already done in %s",
            conf_id,
            resumed,
            len(papers),
            checkpoint.path.name,
        )

    prior_by_title = {normalize_title(p.title): p for p in before}
    refresh, doi_cold, title_cold = route_papers(todo, prior_by_title, full=full)

    # Assigned before the block runs: it is always set inside today, but a
    # future early return in here must still report zero, not raise
    # UnboundLocalError on the read below.
    unbound: list[Paper] = []
    deferred = 0
    untried = 0
    with checkpoint:
        async with httpx.AsyncClient(timeout=60.0) as http:
            unbound, refresh_fuzzy = await _run_batch(
                client, http, refresh, corpus_id_of,
                mode="verify",
                record=checkpoint.record,
            )
            # Routed exactly like any unmatched paper, because that is what
            # they now are. A DOI-bearing paper goes back through the DOI path,
            # where the identifier is authoritative.
            for paper in unbound:
                (doi_cold if doi_id_of(paper) else title_cold).append(paper)
            doi_missed, _ = await _run_batch(
                client, http, doi_cold, doi_id_of,
                mode="set", record=checkpoint.record,
            )
            # Kept out of title_cold so the counts below see each paper once.
            title_queue = title_cold + doi_missed
            if batch_only:
                title_cold_fuzzy, untried = 0, len(title_queue)
            else:
                title_cold_fuzzy, deferred = await _run_title_cold(
                    client, http, title_queue, conf_id,
                    record=checkpoint.record, deadline=deadline,
                )

    # One combined line per conference — refresh is where most fuzzy verdicts
    # actually land, so counting only the title-cold path here would miss
    # most of them.
    fuzzy_total = refresh_fuzzy + title_cold_fuzzy
    if fuzzy_total:
        logger.info(
            "%s: %d papers matched on fuzzy evidence rather than an exact title",
            conf_id,
            fuzzy_total,
        )

    reason = check_enrichment_coverage(papers, before)
    if reason:
        logger.warning("Skipping %s: %s", conf_id, reason)
        # The checkpoint holds exactly the results this guard just rejected.
        # Keeping it would make every later run restore them, skip the lookups
        # and hit the same guard — the retry the message asks for would be
        # impossible without --full.
        checkpoint.discard()
        return EnrichResult(conf_id, "skipped", reason=reason)

    save_enriched(papers, path)
    checkpoint.discard()

    return EnrichResult(
        conf_id=conf_id,
        status="enriched",
        path=_dominant_path(refresh, doi_cold, title_cold),
        total=len(papers),
        # Unbound papers were refreshed and then re-run cold. Counting them
        # only under Cold keeps total = Refresh + Cold + Resumed.
        refreshed=len(refresh) - len(unbound),
        cold=len(doi_cold) + len(title_cold),
        resumed=resumed,
        unbound=len(unbound),
        deferred=deferred,
        untried=untried,
    )


async def _enrich_one(conf_id: str, client: S2Client, data_dir: Path, **kwargs) -> EnrichResult:
    logger.info("Enriching %s...", conf_id)
    try:
        return await enrich_conference(conf_id, client, data_dir, **kwargs)
    except Exception as exc:  # keep going; the summary reports the failure
        # "failed", never "skipped": a skip is a guard doing its job, a
        # failure is a bug or an outage, and the CLI exits non-zero on it.
        logger.exception("Failed to enrich %s", conf_id)
        return EnrichResult(conf_id, "failed", reason=str(exc))


async def enrich_all(
    conf_ids: list[str],
    client: S2Client,
    data_dir: Path,
    *,
    full: bool = False,
    deadline: Deadline = NO_DEADLINE,
    today: date | None = None,
    exempt: frozenset[str] = frozenset(),
) -> list[EnrichResult]:
    """Enrich each conference in turn. One failure never stops the rest.

    With `today` set -- the monthly `--all` run -- archive conferences follow
    `ppr/archive.py`. This month's cohort runs first and batch-only, so its
    cost lands inside the time budget rather than after it; the others are
    reported `not-due` and left untouched. Conferences in `exempt` (a
    re-crawl's `--require`) always get a full enrich, ahead of the other live ones.
    """
    plan = plan_enrich(conf_ids, today, exempt)
    results = []
    for conf_id in order_newest_first(plan.due):
        results.append(await _enrich_one(conf_id, client, data_dir, full=full, batch_only=True))
    # A re-crawled archive id would otherwise sort last and hit the deadline, deferring
    # its misses into next month's untried. It keeps the deadline: the job has a ceiling.
    first = [c for c in plan.live if c in exempt]
    rest = [c for c in plan.live if c not in exempt]
    for conf_id in order_newest_first(first) + order_newest_first(rest):
        results.append(await _enrich_one(conf_id, client, data_dir, full=full, deadline=deadline))
    results.extend(EnrichResult(conf_id, "not-due") for conf_id in sorted(plan.not_due))
    return results


def format_enrich_summary(results: list[EnrichResult]) -> str:
    """Render the per-conference outcome table.

    Skips are printed, not merely logged, so a silently skipped conference can
    never be mistaken for a successful refresh. Failures are counted apart from
    skips: a skip is an expected outcome, a failure needs someone to look.
    Unbound counts bindings severed by verification, so a spike is visible in
    the monthly run rather than only by scripting the data.
    """
    lines = [
        "",
        f"{'Conference':<24} {'Status':<14} {'Path':<11} "
        f"{'Total':>7} {'Refresh':>8} {'Cold':>7} {'Resumed':>8} {'Unbound':>8} {'Deferred':>9}  Note",
        "-" * 122,
    ]
    for r in results:
        if r.status == "not-due":
            continue  # counted in the footer: ~130 identical rows would bury the rest
        lines.append(
            f"{r.conf_id:<24} {r.status:<14} {r.path:<11} "
            f"{r.total:>7} {r.refreshed:>8} {r.cold:>7} {r.resumed:>8} "
            f"{r.unbound:>8} {r.deferred:>9}  {r.reason}"
        )
    skipped = sum(1 for r in results if r.status == "skipped")
    enriched = sum(1 for r in results if r.status == "enriched")
    failed = sum(1 for r in results if r.status == "failed")
    lines.append("")
    not_due = sum(1 for r in results if r.status == "not-due")
    lines.append(
        f"{enriched} enriched, {skipped} skipped, {failed} failed, "
        + (f"{not_due} not due (archive), " if not_due else "")
        + f"{len(results)} total."
    )
    if failed:
        names = ", ".join(r.conf_id for r in results if r.status == "failed")
        lines.append(f"FAILED: {names}")
    deferred = sum(r.deferred for r in results)
    if deferred:
        lines.append(f"Time budget ran out: {deferred} papers deferred to the next run.")
    untried = sum(r.untried for r in results)
    if untried:
        lines.append(
            f"Archive: {untried} unmatched papers left untried "
            "(title matching is off for archive years; `ppr enrich <id>` runs it)."
        )
        mostly = sorted(r.conf_id for r in results if r.untried * 2 > r.total)
        if mostly:
            lines.append(f"Mostly untried (run `ppr enrich <id>`): {', '.join(mostly)}")
    return "\n".join(lines)


def results_to_json(results: list[EnrichResult]) -> str:
    return json.dumps({"results": [asdict(r) for r in results]}, indent=2)
