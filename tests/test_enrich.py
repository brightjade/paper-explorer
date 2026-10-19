import json
import logging

import pytest

from ppr.enrich import (
    apply_enrichment,
    carry_over,
    check_enrichment_coverage,
    read_papers,
    unbind,
)
from ppr.layout import checkpoint_path, papers_path
from ppr.models import Paper
from ppr.store import save_crawl, save_enriched


def _paper(**kw) -> Paper:
    base = dict(title="A Paper", link="L", authors=["X"], selection="oral")
    base.update(kw)
    return Paper(**base)


FULL_ENTRY = {
    "title": "A Paper",
    "citationCount": 42,
    "abstract": "S2 abstract.",
    "influentialCitationCount": 5,
    "referenceCount": 30,
    "tldr": {"model": "tldr@v2", "text": "A summary."},
    "publicationDate": "2025-01-15",
    "fieldsOfStudy": ["Computer Science"],
    "openAccessPdf": {"url": "https://example.com/p.pdf"},
    "externalIds": {"CorpusId": 123, "ArXiv": "2501.00001"},
}


class TestApplyEnrichment:
    def test_a_filled_abstract_is_marked_s2(self):
        assert apply_enrichment(_paper(), FULL_ENTRY).abstract_source == "s2"

    def test_a_kept_abstract_stays_unmarked(self):
        assert apply_enrichment(_paper(abstract="OpenReview abstract"), FULL_ENTRY).abstract_source == ""

    def test_populates_all_enrichment_fields(self):
        p = apply_enrichment(_paper(), FULL_ENTRY)
        assert p.citation_count == 42
        assert p.influential_citation_count == 5
        assert p.reference_count == 30
        assert p.tldr == "A summary."
        assert p.publication_date == "2025-01-15"
        assert p.fields_of_study == ["Computer Science"]
        assert p.open_access_pdf == "https://example.com/p.pdf"
        assert p.external_ids == {"CorpusId": 123, "ArXiv": "2501.00001"}

    def test_fills_abstract_when_empty(self):
        assert apply_enrichment(_paper(), FULL_ENTRY).abstract == "S2 abstract."

    def test_preserves_existing_abstract(self):
        p = apply_enrichment(_paper(abstract="OpenReview abstract"), FULL_ENTRY)
        assert p.abstract == "OpenReview abstract"

    def test_never_touches_crawl_fields(self):
        p = _paper(keywords=["k"], forum_id="fid")
        entry = dict(FULL_ENTRY, title="Totally Different", authors=[{"name": "Z"}])
        apply_enrichment(p, entry)
        assert p.title == "A Paper"
        assert p.authors == ["X"]
        assert p.link == "L"
        assert p.selection == "oral"
        assert p.keywords == ["k"]
        assert p.forum_id == "fid"

    def test_none_entry_leaves_paper_unchanged(self):
        p = _paper(citation_count=99, external_ids={"CorpusId": 7})
        apply_enrichment(p, None)
        assert p.citation_count == 99
        assert p.external_ids == {"CorpusId": 7}

    def test_entry_without_citation_count_leaves_paper_unchanged(self):
        p = _paper(citation_count=99)
        apply_enrichment(p, {"title": "A Paper", "citationCount": None})
        assert p.citation_count == 99

    def test_zero_citations_is_written(self):
        p = apply_enrichment(_paper(citation_count=5), dict(FULL_ENTRY, citationCount=0))
        assert p.citation_count == 0

    def test_empty_tldr_does_not_clear_existing(self):
        p = _paper(tldr="Existing summary")
        apply_enrichment(p, dict(FULL_ENTRY, tldr=None))
        assert p.tldr == "Existing summary"

    def test_tldr_is_overwritten_when_api_has_one(self):
        p = _paper(tldr="Old summary")
        apply_enrichment(p, dict(FULL_ENTRY, tldr={"text": "New summary"}))
        assert p.tldr == "New summary"

    def test_null_nested_objects_are_safe(self):
        p = apply_enrichment(
            _paper(),
            dict(FULL_ENTRY, openAccessPdf=None, fieldsOfStudy=None, externalIds=None,
                 publicationDate=None),
        )
        assert p.open_access_pdf == ""
        assert p.fields_of_study == []
        assert p.external_ids == {}
        assert p.publication_date == ""


def _with_ids(n: int) -> list[Paper]:
    return [_paper(title=f"P{i}", external_ids={"CorpusId": i + 1}) for i in range(n)]


class TestCheckEnrichmentCoverage:
    def test_first_time_enrichment_is_allowed(self):
        assert check_enrichment_coverage(_with_ids(3), []) is None

    def test_zero_prior_coverage_is_allowed(self):
        # A prior file where nothing ever matched has no enrichment to lose.
        assert check_enrichment_coverage([_paper()] * 3, [_paper()] * 3) is None

    def test_total_loss_of_ids_is_blocked(self):
        reason = check_enrichment_coverage([_paper()] * 10, _with_ids(10))
        assert reason is not None
        assert "10" in reason

    def test_coverage_at_exactly_half_is_allowed(self):
        papers = _with_ids(5) + [_paper()] * 5
        assert check_enrichment_coverage(papers, _with_ids(10)) is None

    def test_coverage_just_below_half_is_blocked(self):
        papers = _with_ids(4) + [_paper()] * 6
        assert check_enrichment_coverage(papers, _with_ids(10)) is not None

    def test_growth_in_coverage_is_allowed(self):
        assert check_enrichment_coverage(_with_ids(20), _with_ids(10)) is None


import httpx
import respx

from ppr.enrich import (
    EnrichResult,
    NO_DEADLINE,
    S2_VENUE_NAMES,
    _run_batch,
    _run_title_cold,
    bulk_years,
    corpus_id_of,
    doi_id_of,
    enrich_all,
    enrich_conference,
    route_papers,
)
from ppr.s2_client import BATCH_URL, BULK_URL, MATCH_URL, S2Client


def _write_jsonl(path, papers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(p.to_json() + "\n" for p in papers))


def _conf(tmp_path, conf_id, raw, enriched=None):
    """The year file a crawl of `raw` leaves when `enriched` was on disk before it."""
    path = papers_path(tmp_path, conf_id)
    if enriched is not None:
        save_enriched(enriched, path)
    save_crawl(raw, path)
    return tmp_path


class TestIdExtraction:
    def test_corpus_id(self):
        assert corpus_id_of(_paper(external_ids={"CorpusId": 42})) == "CorpusId:42"

    def test_no_corpus_id(self):
        assert corpus_id_of(_paper()) is None

    def test_doi_from_link(self):
        p = _paper(link="https://doi.org/10.1109/ICRA55743.2025.11127781")
        assert doi_id_of(p) == "DOI:10.1109/ICRA55743.2025.11127781"

    def test_non_doi_link(self):
        assert doi_id_of(_paper(link="https://openreview.net/pdf?id=abc")) is None


class TestRoutePapers:
    def test_known_corpus_id_goes_to_refresh(self):
        raw = [_paper(title="A")]
        prior = {"a": _paper(title="A", external_ids={"CorpusId": 1}, citation_count=5)}
        refresh, doi, title = route_papers(raw, prior, full=False)
        assert [p.title for p in refresh] == ["A"]
        assert (doi, title) == ([], [])
        assert raw[0].citation_count == 5  # carried over

    def test_new_paper_goes_cold(self):
        raw = [_paper(title="New", link="https://openreview.net/pdf?id=z")]
        refresh, doi, title = route_papers(raw, {}, full=False)
        assert [p.title for p in title] == ["New"]
        assert (refresh, doi) == ([], [])

    def test_new_paper_with_doi_goes_id_cold(self):
        raw = [_paper(title="New", link="https://doi.org/10.1/x")]
        refresh, doi, title = route_papers(raw, {}, full=False)
        assert [p.title for p in doi] == ["New"]
        assert title == []

    def test_previously_not_found_is_retried_by_default(self):
        # The whole point of the change: a paper Semantic Scholar could not
        # find last month is asked about again this month, with no flag.
        raw = [_paper(title="A", link="https://openreview.net/pdf?id=z")]
        prior = {"a": _paper(title="A", match_status="not_found")}
        refresh, doi, title = route_papers(raw, prior, full=False)
        assert [p.title for p in title] == ["A"]
        assert refresh == []

    def test_retry_does_not_override_known_corpus_id(self):
        # A known CorpusId means the paper is bound; it belongs on the cheap
        # refresh path, where the binding also gets re-verified.
        raw = [_paper(title="A", link="https://doi.org/10.1/x")]
        prior = {"a": _paper(title="A", external_ids={"CorpusId": 1})}
        refresh, doi, title = route_papers(raw, prior, full=False)
        assert [p.title for p in refresh] == ["A"]
        assert (doi, title) == ([], [])

    def test_full_bypasses_refresh(self):
        raw = [_paper(title="A", link="https://doi.org/10.1/x")]
        prior = {"a": _paper(title="A", external_ids={"CorpusId": 1})}
        refresh, doi, title = route_papers(raw, prior, full=True)
        assert refresh == []
        assert [p.title for p in doi] == ["A"]

    def test_full_does_not_carry_over_prior(self):
        raw = [_paper(title="A")]
        prior = {"a": _paper(title="A", citation_count=999)}
        route_papers(raw, prior, full=True)
        assert raw[0].citation_count is None


class TestEnrichConference:
    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_path_updates_citations(self, tmp_path):
        raw = [_paper(title="A"), _paper(title="B")]
        enriched = [
            _paper(title="A", external_ids={"CorpusId": 1}, citation_count=1),
            _paper(title="B", external_ids={"CorpusId": 2}, citation_count=2),
        ]
        _conf(tmp_path, "iclr_2026", raw, enriched)
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                # The year file is sorted by citations, so B comes first.
                json=[
                    {
                        "title": "B",
                        "citationCount": 200,
                        "externalIds": {"CorpusId": 2},
                    },
                    {
                        "title": "A",
                        "citationCount": 100,
                        "externalIds": {"CorpusId": 1},
                    },
                ],
            )
        )
        result = await enrich_conference(
            "iclr_2026", S2Client(min_interval=0.0), tmp_path
        )
        assert result.status == "enriched"
        assert result.path == "refresh"
        assert result.refreshed == 2
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert [p.title for p in out] == ["B", "A"]  # sorted by citations desc
        assert out[0].citation_count == 200

    @respx.mock
    @pytest.mark.asyncio
    async def test_null_batch_entry_keeps_prior_citations(self, tmp_path):
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="A")],
            [_paper(title="A", external_ids={"CorpusId": 1}, citation_count=77)],
        )
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[None]))
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].citation_count == 77

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_relabels_from_the_verified_response(self, tmp_path):
        # The old behaviour preserved a prior "mismatch" as adjudication
        # history. It was never history — it was a wrong binding being
        # refreshed forever. Refresh now re-decides from what came back.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="A")],
            [_paper(title="A", external_ids={"CorpusId": 1}, match_status="mismatch")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": "A", "citationCount": 5, "externalIds": {"CorpusId": 1},
                       "authors": [{"name": "X"}]}],
            )
        )
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].match_status == "matched"

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_unbinds_a_wrong_binding(self, tmp_path):
        wrong = _paper(title="Bi-VLM: Binary Post-Training Quantization",
                       authors=["Ada Lovelace"])
        right = _paper(title="A Correct Paper", authors=["Grace Hopper"])
        _conf(
            tmp_path,
            "iclr_2026",
            [wrong, right],
            [_paper(title="Bi-VLM: Binary Post-Training Quantization", authors=["Ada Lovelace"],
                    external_ids={"CorpusId": 1}, citation_count=400, tldr="wrong",
                    abstract="Someone else's abstract.", abstract_source="s2",
                    open_access_pdf="http://x/y.pdf",
                    match_status="mismatch"),
             _paper(title="A Correct Paper", authors=["Grace Hopper"],
                    external_ids={"CorpusId": 2}, citation_count=8, match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": "Computing Neighbourhoods with Language Models",
                       "citationCount": 400, "externalIds": {"CorpusId": 1},
                       "authors": [{"name": "Alan Turing"}]},
                      {"title": "A Correct Paper", "citationCount": 8,
                       "externalIds": {"CorpusId": 2},
                       "authors": [{"name": "Grace Hopper"}]}],
            )
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "iclr_2026"))}
        assert result.status == "enriched"
        severed = out["Bi-VLM: Binary Post-Training Quantization"]
        assert severed.match_status == "not_found"
        assert severed.citation_count is None
        assert severed.external_ids == {}
        assert severed.tldr == ""
        assert severed.open_access_pdf == ""
        assert severed.abstract == ""  # the crawl had none
        assert out["A Correct Paper"].external_ids == {"CorpusId": 2}
        assert result.unbound == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_accepts_a_drifted_title_on_shared_authors(self, tmp_path):
        # match_verdict only reaches its author-weighted branch when the title
        # is not an exact match. Every other refresh fixture in this file uses
        # an exact title (which short-circuits before authors are consulted)
        # or a reject that rejects with or without them — so passing `[]`
        # instead of `paper.authors` at the call site would go unnoticed.
        # This title drifts just enough that the verdict depends on whether
        # the real author list reaches match_verdict.
        ours_title = (
            "Align Your Trajectory Tangent: Training Better Consistency "
            "Models via Manifold-Aligned Tangents"
        )
        drifted_title = (
            "Align Your Tangent: Training Better Consistency Models via "
            "Manifold-Aligned Tangents"
        )
        authors = ["Ada Lovelace", "Grace Hopper"]
        # "Companion" keeps coverage at 50% (same trick as
        # test_null_entry_never_unbinds) so a wrongly unbound target paper
        # cannot hide behind check_enrichment_coverage's skip.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title=ours_title, authors=authors),
             _paper(title="Companion", authors=["Alan Turing"])],
            [_paper(title=ours_title, authors=authors,
                    external_ids={"CorpusId": 1}, citation_count=10,
                    match_status="matched"),
             _paper(title="Companion", authors=["Alan Turing"],
                    external_ids={"CorpusId": 2}, citation_count=5,
                    match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"title": drifted_title, "citationCount": 15,
                     "externalIds": {"CorpusId": 1},
                     "authors": [{"name": n} for n in authors]},
                    {"title": "Companion", "citationCount": 5,
                     "externalIds": {"CorpusId": 2},
                     "authors": [{"name": "Alan Turing"}]},
                ],
            )
        )
        # If authors were dropped before reaching match_verdict, the paper
        # would be rejected and unbound, then retried cold — mock that path
        # too so the failure is a clean assertion mismatch rather than an
        # unmocked-request crash.
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "iclr_2026"))}
        assert result.status == "enriched"
        assert out[ours_title].match_status == "matched_fuzzy"
        assert out[ours_title].citation_count == 15
        assert result.unbound == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_fuzzy_verdicts_are_logged_per_conference(
        self, tmp_path, caplog
    ):
        # The design spec wants matched_fuzzy counted and logged per
        # conference so a spike is visible as a trend. The plan narrowed that
        # to the title-cold path, but refresh is where the large majority of
        # fuzzy verdicts land — a log that counts only title-cold's fuzzy
        # matches would miss most of what the spec wants tracked.
        ours_title = (
            "Align Your Trajectory Tangent: Training Better Consistency "
            "Models via Manifold-Aligned Tangents"
        )
        drifted_title = (
            "Align Your Tangent: Training Better Consistency Models via "
            "Manifold-Aligned Tangents"
        )
        authors = ["Ada Lovelace", "Grace Hopper"]
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title=ours_title, authors=authors)],
            [_paper(title=ours_title, authors=authors,
                    external_ids={"CorpusId": 1}, citation_count=10,
                    match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": drifted_title, "citationCount": 15,
                       "externalIds": {"CorpusId": 1},
                       "authors": [{"name": n} for n in authors]}],
            )
        )
        with caplog.at_level(logging.INFO, logger="ppr.enrich"):
            await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        assert "iclr_2026: 1 papers matched on fuzzy evidence" in caplog.text

    @respx.mock
    @pytest.mark.asyncio
    async def test_unbind_restores_the_crawl_abstract(self, tmp_path):
        # OpenReview supplies abstracts; S2 only fills the blanks. Clearing
        # outright would blank a legitimate abstract until next month's crawl
        # read restores it.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"], abstract="Ours, from OpenReview."),
             _paper(title="A Correct Paper", authors=["Grace Hopper"])],
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"], abstract="Ours, from OpenReview.",
                    external_ids={"CorpusId": 1}, citation_count=90, match_status="mismatch"),
             _paper(title="A Correct Paper", authors=["Grace Hopper"],
                    external_ids={"CorpusId": 2}, citation_count=8, match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": "Floorplan Generation with Graph Beta Diffusion",
                       "citationCount": 90, "externalIds": {"CorpusId": 1},
                       "authors": [{"name": "Alan Turing"}]},
                      {"title": "A Correct Paper", "citationCount": 8,
                       "externalIds": {"CorpusId": 2},
                       "authors": [{"name": "Grace Hopper"}]}],
            )
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "iclr_2026"))}
        # Without these, a verified (never-unbound) "Beta Diffusion" would pass
        # too: apply_enrichment only fills an empty abstract, so a bound
        # paper's OpenReview abstract survives untouched either way. These
        # confirm unbind is what ran, not a no-op.
        assert result.unbound == 1
        assert out["Beta Diffusion"].match_status == "not_found"
        assert out["Beta Diffusion"].abstract == "Ours, from OpenReview."

    @respx.mock
    @pytest.mark.asyncio
    async def test_unbound_paper_is_retried_in_the_same_run(self, tmp_path):
        # Most will draw the same wrong neighbour and be rejected again — a
        # handful of wasted requests. But a paper S2 has since indexed properly
        # recovers now instead of waiting a month.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"])],
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"],
                    external_ids={"CorpusId": 1}, citation_count=90, match_status="mismatch")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": "Floorplan Generation with Graph Beta Diffusion",
                       "citationCount": 90, "externalIds": {"CorpusId": 1},
                       "authors": [{"name": "Alan Turing"}]}],
            )
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"title": "Beta Diffusion", "citationCount": 3,
                                "externalIds": {"CorpusId": 42},
                                "authors": [{"name": "Ada Lovelace"}]}]},
            )
        )
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        # Guards against the plan's recurring trap: a coverage-guard skip
        # leaves papers_enriched.jsonl untouched and defaults `unbound` to 0,
        # so a fixture whose only paper does not rebind would pass every
        # assertion below without the cold retry ever running. This one
        # rebinds to a new CorpusId, keeping coverage at 1/1 and clearing the
        # guard — but assert the status directly rather than trust that.
        assert result.status == "enriched"
        assert out[0].match_status == "matched"
        assert out[0].external_ids == {"CorpusId": 42}
        assert out[0].citation_count == 3
        assert result.unbound == 1
        assert result.total == result.refreshed + result.cold + result.resumed

    @respx.mock
    @pytest.mark.asyncio
    async def test_unbound_paper_is_not_checkpointed_by_refresh(self, tmp_path):
        # If refresh checkpointed the severed paper, a crash before the cold
        # stage would leave the next run restoring it as finished — frozen
        # unbound and never retried. It is recorded only once cold finishes it.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"]),
             _paper(title="A Correct Paper", authors=["Grace Hopper"])],
            [_paper(title="Beta Diffusion", authors=["Ada Lovelace"],
                    external_ids={"CorpusId": 1}, citation_count=90, match_status="mismatch"),
             _paper(title="A Correct Paper", authors=["Grace Hopper"],
                    external_ids={"CorpusId": 2}, citation_count=8, match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"title": "Floorplan Generation with Graph Beta Diffusion",
                       "citationCount": 90, "externalIds": {"CorpusId": 1},
                       "authors": [{"name": "Alan Turing"}]},
                      {"title": "A Correct Paper", "citationCount": 8,
                       "externalIds": {"CorpusId": 2},
                       "authors": [{"name": "Grace Hopper"}]}],
            )
        )
        recorded = []
        client = S2Client(min_interval=0.0)
        papers = read_papers(papers_path(tmp_path, "iclr_2026"))
        for p in papers:
            if p.title == "Beta Diffusion":
                p.external_ids = {"CorpusId": 1}
            elif p.title == "A Correct Paper":
                p.external_ids = {"CorpusId": 2}
        async with httpx.AsyncClient() as http:
            await _run_batch(
                client,
                http,
                papers,
                corpus_id_of,
                mode="verify",
                record=recorded.extend,
            )
        assert [p.title for p in recorded] == ["A Correct Paper"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_null_entry_never_unbinds(self, tmp_path):
        # get_batch fills a whole failed chunk with None. Reading that as a
        # failed verification would sever 500 papers over one HTTP hiccup.
        #
        # A one-paper fixture cannot catch a regression here: unbinding its
        # only paper drops coverage to 0%, check_enrichment_coverage skips the
        # run, and the untouched fixture file is read back looking exactly
        # like a paper that was never unbound at all — every assertion below
        # would still pass. "Companion" keeps coverage at 50% so a wrongly
        # severed "A" cannot hide behind the guard, and asserting "enriched"
        # rules out the skip path directly.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="A"), _paper(title="Companion")],
            [_paper(title="A", external_ids={"CorpusId": 1}, citation_count=77,
                    match_status="matched"),
             _paper(title="Companion", external_ids={"CorpusId": 2}, citation_count=5,
                    match_status="matched")],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    None,
                    {"title": "Companion", "citationCount": 5,
                     "externalIds": {"CorpusId": 2}, "authors": [{"name": "X"}]},
                ],
            )
        )
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "iclr_2026"))}
        assert result.status == "enriched"
        assert out["A"].citation_count == 77
        assert out["A"].external_ids == {"CorpusId": 1}
        assert out["A"].match_status == "matched"
        assert result.unbound == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_null_entry_does_not_flip_match_status(self, tmp_path):
        # A batch entry of None on refresh must not be read as "not_found" —
        # that labelling belongs only to title matching, which has asked.
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="A")],
            [_paper(title="A", external_ids={"CorpusId": 1}, match_status="matched")],
        )
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[None]))
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].match_status == "matched"

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_path_posts_corpus_ids(self, tmp_path):
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="A"), _paper(title="B")],
            [
                _paper(title="A", external_ids={"CorpusId": 1}),
                _paper(title="B", external_ids={"CorpusId": 2}),
            ],
        )
        route = respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"title": "A", "citationCount": 1, "externalIds": {"CorpusId": 1}},
                    {"title": "B", "citationCount": 2, "externalIds": {"CorpusId": 2}},
                ],
            )
        )
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        import json as _json

        assert _json.loads(route.calls[0].request.content)["ids"] == [
            "CorpusId:1",
            "CorpusId:2",
        ]

    @respx.mock
    @pytest.mark.asyncio
    async def test_id_cold_path_uses_doi(self, tmp_path):
        _conf(
            tmp_path,
            "icra_2026",
            [_paper(title="A", link="https://doi.org/10.1/x")],
        )
        route = respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200, json=[{"title": "A", "citationCount": 9}]
            )
        )
        result = await enrich_conference(
            "icra_2026", S2Client(min_interval=0.0), tmp_path
        )
        assert result.path == "id-cold"
        assert result.cold == 1
        import json as _json

        assert _json.loads(route.calls[0].request.content)["ids"] == ["DOI:10.1/x"]
        out = read_papers(papers_path(tmp_path, "icra_2026"))
        assert out[0].citation_count == 9
        assert out[0].match_status == "matched"

    @respx.mock
    @pytest.mark.asyncio
    async def test_doi_miss_falls_back_to_title_matching(self, tmp_path):
        # DBLP records DOIs Semantic Scholar never linked to its paper (most of
        # ECCV and EMNLP 2022). A DOI it does not know is not a paper it lacks.
        _conf(tmp_path, "eccv_2022", [
            _paper(title="Known DOI", link="https://doi.org/10.1/a"),
            _paper(title="In Bulk", link="https://doi.org/10.1/b"),
            _paper(title="By Title", link="https://doi.org/10.1/c", authors=["Ann Lee"]),
        ])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[
            {"title": "Known DOI", "citationCount": 1}, None, None,
        ]))
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={
            "total": 1, "data": [{"title": "In Bulk", "citationCount": 2}],
        }))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={
            "data": [{"title": "By Title", "citationCount": 3,
                      "authors": [{"name": "Ann Lee"}]}],
        }))

        result = await enrich_conference("eccv_2022", S2Client(min_interval=0.0), tmp_path)

        assert match.call_count == 1  # only the paper neither the DOI nor bulk found
        assert (result.total, result.cold) == (3, 3)  # a fallback is not a second paper
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "eccv_2022"))}
        assert [(t, out[t].citation_count, out[t].match_status) for t in sorted(out)] == [
            ("By Title", 3, "matched"),
            ("In Bulk", 2, "matched"),
            ("Known DOI", 1, "matched"),
        ]

    @respx.mock
    @pytest.mark.asyncio
    async def test_doi_miss_that_title_matching_rejects_is_not_found(self, tmp_path):
        _conf(tmp_path, "icra_2022", [_paper(title="Unindexed", link="https://doi.org/10.1/a")])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[None]))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={
            "data": [{"title": "A Different Paper Entirely", "citationCount": 99}],
        }))

        await enrich_conference("icra_2022", S2Client(min_interval=0.0), tmp_path)

        assert match.called
        out = read_papers(papers_path(tmp_path, "icra_2022"))
        assert (out[0].citation_count, out[0].match_status) == (None, "not_found")

    @respx.mock
    @pytest.mark.asyncio
    async def test_doi_miss_past_the_deadline_is_deferred(self, tmp_path):
        _conf(tmp_path, "icra_2022", [_paper(title="Miss", link="https://doi.org/10.1/a")])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[None]))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "icra_2022", S2Client(min_interval=0.0), tmp_path, deadline=_passed()
        )

        assert (result.cold, result.deferred) == (1, 1)
        assert not match.called
        out = read_papers(papers_path(tmp_path, "icra_2022"))
        assert out[0].match_status != "matched"

    @respx.mock
    @pytest.mark.asyncio
    async def test_failed_doi_chunk_goes_to_title_matching(self, tmp_path):
        _conf(tmp_path, "icra_2022", [_paper(title="A", link="https://doi.org/10.1/a",
                                             authors=["Ann Lee"])])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json={"error": "odd"}))
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={
            "data": [{"title": "A", "citationCount": 4, "authors": [{"name": "Ann Lee"}]}],
        }))

        await enrich_conference("icra_2022", S2Client(min_interval=0.0), tmp_path)

        out = read_papers(papers_path(tmp_path, "icra_2022"))
        assert (out[0].citation_count, out[0].match_status) == (4, "matched")

    @respx.mock
    @pytest.mark.asyncio
    async def test_unbound_paper_whose_doi_misses_is_title_matched(self, tmp_path):
        _conf(
            tmp_path, "icra_2022",
            [_paper(title="Ours", link="https://doi.org/10.1/a", authors=["Ann Lee"])],
            [_paper(title="Ours", external_ids={"CorpusId": 1}, citation_count=50,
                    match_status="matched")],
        )

        def _batch(request):
            ids = json.loads(request.content)["ids"]
            if ids == ["CorpusId:1"]:
                return httpx.Response(200, json=[{"title": "A Stranger's Paper",
                                                  "authors": [{"name": "Bo Kim"}],
                                                  "externalIds": {"CorpusId": 1}}])
            return httpx.Response(200, json=[None])

        respx.post(BATCH_URL).mock(side_effect=_batch)
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={
            "data": [{"title": "Ours", "citationCount": 6, "authors": [{"name": "Ann Lee"}],
                      "externalIds": {"CorpusId": 2}}],
        }))

        result = await enrich_conference("icra_2022", S2Client(min_interval=0.0), tmp_path)

        assert result.unbound == 1
        out = read_papers(papers_path(tmp_path, "icra_2022"))
        assert (out[0].citation_count, out[0].external_ids, out[0].match_status) == (
            6, {"CorpusId": 2}, "matched")

    @respx.mock
    @pytest.mark.asyncio
    async def test_doi_miss_is_checkpointed_only_after_its_title_retry(self, tmp_path):
        # Like an unbound paper: a kill between the DOI miss and its title retry
        # must leave it to be asked again, not frozen as not_found.
        _conf(tmp_path, "icra_2022", [
            _paper(title="Hit", link="https://doi.org/10.1/a"),
            _paper(title="Miss", link="https://doi.org/10.1/b"),
        ])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[
            {"title": "Hit", "citationCount": 1}, None,
        ]))
        respx.get(MATCH_URL).mock(side_effect=RuntimeError("killed"))

        with pytest.raises(RuntimeError):
            await enrich_conference("icra_2022", S2Client(min_interval=0.0), tmp_path)

        done = read_papers(checkpoint_path(tmp_path, "icra_2022"))
        assert [p.title for p in done] == ["Hit"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_title_cold_uses_bulk_then_falls_back_to_match(self, tmp_path):
        _conf(
            tmp_path,
            "icml_2026",
            [
                _paper(title="In Bulk", link="https://openreview.net/pdf?id=a"),
                _paper(title="Not In Bulk", link="https://openreview.net/pdf?id=b"),
            ],
        )
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(
                200,
                json={"total": 1, "data": [{"title": "in bulk", "citationCount": 11}]},
            )
        )
        match_route = respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200, json={"data": [{"title": "Not In Bulk", "citationCount": 22}]}
            )
        )
        result = await enrich_conference(
            "icml_2026", S2Client(min_interval=0.0), tmp_path
        )
        assert result.path == "title-cold"
        assert match_route.call_count == 1  # only the bulk miss
        out = {p.title: p for p in read_papers(
            papers_path(tmp_path, "icml_2026")
        )}
        assert out["In Bulk"].citation_count == 11
        assert out["In Bulk"].match_status == "matched"
        assert out["Not In Bulk"].citation_count == 22

    @respx.mock
    @pytest.mark.asyncio
    async def test_unknown_venue_skips_bulk(self, tmp_path):
        _conf(tmp_path, "notavenue_2026", [_paper(title="A", link="x")])
        bulk = respx.get(BULK_URL)
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200, json={"data": [{"title": "A", "citationCount": 1}]}
            )
        )
        await enrich_conference("notavenue_2026", S2Client(min_interval=0.0), tmp_path)
        assert bulk.call_count == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_bulk_prefetch_matches_through_punctuation(self, tmp_path):
        # Keyed by normalize_title this missed and fell through to the ~0.3
        # req/s per-title path. title_key keeps it in the cheap bulk path.
        _conf(tmp_path, "iclr_2026", [_paper(title="A Study: Part One")])
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"title": "A Study : Part One.", "citationCount": 7,
                                "externalIds": {"CorpusId": 5}}]},
            )
        )
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        assert match.call_count == 0
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].match_status == "matched"
        assert out[0].citation_count == 7

    @respx.mock
    @pytest.mark.asyncio
    async def test_title_cold_rejects_a_wrong_neighbour(self, tmp_path):
        # /search/match returns the nearest neighbour, not nothing, for a paper
        # S2 has not indexed. Binding to it is how wrong records are born.
        _conf(tmp_path, "iclr_2026", [_paper(title="Beta Diffusion", authors=["Ada Lovelace"])])
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{
                    "title": "Floorplan Generation with Graph Beta Diffusion",
                    "citationCount": 300,
                    "externalIds": {"CorpusId": 999},
                    "authors": [{"name": "Alan Turing"}],
                }]},
            )
        )
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].match_status == "not_found"
        assert out[0].citation_count is None
        assert out[0].external_ids == {}

    @respx.mock
    @pytest.mark.asyncio
    async def test_title_cold_accepts_a_fuzzy_match(self, tmp_path):
        _conf(tmp_path, "iclr_2026",
              [_paper(title="A Survey of Agents", authors=["Ada Lovelace"])])
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{
                    "title": "A Survey of Agents: How Far Are We?",
                    "citationCount": 12,
                    "externalIds": {"CorpusId": 4},
                    "authors": [{"name": "Ada Lovelace"}],
                }]},
            )
        )
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert out[0].match_status == "matched_fuzzy"
        assert out[0].citation_count == 12

    @respx.mock
    @pytest.mark.asyncio
    async def test_full_run_against_a_dry_api_does_not_wipe_enrichment(self, tmp_path):
        # --full routes every paper cold. If the API then answers nothing, each
        # paper would be written back with citations, tldr and external IDs
        # blank while the paper count is unchanged — invisible to save_crawl's paper-count guard.
        enriched = [
            _paper(
                title=f"P{i}",
                external_ids={"CorpusId": i + 1},
                citation_count=i,
                tldr="Prior summary",
            )
            for i in range(10)
        ]
        _conf(tmp_path, "iclr_2026", [_paper(title=f"P{i}") for i in range(10)], enriched)
        path = papers_path(tmp_path, "iclr_2026")
        before = path.read_bytes()
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "iclr_2026", S2Client(min_interval=0.0), tmp_path, full=True
        )

        assert result.status == "skipped"
        assert result.reason
        assert path.read_bytes() == before

    @respx.mock
    @pytest.mark.asyncio
    async def test_first_time_enrichment_is_written_even_when_api_is_dry(self, tmp_path):
        _conf(tmp_path, "iclr_2026", [_paper(title=f"P{i}") for i in range(10)])
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "iclr_2026", S2Client(min_interval=0.0), tmp_path
        )

        assert result.status == "enriched"
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert len(out) == 10

    @respx.mock
    @pytest.mark.asyncio
    async def test_healthy_refresh_still_writes(self, tmp_path):
        enriched = [
            _paper(title=f"P{i}", external_ids={"CorpusId": i + 1}, citation_count=i)
            for i in range(10)
        ]
        _conf(tmp_path, "iclr_2026", [_paper(title=f"P{i}") for i in range(10)], enriched)

        def _respond(request):
            import json as _json

            ids = _json.loads(request.content)["ids"]
            return httpx.Response(
                200,
                json=[
                    {
                        # Corpus ID n was assigned to title P{n-1}; echoing the
                        # matching title (rather than the id itself) is what
                        # makes this binding survive verification.
                        "title": f"P{int(i.split(':')[1]) - 1}",
                        "citationCount": 50,
                        "externalIds": {"CorpusId": int(i.split(":")[1])},
                    }
                    for i in ids
                ],
            )

        respx.post(BATCH_URL).mock(side_effect=_respond)
        result = await enrich_conference(
            "iclr_2026", S2Client(min_interval=0.0), tmp_path
        )

        assert result.status == "enriched"
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert all(p.citation_count == 50 for p in out)

    @pytest.mark.asyncio
    async def test_missing_conference_is_nothing_to_do(self, tmp_path):
        result = await enrich_conference(
            "ghost_2026", S2Client(min_interval=0.0), tmp_path
        )
        assert result.status == "nothing-to-do"

    @respx.mock
    @pytest.mark.asyncio
    async def test_paper_removed_from_raw_is_dropped(self, tmp_path):
        _conf(
            tmp_path,
            "iclr_2026",
            [_paper(title="Keep")],
            [
                _paper(title="Keep", external_ids={"CorpusId": 1}),
                _paper(title="Gone", external_ids={"CorpusId": 2}),
            ],
        )
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "title": "Keep",
                        "citationCount": 1,
                        "externalIds": {"CorpusId": 1},
                    }
                ],
            )
        )
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        out = read_papers(papers_path(tmp_path, "iclr_2026"))
        assert [p.title for p in out] == ["Keep"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_mixed_refresh_and_new_papers_in_one_run(self, tmp_path):
        _conf(
            tmp_path,
            "icra_2026",
            [
                _paper(title="Old", link="https://doi.org/10.1/old"),
                _paper(title="New", link="https://doi.org/10.1/new"),
            ],
            [_paper(title="Old", external_ids={"CorpusId": 1}, citation_count=1)],
        )

        def _respond(request):
            import json as _json

            ids = _json.loads(request.content)["ids"]
            # The refresh leg (CorpusId:1) must echo "Old"'s real title, or
            # verification rejects it as a stranger and this stops testing a
            # refresh at all — see test_healthy_refresh_still_writes for the
            # same mistake.
            titles = {"CorpusId:1": "Old", "DOI:10.1/new": "New"}
            return httpx.Response(
                200,
                json=[
                    {
                        "title": titles.get(i, i),
                        "citationCount": 5,
                        "externalIds": {"CorpusId": n},
                    }
                    for n, i in enumerate(ids, start=1)
                ],
            )

        respx.post(BATCH_URL).mock(side_effect=_respond)
        result = await enrich_conference(
            "icra_2026", S2Client(min_interval=0.0), tmp_path
        )
        assert result.refreshed == 1
        assert result.cold == 1
        assert result.total == 2
        assert result.unbound == 0


class TestEnrichResume:
    @respx.mock
    @pytest.mark.asyncio
    async def test_resume_after_an_unbind_drops_the_strangers_abstract(self, tmp_path):
        """A checkpointed paper restores onto its crawl view, not onto the stale file.

        The year file holds a wrong binding whose abstract came from Semantic
        Scholar. The killed run unbinds it and finds the right record; the
        resume must not let the file's stale abstract outlive that.
        """
        def _year_file(conf_id):
            save_enriched([
                _paper(title="Wrong", link="https://doi.org/10.1/w", authors=["Ada Lovelace"],
                       external_ids={"CorpusId": 1},
                       citation_count=400, abstract="Someone else's abstract.",
                       abstract_source="s2", match_status="matched"),
                _paper(title="Right", authors=["Grace Hopper"], external_ids={"CorpusId": 2},
                       citation_count=8, match_status="matched"),
                _paper(title="New", authors=["Alan Kay"]),
            ], papers_path(tmp_path, conf_id))

        def _batch(request):
            ids = json.loads(request.content)["ids"]
            if not ids[0].startswith("CorpusId"):
                # The unbound paper's DOI: the record it really is.
                return httpx.Response(200, json=[{
                    "title": "Wrong", "citationCount": 5, "abstract": "The correct abstract.",
                    "externalIds": {"CorpusId": 42}, "authors": [{"name": "Ada Lovelace"}]}])
            entries = {
                "CorpusId:1": {"title": "Computing Neighbourhoods", "citationCount": 400,
                               "externalIds": {"CorpusId": 1}, "authors": [{"name": "Alan Turing"}]},
                "CorpusId:2": {"title": "Right", "citationCount": 9,
                               "externalIds": {"CorpusId": 2}, "authors": [{"name": "Grace Hopper"}]},
            }
            return httpx.Response(200, json=[entries[i] for i in ids])

        state = {"die": False}

        def _match(request):
            if state["die"]:
                raise RuntimeError("killed")
            return httpx.Response(200, json={"data": []})

        respx.post(BATCH_URL).mock(side_effect=_batch)
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        respx.get(MATCH_URL).mock(side_effect=_match)

        _year_file("clean_2026")
        await enrich_conference("clean_2026", S2Client(min_interval=0.0), tmp_path)

        _year_file("resumed_2026")
        state["die"] = True
        with pytest.raises(RuntimeError):
            await enrich_conference("resumed_2026", S2Client(min_interval=0.0), tmp_path)
        state["die"] = False
        await enrich_conference("resumed_2026", S2Client(min_interval=0.0), tmp_path)

        clean = {p.title: p for p in read_papers(papers_path(tmp_path, "clean_2026"))}
        resumed = {p.title: p for p in read_papers(papers_path(tmp_path, "resumed_2026"))}
        assert clean["Wrong"].abstract == "The correct abstract."
        assert resumed["Wrong"].to_dict() == clean["Wrong"].to_dict()

    @respx.mock
    @pytest.mark.asyncio
    async def test_checkpoint_is_written_as_work_completes(self, tmp_path):
        """The point of the checkpoint is to survive a kill, so it must exist mid-run."""
        _conf(tmp_path, "icml_2026", [
            _paper(title="A", link="https://openreview.net/pdf?id=a"),
            _paper(title="B", link="https://openreview.net/pdf?id=b"),
        ])
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        seen = []

        def _match(request):
            ckpt = checkpoint_path(tmp_path, "icml_2026")
            seen.append(len(ckpt.read_text().splitlines()) if ckpt.exists() else 0)
            return httpx.Response(200, json={"data": [{"title": "T", "citationCount": 1}]})

        respx.get(MATCH_URL).mock(side_effect=_match)
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)
        assert seen == [0, 1], "checkpoint must grow between lookups, not only at the end"

    @respx.mock
    @pytest.mark.asyncio
    async def test_resume_skips_papers_already_in_the_checkpoint(self, tmp_path):
        _conf(tmp_path, "icml_2026", [_paper(title="Done"), _paper(title="Todo")])
        _write_jsonl(
            checkpoint_path(tmp_path, "icml_2026"),
            [_paper(title="Done", citation_count=42)],
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        route = respx.get(MATCH_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"title": "Todo", "citationCount": 7}]})
        )
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)

        assert route.call_count == 1, "the completed paper must not be looked up again"
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "icml_2026"))}
        assert out["Done"].citation_count == 42
        assert out["Todo"].citation_count == 7

    @respx.mock
    @pytest.mark.asyncio
    async def test_checkpoint_is_removed_on_success(self, tmp_path):
        _conf(tmp_path, "icml_2026", [_paper(title="A")])
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"title": "A", "citationCount": 1}]})
        )
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)
        assert not (checkpoint_path(tmp_path, "icml_2026")).exists()

    @respx.mock
    @pytest.mark.asyncio
    async def test_full_discards_a_stale_checkpoint(self, tmp_path):
        """--full exists to throw prior enrichment away; resuming onto it would defeat that."""
        _conf(tmp_path, "icml_2026", [_paper(title="A")])
        _write_jsonl(
            checkpoint_path(tmp_path, "icml_2026"),
            [_paper(title="A", citation_count=999)],
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"title": "A", "citationCount": 5}]})
        )
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path, full=True)
        out = read_papers(papers_path(tmp_path, "icml_2026"))
        assert out[0].citation_count == 5

    @respx.mock
    @pytest.mark.asyncio
    async def test_checkpoint_cannot_resurrect_a_paper_dropped_from_raw(self, tmp_path):
        """papers.jsonl stays authoritative for membership, checkpoint or not."""
        _conf(tmp_path, "icml_2026", [_paper(title="Keep")])
        _write_jsonl(
            checkpoint_path(tmp_path, "icml_2026"),
            [_paper(title="Keep", citation_count=1), _paper(title="Gone", citation_count=2)],
        )
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)
        titles = [p.title for p in read_papers(papers_path(tmp_path, "icml_2026"))]
        assert titles == ["Keep"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_resumed_output_equals_uninterrupted_output(self, tmp_path):
        """A resumed run must produce exactly what one clean run would.

        The checkpoint here is not hand-written: the first attempt is killed
        partway through, the way the usenix_security_2026 run was, so the file
        the resume reads back is one this code really produced.
        """
        papers = [_paper(title=f"P{i}") for i in range(4)]
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
        state = {"n": 0, "die_on": None}

        def _match(request):
            state["n"] += 1
            if state["n"] == state["die_on"]:
                raise RuntimeError("killed")
            return httpx.Response(200, json={"data": [{"title": "x", "citationCount": 3}]})

        respx.get(MATCH_URL).mock(side_effect=_match)

        _conf(tmp_path, "clean_2026", papers)
        await enrich_conference("clean_2026", S2Client(min_interval=0.0), tmp_path)
        assert state["n"] == 4

        _conf(tmp_path, "resumed_2026", papers)
        crawled = papers_path(tmp_path, "resumed_2026").read_bytes()
        state["n"], state["die_on"] = 0, 3  # die once P0 and P1 are recorded
        with pytest.raises(RuntimeError):
            await enrich_conference("resumed_2026", S2Client(min_interval=0.0), tmp_path)
        ckpt = checkpoint_path(tmp_path, "resumed_2026")
        assert len(ckpt.read_text().splitlines()) == 2
        assert papers_path(tmp_path, "resumed_2026").read_bytes() == crawled

        state["n"], state["die_on"] = 0, None
        await enrich_conference("resumed_2026", S2Client(min_interval=0.0), tmp_path)
        assert state["n"] == 2, "only the two unfinished papers may be looked up"

        clean = (papers_path(tmp_path, "clean_2026")).read_text()
        resumed = (papers_path(tmp_path, "resumed_2026")).read_text()
        assert clean == resumed

    @respx.mock
    @pytest.mark.asyncio
    async def test_batch_path_progress_survives_a_kill_in_a_later_path(self, tmp_path):
        """A conference mixing paths must not lose its finished batch work."""
        _conf(tmp_path, "icml_2026", [
            _paper(title="ById", link="https://doi.org/10.1/a"),
            _paper(title="ByTitle", link="https://openreview.net/pdf?id=b"),
        ])
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(200, json=[{"title": "ById", "citationCount": 4}])
        )
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        respx.get(MATCH_URL).mock(side_effect=RuntimeError("killed"))

        with pytest.raises(RuntimeError):
            await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)

        done = read_papers(checkpoint_path(tmp_path, "icml_2026"))
        assert [p.title for p in done] == ["ById"]
        assert done[0].citation_count == 4

    @respx.mock
    @pytest.mark.asyncio
    async def test_checkpointed_not_found_is_honoured_on_resume(self, tmp_path):
        # Deliberate, and it reads like a bug without this note: retry happens
        # BETWEEN runs, never within one. A six-hour run killed at hour five
        # must not re-ask about the papers it just failed to find — a paper
        # absent from Semantic Scholar ten minutes ago is still absent now.
        _conf(tmp_path, "iclr_2026", [_paper(title="A")])
        checkpoint_path(tmp_path, "iclr_2026").write_text(
            _paper(title="A", match_status="not_found").to_json() + "\n"
        )
        route = respx.get(MATCH_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"title": "A", "citationCount": 9}]})
        )
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        assert route.call_count == 0
        assert result.resumed == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_resuming_twice_across_a_torn_line_loses_nothing(self, tmp_path):
        """Appending onto a torn line would swallow the next good record."""
        _conf(tmp_path, "icml_2026", [
            _paper(title="A"), _paper(title="B"), _paper(title="C")
        ])
        ckpt = checkpoint_path(tmp_path, "icml_2026")
        _write_jsonl(ckpt, [_paper(title="A", citation_count=1, match_status="matched")])
        with open(ckpt, "a", encoding="utf-8") as f:
            f.write('{"title": "B", "link": "L", "citation_c')  # killed mid-write

        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        state = {"die_on": "C", "queried": []}

        def _match(request):
            title = request.url.params["query"]
            state["queried"].append(title)
            if title == state["die_on"]:
                raise RuntimeError("killed")
            return httpx.Response(
                200, json={"data": [{"title": title, "citationCount": 9}]}
            )

        respx.get(MATCH_URL).mock(side_effect=_match)

        # First resume: B is looked up and recorded, then the run dies on C.
        with pytest.raises(RuntimeError):
            await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)
        assert state["queried"] == ["B", "C"]

        # Second resume: B's record must have survived the torn line.
        state["die_on"], state["queried"] = None, []
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)
        assert state["queried"] == ["C"], "B was recorded and must not be redone"

        out = {p.title: p for p in read_papers(
            papers_path(tmp_path, "icml_2026")
        )}
        assert out["A"].citation_count == 1
        assert out["B"].citation_count == 9
        assert out["C"].citation_count == 9

    @pytest.mark.asyncio
    async def test_nothing_to_do_discards_a_stale_checkpoint(self, tmp_path):
        """The one success path the delete-on-success rule would otherwise miss."""
        _conf(tmp_path, "ghost_2026", [])
        ckpt = checkpoint_path(tmp_path, "ghost_2026")
        _write_jsonl(ckpt, [_paper(title="Ghost", citation_count=1)])

        result = await enrich_conference(
            "ghost_2026", S2Client(min_interval=0.0), tmp_path
        )

        assert result.status == "nothing-to-do"
        assert not ckpt.exists()

    @respx.mock
    @pytest.mark.asyncio
    async def test_half_written_last_line_is_ignored(self, tmp_path):
        """A killed process can leave a partial line; it must not fail the run."""
        _conf(tmp_path, "icml_2026", [_paper(title="Done"), _paper(title="Torn")])
        ckpt = checkpoint_path(tmp_path, "icml_2026")
        _write_jsonl(ckpt, [_paper(title="Done", citation_count=42)])
        with open(ckpt, "a", encoding="utf-8") as f:
            f.write('{"title": "Torn", "link": "L", "citation_c')

        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        route = respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200, json={"data": [{"title": "Torn", "citationCount": 7}]}
            )
        )
        await enrich_conference("icml_2026", S2Client(min_interval=0.0), tmp_path)

        assert route.call_count == 1, "only the torn paper is looked up again"
        out = {p.title: p for p in read_papers(
            papers_path(tmp_path, "icml_2026")
        )}
        assert out["Done"].citation_count == 42
        assert out["Torn"].citation_count == 7

    @respx.mock
    @pytest.mark.asyncio
    async def test_checkpoint_is_discarded_when_a_guard_rejects_the_run(self, tmp_path):
        """The guard says retry; a kept checkpoint would make retrying impossible.

        The checkpoint would hold exactly the results the coverage guard just
        rejected, so every later run would restore them, skip every lookup and
        hit the same guard again.
        """
        enriched = [
            _paper(title=f"P{i}", external_ids={"CorpusId": i + 1}, citation_count=i)
            for i in range(10)
        ]
        _conf(tmp_path, "iclr_2026", [_paper(title=f"P{i}") for i in range(10)], enriched)
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "iclr_2026", S2Client(min_interval=0.0), tmp_path, full=True
        )

        assert result.status == "skipped"
        assert not (checkpoint_path(tmp_path, "iclr_2026")).exists()


class TestEnrichAll:
    @pytest.mark.asyncio
    async def test_one_skip_does_not_stop_the_rest(self, tmp_path, monkeypatch):
        async def fake(conf_id, client, data_dir, **_):
            return EnrichResult(conf_id, "skipped" if conf_id == "corl_2024" else "nothing-to-do")

        monkeypatch.setattr("ppr.enrich.enrich_conference", fake)
        results = await enrich_all(["corl_2024", "empty_2026"], S2Client(min_interval=0.0), tmp_path)
        assert [(r.conf_id, r.status) for r in results] == [
            ("empty_2026", "nothing-to-do"), ("corl_2024", "skipped"),
        ]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_stop_the_rest(self, tmp_path, monkeypatch):
        calls = []

        async def fake_enrich_conference(conf_id, client, data_dir, *, full=False, deadline=NO_DEADLINE):
            calls.append(conf_id)
            if conf_id == "boom_2026":
                raise ValueError("kaboom")
            return EnrichResult(conf_id, "enriched")

        monkeypatch.setattr(
            "ppr.enrich.enrich_conference", fake_enrich_conference
        )
        results = await enrich_all(
            ["boom_2026", "fine_2026"], S2Client(min_interval=0.0), tmp_path
        )
        # Both conferences were attempted — the failure did not short-circuit
        # the loop — and the crash comes back as "failed", distinct from the
        # "skipped" a deliberate guard returns, so the CLI can exit non-zero.
        assert calls == ["boom_2026", "fine_2026"]
        assert results[0].conf_id == "boom_2026"
        assert results[0].status == "failed"
        assert "kaboom" in results[0].reason
        assert results[1].conf_id == "fine_2026"
        assert results[1].status == "enriched"


class TestVenueNames:
    def test_verified_venue_strings_present(self):
        assert S2_VENUE_NAMES["icml"] == "International Conference on Machine Learning"
        assert S2_VENUE_NAMES["cvpr"] == "CVPR"


import argparse

from ppr.cli import all_conference_ids, build_parser, cmd_enrich
from ppr.enrich import format_enrich_summary


class TestCliWiring:
    def test_all_conference_ids_lists_data_dirs(self, tmp_path):
        (tmp_path / "iclr_2026").mkdir()
        (tmp_path / "acl_2026").mkdir()
        (tmp_path / "notadir.txt").write_text("x")
        assert all_conference_ids(tmp_path) == ["acl_2026", "iclr_2026"]

    def test_enrich_accepts_all_flag_without_ids(self):
        args = build_parser().parse_args(["enrich", "--all"])
        assert args.all is True
        assert args.conferences == []

    def test_enrich_accepts_ids_without_all_flag(self):
        args = build_parser().parse_args(["enrich", "iclr_2026"])
        assert args.conferences == ["iclr_2026"]
        assert args.all is False

    def test_enrich_exposes_full(self):
        args = build_parser().parse_args(["enrich", "--all", "--full"])
        assert args.full is True

    def test_full_defaults_to_false(self):
        args = build_parser().parse_args(["enrich", "--all"])
        assert args.full is False

    def test_retry_unmatched_flag_is_gone(self):
        # Retry is the default now; the flag would be a no-op that reads as a
        # switch. Anyone who scripted it should get an error, not silence.
        with pytest.raises(SystemExit):
            build_parser().parse_args(["enrich", "--all", "--retry-unmatched"])


class TestFormatSummary:
    def test_reports_every_status_including_skips(self):
        out = format_enrich_summary(
            [
                EnrichResult("iclr_2026", "enriched", "refresh", 5340, 5340, 0, 0),
                EnrichResult("corl_2024", "skipped", reason="papers.jsonl is empty"),
                EnrichResult("ghost_2026", "nothing-to-do"),
            ]
        )
        assert "iclr_2026" in out
        assert "corl_2024" in out
        assert "papers.jsonl is empty" in out
        assert "ghost_2026" in out

    def test_counts_skips(self):
        out = format_enrich_summary(
            [EnrichResult("a", "skipped", reason="r"), EnrichResult("b", "enriched")]
        )
        assert "1 skipped" in out

    def test_counts_failures_separately_from_skips(self):
        out = format_enrich_summary(
            [
                EnrichResult("a", "skipped", reason="guard"),
                EnrichResult("b", "failed", reason="kaboom"),
                EnrichResult("c", "enriched"),
            ]
        )
        assert "1 failed" in out
        assert "1 skipped" in out
        assert "kaboom" in out


class TestFormatEnrichSummary:
    def test_reports_resumed_and_unbound(self):
        out = format_enrich_summary([
            EnrichResult("iclr_2026", "enriched", "refresh",
                         total=10, refreshed=7, cold=2, resumed=1, unbound=2),
        ])
        assert "Resumed" in out
        assert "Unbound" in out
        assert "1 enriched, 0 skipped, 0 failed, 1 total." in out

    def test_row_renders_each_numeric_column_in_its_own_slot(self):
        # A header naming "Resumed" and "Unbound" is not proof the row under
        # it renders those columns from the right fields — e.g. printing
        # r.resumed twice and never r.unbound would still satisfy the
        # assertions above. Every numeric column gets a distinct value here,
        # so only the correct field in the correct slot can match.
        result = EnrichResult(
            "iclr_2026", "enriched", "refresh",
            total=23, refreshed=11, cold=5, resumed=4, unbound=3, deferred=2,
            reason="a note",
        )
        out = format_enrich_summary([result])
        expected_row = (
            f"{'iclr_2026':<24} {'enriched':<14} {'refresh':<11} "
            f"{23:>7} {11:>8} {5:>7} {4:>8} {3:>8} {2:>9}  a note"
        )
        assert expected_row in out


def _enrich_args(**kw) -> argparse.Namespace:
    base = dict(
        conferences=["a_2026"], all=False, full=False,
        api_key="", time_budget=None, report=None, require=[],
    )
    base.update(kw)
    return argparse.Namespace(**base)


class TestCmdEnrichExitCode:
    def _patch_results(self, monkeypatch, results):
        async def fake_enrich_all(*args, **kwargs):
            return results

        monkeypatch.setattr("ppr.cli.enrich_all", fake_enrich_all)

    def test_a_failed_conference_exits_nonzero(self, monkeypatch, capsys):
        # ppr enrich --all feeds a data release; a run where a conference
        # crashed must not look like success to the calling shell script.
        self._patch_results(
            monkeypatch, [EnrichResult("a_2026", "failed", reason="kaboom")]
        )
        with pytest.raises(SystemExit) as exc:
            cmd_enrich(_enrich_args())
        assert exc.value.code == 1

    def test_guard_skips_exit_zero(self, monkeypatch, capsys):
        # A guard skip is the correct outcome, not an error.
        self._patch_results(
            monkeypatch,
            [
                EnrichResult("a_2026", "skipped", reason="guard"),
                EnrichResult("b_2026", "nothing-to-do"),
                EnrichResult("c_2026", "enriched"),
            ],
        )
        cmd_enrich(_enrich_args())

    def test_a_required_conference_skipped_by_a_guard_exits_nonzero(self, monkeypatch, capsys):
        """After a re-crawl, a guard skip leaves the old papers_enriched.jsonl
        beside the new papers.jsonl; shipping that release is the failure."""
        self._patch_results(monkeypatch, [EnrichResult("ase_2024", "skipped", reason="guard")])
        with pytest.raises(SystemExit) as exc:
            cmd_enrich(_enrich_args(require=["ase_2024"]))
        assert exc.value.code == 1
        assert "ase_2024" in capsys.readouterr().out

    def test_a_required_conference_missing_from_the_results_exits_nonzero(self, monkeypatch, capsys):
        self._patch_results(monkeypatch, [EnrichResult("a_2026", "enriched")])
        with pytest.raises(SystemExit):
            cmd_enrich(_enrich_args(require=["ase_2024"]))

    def test_required_conferences_that_enriched_exit_zero(self, monkeypatch, capsys):
        self._patch_results(monkeypatch, [EnrichResult("ase_2024", "enriched"),
                                          EnrichResult("ase_2025", "nothing-to-do")])
        cmd_enrich(_enrich_args(require=["ase_2024", "ase_2025"]))

    def test_skips_outside_the_required_set_still_exit_zero(self, monkeypatch, capsys):
        self._patch_results(monkeypatch, [EnrichResult("ase_2024", "enriched"),
                                          EnrichResult("b_2026", "skipped", reason="guard")])
        cmd_enrich(_enrich_args(require=["ase_2024"]))

    def test_require_parses_a_list(self):
        args = build_parser().parse_args(["enrich", "--all", "--require", "a_2026", "b_2026"])
        assert args.require == ["a_2026", "b_2026"]


from ppr.enrich import Deadline, order_newest_first, parse_duration, results_to_json


def _passed():
    """A deadline that has already passed."""
    return Deadline(0, clock=lambda: 100.0)


class TestDeadline:
    def test_none_never_passes(self):
        assert NO_DEADLINE.passed() is False

    def test_passes_at_the_budget(self):
        now = iter([0.0, 9.9, 10.0])
        d = Deadline(10, clock=lambda: next(now))
        assert d.passed() is False
        assert d.passed() is True


class TestParseDuration:
    @pytest.mark.parametrize("text,seconds", [("90s", 90), ("30m", 1800), ("4h", 14400)])
    def test_units(self, text, seconds):
        assert parse_duration(text) == seconds

    @pytest.mark.parametrize("text", ["4", "4d", "h", "-1h", "1.5h"])
    def test_rejects_anything_else(self, text):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_duration(text)


class TestOrderNewestFirst:
    def test_year_desc_then_id(self):
        assert order_newest_first(["acl_2024", "wacv_2026", "cvpr_2026", "iclr_2025"]) == [
            "cvpr_2026", "wacv_2026", "iclr_2025", "acl_2024",
        ]


class TestTimeBudget:
    @respx.mock
    @pytest.mark.asyncio
    async def test_past_deadline_defers_title_matching_and_keeps_prior_state(self, tmp_path):
        _conf(
            tmp_path, "icml_2026",
            [_paper(title="Old"), _paper(title="New"), _paper(title="Hit")],
            [_paper(title="Old", match_status="not_found", tldr="kept")],
        )
        # Bulk prefetch is not per-title matching: it must still run, and its
        # hit must still be applied, after the deadline has passed.
        bulk = respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": [
            {"title": "Hit", "citationCount": 7, "externalIds": {"CorpusId": 5}},
        ]}))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        result = await enrich_conference(
            "icml_2026", S2Client(min_interval=0.0), tmp_path, deadline=_passed()
        )
        assert result.status == "enriched"
        assert result.deferred == 2
        assert bulk.called
        assert match.call_count == 0
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "icml_2026"))}
        assert out["Hit"].citation_count == 7
        assert out["Old"].match_status == "not_found"
        assert out["Old"].tldr == "kept"  # carried over, not wiped by the deferral
        assert out["New"].match_status == ""  # never looked up, so not "not_found"

    @respx.mock
    @pytest.mark.asyncio
    async def test_deadline_mid_loop_defers_only_the_rest(self, tmp_path):
        _conf(tmp_path, "icml_2026", [_paper(title="A"), _paper(title="B")])
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        ticks = iter([0.0, 5.0, 15.0])
        result = await enrich_conference(
            "icml_2026", S2Client(min_interval=0.0), tmp_path,
            deadline=Deadline(10, clock=lambda: next(ticks)),
        )
        assert match.call_count == 1
        assert result.deferred == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_still_runs_after_the_deadline(self, tmp_path):
        _conf(
            tmp_path, "iclr_2025",
            [_paper(title="A")],
            [_paper(title="A", external_ids={"CorpusId": 1}, citation_count=1)],
        )
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[
            {"title": "A", "citationCount": 99, "externalIds": {"CorpusId": 1},
             "authors": [{"name": "X"}]},
        ]))
        result = await enrich_conference(
            "iclr_2025", S2Client(min_interval=0.0), tmp_path, deadline=_passed()
        )
        assert (result.status, result.deferred) == ("enriched", 0)
        out = read_papers(papers_path(tmp_path, "iclr_2025"))
        assert out[0].citation_count == 99

    @pytest.mark.asyncio
    async def test_enrich_all_forwards_the_deadline_in_newest_first_order(self, tmp_path, monkeypatch):
        seen = []

        async def fake(conf_id, client, data_dir, *, full=False, deadline=NO_DEADLINE):
            seen.append((conf_id, deadline))
            return EnrichResult(conf_id, "enriched")

        monkeypatch.setattr("ppr.enrich.enrich_conference", fake)
        d = _passed()
        await enrich_all(["acl_2024", "icml_2026"], S2Client(min_interval=0.0), tmp_path, deadline=d)
        assert seen == [("icml_2026", d), ("acl_2024", d)]


class TestDeferredReporting:
    def test_summary_has_a_deferred_column_and_footer(self):
        out = format_enrich_summary([
            EnrichResult("icml_2026", "enriched", "title-cold", total=10, cold=10, deferred=7),
        ])
        assert "Deferred" in out
        assert "7 papers deferred to the next run" in out

    def test_no_footer_when_nothing_deferred(self):
        out = format_enrich_summary([EnrichResult("a_2026", "enriched", total=1)])
        assert "deferred to the next run" not in out

    def test_json_report(self):
        row = json.loads(results_to_json([EnrichResult("a_2026", "enriched", deferred=3)]))["results"][0]
        assert (row["conf_id"], row["deferred"]) == ("a_2026", 3)


class TestCmdEnrichReport:
    def test_report_is_written_even_when_a_conference_failed(self, tmp_path, monkeypatch):
        async def fake_enrich_all(*args, **kwargs):
            return [EnrichResult("a_2026", "failed", reason="kaboom")]

        monkeypatch.setattr("ppr.cli.enrich_all", fake_enrich_all)
        report = tmp_path / "enrich.json"
        with pytest.raises(SystemExit):
            cmd_enrich(_enrich_args(report=report))
        assert json.loads(report.read_text())["results"][0]["status"] == "failed"

    def test_deferral_alone_exits_zero(self, monkeypatch):
        async def fake_enrich_all(*args, **kwargs):
            return [EnrichResult("a_2026", "enriched", deferred=50)]

        monkeypatch.setattr("ppr.cli.enrich_all", fake_enrich_all)
        cmd_enrich(_enrich_args())  # no SystemExit


class TestCmdEnrichDeadlineWiring:
    def _captured(self, monkeypatch, argv):
        seen = {}

        async def fake_enrich_all(*args, **kwargs):
            seen.update(kwargs)
            return [EnrichResult("a_2026", "enriched")]

        monkeypatch.setattr("ppr.cli.enrich_all", fake_enrich_all)
        cmd_enrich(build_parser().parse_args(argv))
        return seen["deadline"]

    def test_zero_budget_is_a_spent_deadline_not_no_deadline(self, monkeypatch):
        deadline = self._captured(monkeypatch, ["enrich", "a_2026", "--time-budget", "0s"])
        assert deadline is not NO_DEADLINE
        assert deadline.passed() is True

    def test_no_budget_means_no_deadline(self, monkeypatch):
        assert self._captured(monkeypatch, ["enrich", "a_2026"]) is NO_DEADLINE


class TestBatchOnly:
    """Archive conferences: refresh and DOI batches only, never title matching."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_refreshes_and_leaves_title_cold_papers_untried(self, tmp_path):
        raw = [_paper(title="Bound"), _paper(title="Never Found")]
        enriched = [
            _paper(title="Bound", external_ids={"CorpusId": 1}, citation_count=1),
            _paper(title="Never Found", match_status="not_found"),
        ]
        _conf(tmp_path, "cvpr_2019", raw, enriched)
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[
            {"title": "Bound", "citationCount": 50, "externalIds": {"CorpusId": 1},
             "authors": [{"name": "X"}]},
        ]))
        bulk = respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "cvpr_2019", S2Client(min_interval=0.0), tmp_path, batch_only=True
        )

        assert result.status == "enriched"
        assert (result.refreshed, result.untried, result.deferred) == (1, 1, 0)
        assert not bulk.called and not match.called
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "cvpr_2019"))}
        assert out["Bound"].citation_count == 50
        assert out["Never Found"].match_status == "not_found"

    @respx.mock
    @pytest.mark.asyncio
    async def test_doi_papers_still_bind_by_batch(self, tmp_path):
        # Review focus 2: an archive conference never cold-enriched still gets
        # its DOI papers, and the rest show up as untried, not as success.
        raw = [_paper(title="Has DOI", link="https://doi.org/10.1/x"), _paper(title="No DOI")]
        _conf(tmp_path, "icra_2016", raw)
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[
            {"title": "Has DOI", "citationCount": 7, "externalIds": {"CorpusId": 9},
             "authors": [{"name": "X"}]},
        ]))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "icra_2016", S2Client(min_interval=0.0), tmp_path, batch_only=True
        )

        assert result.status == "enriched"
        assert (result.cold, result.untried) == (2, 1)
        assert not match.called
        out = {p.title: p for p in read_papers(papers_path(tmp_path, "icra_2016"))}
        assert out["Has DOI"].citation_count == 7
        assert out["No DOI"].citation_count is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_a_doi_miss_is_untried_not_title_matched(self, tmp_path):
        _conf(tmp_path, "eccv_2016", [_paper(title="Miss", link="https://doi.org/10.1/x")])
        respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[None]))
        bulk = respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        match = respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = await enrich_conference(
            "eccv_2016", S2Client(min_interval=0.0), tmp_path, batch_only=True
        )

        assert (result.status, result.cold, result.untried) == ("enriched", 1, 1)
        assert not bulk.called and not match.called


from datetime import date

from ppr.cli import build_parser, cmd_enrich  # noqa: F811
from ppr.enrich import Deadline, format_enrich_summary  # noqa: F811


class TestEnrichAllArchive:
    NOV_2026 = date(2026, 11, 3)

    @pytest.mark.asyncio
    async def test_due_archive_runs_first_batch_only_and_not_due_is_skipped(self, tmp_path, monkeypatch):
        calls = []

        async def fake(conf_id, client, data_dir, **kwargs):
            calls.append((conf_id, kwargs))
            return EnrichResult(conf_id, "enriched")

        monkeypatch.setattr("ppr.enrich.enrich_conference", fake)
        d = Deadline(0, clock=lambda: 100.0)
        results = await enrich_all(
            ["icml_2026", "neurips_2017", "cvpr_2019", "iros_2016"],
            S2Client(min_interval=0.0), tmp_path, deadline=d, today=self.NOV_2026,
        )
        # November: cohort 2 = cvpr_2019, iros_2016. neurips_2017 is cohort 1.
        assert calls == [
            ("cvpr_2019", {"full": False, "batch_only": True}),
            ("iros_2016", {"full": False, "batch_only": True}),
            ("icml_2026", {"full": False, "deadline": d}),
        ]
        assert [(r.conf_id, r.status) for r in results][-1] == ("neurips_2017", "not-due")

    @pytest.mark.asyncio
    async def test_not_due_files_are_byte_identical(self, tmp_path):
        _conf(tmp_path, "neurips_2017", [_paper(title="A")],
              [_paper(title="A", external_ids={"CorpusId": 1}, citation_count=3)])
        path = papers_path(tmp_path, "neurips_2017")
        before = path.read_bytes()
        results = await enrich_all(["neurips_2017"], S2Client(min_interval=0.0), tmp_path,
                                   today=self.NOV_2026)
        assert [(r.conf_id, r.status) for r in results] == [("neurips_2017", "not-due")]
        assert path.read_bytes() == before

    @pytest.mark.asyncio
    async def test_exempt_archive_conference_gets_a_full_enrich(self, tmp_path, monkeypatch):
        calls = []

        async def fake(conf_id, client, data_dir, **kwargs):
            calls.append((conf_id, kwargs))
            return EnrichResult(conf_id, "enriched")

        monkeypatch.setattr("ppr.enrich.enrich_conference", fake)
        await enrich_all(["neurips_2017"], S2Client(min_interval=0.0), tmp_path,
                         today=self.NOV_2026, exempt=frozenset({"neurips_2017"}))
        assert calls == [("neurips_2017", {"full": False, "deadline": NO_DEADLINE})]


    @pytest.mark.asyncio
    async def test_exempt_live_ids_run_before_newer_live_ids_but_keep_the_deadline(
            self, tmp_path, monkeypatch):
        calls = []

        async def fake(conf_id, client, data_dir, **kwargs):
            calls.append((conf_id, kwargs))
            return EnrichResult(conf_id, "enriched")

        monkeypatch.setattr("ppr.enrich.enrich_conference", fake)
        d = Deadline(0, clock=lambda: 100.0)
        await enrich_all(["icml_2026", "acl_2024", "neurips_2017"],
                         S2Client(min_interval=0.0), tmp_path, deadline=d,
                         today=self.NOV_2026, exempt=frozenset({"neurips_2017"}))
        assert calls == [
            ("neurips_2017", {"full": False, "deadline": d}),
            ("icml_2026", {"full": False, "deadline": d}),
            ("acl_2024", {"full": False, "deadline": d}),
        ]


class TestArchiveSummary:
    def test_not_due_rows_are_counted_not_listed(self):
        out = format_enrich_summary([
            EnrichResult("icml_2026", "enriched", total=1),
            EnrichResult("neurips_2017", "not-due"),
        ])
        assert "neurips_2017" not in out
        assert "1 enriched, 0 skipped, 0 failed, 1 not due (archive), 2 total." in out

    def test_untried_papers_are_named_in_the_footer(self):
        out = format_enrich_summary([EnrichResult("icra_2016", "enriched", cold=2, untried=1)])
        assert "1 unmatched papers left untried" in out

    def test_mostly_untried_conferences_are_named(self):
        out = format_enrich_summary([
            EnrichResult("rss_2014", "enriched", total=10, untried=8),
            EnrichResult("icra_2016", "enriched", total=10, untried=8),
            EnrichResult("iros_2016", "enriched", total=10, untried=2),
        ])
        assert "Mostly untried (run `ppr enrich <id>`): icra_2016, rss_2014" in out

    def test_mostly_untried_line_omits_conferences_under_half(self):
        out = format_enrich_summary([EnrichResult("iros_2016", "enriched", total=10, untried=2)])
        assert "Mostly untried" not in out


class TestCmdEnrichArchiveWiring:
    def _kwargs(self, monkeypatch, argv):
        seen = {}

        async def fake_enrich_all(*args, **kwargs):
            seen.update(kwargs)
            # Both ids end enriched, so the --require check does not exit first.
            return [EnrichResult("a_2026", "enriched"), EnrichResult("x_2015", "enriched")]

        monkeypatch.setattr("ppr.cli.enrich_all", fake_enrich_all)
        monkeypatch.setattr("ppr.cli.all_conference_ids", lambda _d: ["a_2026", "x_2015"])
        cmd_enrich(build_parser().parse_args(argv))
        return seen

    def test_all_applies_the_archive_rule_and_exempts_required_ids(self, monkeypatch):
        seen = self._kwargs(monkeypatch, ["enrich", "--all", "--require", "x_2015"])
        assert seen["today"] == date.today()
        assert seen["exempt"] == frozenset({"x_2015"})

    def test_named_conferences_get_no_archive_rule(self, monkeypatch):
        assert self._kwargs(monkeypatch, ["enrich", "x_2015"])["today"] is None

    def test_full_turns_the_archive_rule_off(self, monkeypatch):
        # Review focus 3: --full re-runs every cold path; batch-only would
        # leave non-DOI archive papers unenriched behind the coverage guard.
        assert self._kwargs(monkeypatch, ["enrich", "--all", "--full"])["today"] is None


def test_enrichment_never_touches_venue_date():
    paper = _paper(venue_date="2025-02-03")
    apply_enrichment(paper, FULL_ENTRY)
    assert paper.venue_date == "2025-02-03"
    unbind(paper)
    assert paper.venue_date == "2025-02-03"
    raw = _paper(venue_date="2025-02-03")
    carry_over(raw, _paper(venue_date="1999-01-01", citation_count=3))
    assert raw.venue_date == "2025-02-03"


def test_bulk_years():
    assert bulk_years("tmlr", 2025) == [2024, 2025]
    assert bulk_years("iclr", 2025) == [2025]


class _FakeS2:
    """Records bulk and per-title calls; bulk answers only for given (venue, year)."""

    def __init__(self, hits):
        self.hits = hits
        self.bulk_calls = []
        self.match_calls = []

    async def bulk_search(self, http, venue, year):
        self.bulk_calls.append((venue, year))
        return self.hits.get((venue, year), [])

    async def match_title(self, http, title):
        self.match_calls.append(title)
        return None


@pytest.mark.asyncio
async def test_tmlr_prefetch_finds_a_paper_s2_dates_a_year_earlier():
    venue = "Trans. Mach. Learn. Res."
    fake = _FakeS2({(venue, 2024): [{"title": "Foo", "citationCount": 7}]})
    paper = _paper(title="Foo")
    await _run_title_cold(fake, None, [paper], "tmlr_2025", lambda ps: None)
    assert paper.match_status == "matched"
    assert paper.citation_count == 7
    assert fake.bulk_calls == [(venue, 2024), (venue, 2025)]
    assert fake.match_calls == []


class TestSingleFile:
    @respx.mock
    @pytest.mark.asyncio
    async def test_enrich_writes_back_to_the_year_file(self, tmp_path):
        path = papers_path(tmp_path, "iclr_2026")
        save_enriched([_paper(title="A", external_ids={"CorpusId": 1}, citation_count=1)], path)
        respx.post(BATCH_URL).mock(return_value=httpx.Response(
            200, json=[{"title": "A", "citationCount": 7, "externalIds": {"CorpusId": 1}}]))
        result = await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path)
        assert result.status == "enriched"
        assert [p.citation_count for p in read_papers(path)] == [7]
        assert sorted(p.name for p in path.parent.iterdir()) == ["2026.jsonl"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_full_starts_from_the_crawl_view(self, tmp_path):
        path = papers_path(tmp_path, "iclr_2026")
        save_enriched([_paper(title="A", authors=["Ada Lovelace"], external_ids={"CorpusId": 1},
                              citation_count=3, tldr="stale", abstract="Old S2 abstract.",
                              abstract_source="s2", match_status="matched")], path)
        respx.get(BULK_URL).mock(return_value=httpx.Response(200, json={
            "total": 1, "data": [{"title": "A", "citationCount": 9, "abstract": "New S2 abstract.",
                                  "externalIds": {"CorpusId": 1}, "authors": [{"name": "Ada Lovelace"}]}],
        }))
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        await enrich_conference("iclr_2026", S2Client(min_interval=0.0), tmp_path, full=True)
        [p] = read_papers(path)
        assert (p.citation_count, p.tldr) == (9, "")
        assert (p.abstract, p.abstract_source) == ("New S2 abstract.", "s2")


def test_unbind_keeps_a_crawl_abstract_and_clears_an_s2_one():
    crawl = unbind(_paper(abstract="From OpenReview.", external_ids={"CorpusId": 1}, citation_count=4))
    s2 = unbind(_paper(abstract="From S2.", abstract_source="s2", external_ids={"CorpusId": 2}))
    assert (crawl.abstract, crawl.match_status, crawl.citation_count) == ("From OpenReview.", "not_found", None)
    assert (s2.abstract, s2.abstract_source, s2.external_ids) == ("", "", {})
