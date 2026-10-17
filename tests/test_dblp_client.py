"""Tests for the one implementation of how the project talks to DBLP: its SPARQL endpoint."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ppr import dblp_client
from ppr.dblp_client import (
    MAX_RETRIES,
    MIN_INTERVAL,
    DblpUnavailable,
    clean_author,
    clean_title,
    select,
    toc_count,
    toc_iri,
    toc_papers,
)

COUNT_ROWS = [{"n": {"type": "literal", "value": "245"}}]


def _response(status=200, bindings=None, headers=None, meta=None, html=None):
    r = MagicMock()
    r.status_code = status
    # A real dict: `.get(...)` on an unconfigured MagicMock returns another
    # MagicMock, which Retry-After parsing would read as a value.
    r.headers = headers or {}
    if html is not None:
        r.text = html
        r.json = MagicMock(side_effect=ValueError("not json"))
    else:
        payload = {"head": {"vars": []},
                   "results": {"bindings": COUNT_ROWS if bindings is None else bindings}}
        if meta is not None:
            payload["meta"] = meta
        r.json = lambda: payload
    return r


@pytest.fixture(autouse=True)
def reset_pacing(monkeypatch):
    """The request clock is module state shared by every caller; a test must not
    inherit the previous test's turn."""
    monkeypatch.setattr(dblp_client, "_last_request", 0.0)


@pytest.fixture
def slept(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr("ppr.dblp_client.time.sleep", lambda s: calls.append(s))
    return calls


def _sent(post) -> str:
    return post.call_args.kwargs["data"]["query"]


class TestSelect:
    def test_posts_the_query_and_returns_its_bindings(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response()) as p:
            assert select("SELECT ?n WHERE { }") == COUNT_ROWS
        assert p.call_args.args[0] == "https://sparql.dblp.org/sparql"
        assert "PREFIX dblp: <https://dblp.org/rdf/schema#>" in _sent(p)
        assert p.call_args.kwargs["headers"]["Accept"] == "application/sparql-results+json"

    def test_identifies_the_project_not_a_browser(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response()) as p:
            select("SELECT ?n WHERE { }")
        ua = p.call_args.kwargs["headers"]["User-Agent"]
        assert "paper-explorer" in ua
        assert "Mozilla" not in ua

    @pytest.mark.parametrize("status", sorted(dblp_client.RETRYABLE_STATUSES))
    def test_retries_every_retryable_status_then_succeeds(self, slept, status):
        with patch("ppr.dblp_client.requests.post", side_effect=[_response(status), _response()]):
            assert select("q") == COUNT_ROWS

    def test_persistent_throttling_raises_rather_than_returning_rows(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response(429)) as p:
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "429" in str(exc.value)
        assert p.call_count == MAX_RETRIES

    def test_a_bot_challenge_is_named_and_not_retried(self, slept):
        """dblp.org's Anubis wall answers 202 with an HTML page (2026-10-14).
        Retrying a proof-of-work challenge never gets past it, and the report
        must say what happened, not a bare status code."""
        challenge = _response(202, html="<title>Making sure you're not a bot!</title>")
        with patch("ppr.dblp_client.requests.post", return_value=challenge) as p:
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "bot challenge" in str(exc.value)
        assert "202" in str(exc.value)
        assert p.call_count == 1

    def test_html_with_a_200_is_not_rows(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response(200, html="<html>")):
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "200" in str(exc.value)

    def test_a_truncated_result_raises(self, slept):
        """A capped result read as complete would undercount a toc."""
        short = _response(bindings=COUNT_ROWS, meta={"result-size-total": 5})
        with patch("ppr.dblp_client.requests.post", return_value=short):
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "truncated" in str(exc.value)

    def test_a_non_numeric_total_raises_unavailable(self, slept):
        odd = _response(bindings=COUNT_ROWS, meta={"result-size-total": "many"})
        with patch("ppr.dblp_client.requests.post", return_value=odd):
            with pytest.raises(DblpUnavailable, match="result-size-total"):
                select("q")

    def test_a_complete_result_with_meta_passes(self, slept):
        full = _response(bindings=COUNT_ROWS, meta={"result-size-total": 1})
        with patch("ppr.dblp_client.requests.post", return_value=full):
            assert select("q") == COUNT_ROWS

    def test_network_error_is_retried_then_raises(self, slept):
        with patch("ppr.dblp_client.requests.post", side_effect=requests.RequestException("boom")):
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "RequestException" in str(exc.value)

    def test_network_error_recovers_on_a_retry(self, slept):
        with patch("ppr.dblp_client.requests.post",
                   side_effect=[requests.RequestException("boom"), _response()]):
            assert select("q") == COUNT_ROWS

    def test_a_non_retryable_error_raises_immediately(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response(404)) as p:
            with pytest.raises(DblpUnavailable) as exc:
                select("q")
        assert "404" in str(exc.value)
        assert p.call_count == 1

    def test_retry_after_is_honored_over_the_backoff_guess(self, slept):
        throttled = _response(429, headers={"Retry-After": "30"})
        with patch("ppr.dblp_client.requests.post", side_effect=[throttled, _response()]):
            assert select("q") == COUNT_ROWS
        assert 30.0 in slept

    def test_a_retry_after_http_date_falls_back_to_the_backoff(self, slept):
        throttled = _response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        with patch("ppr.dblp_client.requests.post", side_effect=[throttled, _response()]):
            assert select("q") == COUNT_ROWS
        assert slept


class TestTocIri:
    def test_maps_a_toc_key_to_its_page_iri(self):
        assert toc_iri("db/conf/icse/icse2025.bht") == "https://dblp.org/db/conf/icse/icse2025"

    def test_rejects_a_key_that_would_break_the_query(self):
        with pytest.raises(ValueError):
            toc_iri("db/conf/x> } DROP")


class TestTocCount:
    def test_counts_one_key_excluding_editorship(self, slept):
        rows = [{"n": {"value": "245"}}]
        with patch("ppr.dblp_client.requests.post", return_value=_response(bindings=rows)) as p:
            assert toc_count(["db/conf/icse/icse2025.bht"]) == 245
        q = _sent(p)
        assert "<https://dblp.org/db/conf/icse/icse2025>" in q
        assert "dblp:listedOnTocPage" in q
        assert "FILTER NOT EXISTS { ?pub a dblp:Editorship }" in q

    def test_many_keys_are_one_request(self, slept):
        """ECCV 2024 spans 89 volumes, counted in one query."""
        keys = [f"db/conf/eccv/eccv2024-{i}.bht" for i in range(1, 90)]
        with patch("ppr.dblp_client.requests.post",
                   return_value=_response(bindings=[{"n": {"value": "2387"}}])) as p:
            assert toc_count(keys) == 2387
        assert p.call_count == 1
        assert "<https://dblp.org/db/conf/eccv/eccv2024-89>" in _sent(p)

    def test_number_filters_a_shared_pacmse_volume(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response()) as p:
            toc_count(["db/journals/pacmse/pacmse2.bht"], number="ISSTA")
        q = _sent(p)
        assert "dblp:publishedInJournalVolumeIssue" in q
        assert 'STR(?issue) = "ISSTA"' in q

    def test_no_number_means_no_issue_filter(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response()) as p:
            toc_count(["db/conf/icse/icse2025.bht"])
        assert "publishedInJournalVolumeIssue" not in _sent(p)

    def test_an_empty_key_list_is_a_caller_bug(self):
        with pytest.raises(ValueError):
            toc_count([])

    def test_an_unparseable_count_raises(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response(bindings=[])):
            with pytest.raises(DblpUnavailable):
                toc_count(["db/conf/icse/icse2025.bht"])


def _row(pub, title, link=None, ord=None, name=None):
    row = {"pub": {"value": pub}, "title": {"value": title}}
    if link:
        row["link"] = {"value": link}
    if ord is not None:
        row["ord"] = {"value": str(ord)}
        row["name"] = {"value": name}
    return row


class TestTocPapers:
    def test_groups_rows_into_cleaned_papers_with_ordered_authors(self, slept):
        rows = [
            _row("p1", "Second &amp; Third.", "https://doi.org/10.1/b", 2, "Bea Two 0001"),
            _row("p1", "Second &amp; Third.", "https://doi.org/10.1/b", 1, "Al One"),
            _row("p2", "Solo", "https://doi.org/10.1/c", 1, "Cy Three"),
        ]
        with patch("ppr.dblp_client.requests.post", return_value=_response(bindings=rows)):
            out = toc_papers("db/conf/icse/icse2025.bht")
        assert out == [
            {"title": "Second & Third", "link": "https://doi.org/10.1/b",
             "authors": ["Al One", "Bea Two"]},
            {"title": "Solo", "link": "https://doi.org/10.1/c", "authors": ["Cy Three"]},
        ]

    def test_a_doi_link_wins_over_other_document_pages(self, slept):
        rows = [
            _row("p1", "T", "https://ieeexplore.ieee.org/document/1", 1, "A"),
            _row("p1", "T", "https://doi.org/10.1/a", 1, "A"),
        ]
        with patch("ppr.dblp_client.requests.post", return_value=_response(bindings=rows)):
            assert toc_papers("db/conf/icra/icra2025.bht")[0]["link"] == "https://doi.org/10.1/a"

    def test_a_paper_without_a_document_page_has_an_empty_link(self, slept):
        with patch("ppr.dblp_client.requests.post",
                   return_value=_response(bindings=[_row("p1", "T", None, 1, "A")])):
            assert toc_papers("db/conf/icra/icra2025.bht")[0]["link"] == ""

    def test_query_excludes_editorship_and_orders_by_ordinal(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response(bindings=[])) as p:
            assert toc_papers("db/conf/icra/icra2025.bht", number=None) == []
        q = _sent(p)
        assert "FILTER NOT EXISTS { ?pub a dblp:Editorship }" in q
        assert "dblp:signatureOrdinal" in q
        assert "ORDER BY ?pub ?ord" in q


class TestCleaning:
    def test_strips_a_four_digit_disambiguation_suffix(self):
        assert clean_author("Hao Zhong 0001") == "Hao Zhong"

    def test_strips_another_suffix(self):
        assert clean_author("Wei Li 0042") == "Wei Li"

    def test_leaves_a_plain_name_alone(self):
        assert clean_author("Jane Doe") == "Jane Doe"

    def test_a_name_ending_in_digits_is_not_a_suffix(self):
        assert clean_author("Agent007") == "Agent007"

    def test_empty_name(self):
        assert clean_author("") == ""

    def test_title_entities_and_trailing_period(self):
        assert clean_title("Bugs &amp; Fixes.") == "Bugs & Fixes"

    @pytest.mark.parametrize("raw,clean", [
        ("Copy and Paste Redeemed (T).", "Copy and Paste Redeemed"),
        ("GRT: Program-Analysis-Guided Random Testing (T).", "GRT: Program-Analysis-Guided Random Testing"),
        ("Tracking Load-time Configuration Options (N).", "Tracking Load-time Configuration Options"),
        ("Sorting in O(N).", "Sorting in O(N)"),          # not a track marker: no space before it
        ("Learning (T) Models.", "Learning (T) Models"),   # only at the end
    ])
    def test_clean_title_drops_ase_2015_track_markers(self, raw, clean):
        assert clean_title(raw) == clean


class TestPacing:
    def test_min_interval_is_the_endpoint_crawl_delay(self):
        """sparql.dblp.org/robots.txt: `Crawl-delay: 10` (checked 2026-10-14)."""
        assert MIN_INTERVAL == 10.0

    def test_consecutive_queries_are_spaced_by_the_crawl_delay(self, slept):
        with patch("ppr.dblp_client.requests.post", return_value=_response()):
            select("q")
            select("q")
        assert max(slept) > MIN_INTERVAL - 0.05
        assert max(slept) <= MIN_INTERVAL

    def test_pacing_is_shared_across_callers(self):
        """Every DBLP caller hits one host from one machine; pacing each tracked
        separately would not be pacing at all."""
        from ppr import discover, validate
        from ppr.scrapers import dblp as dblp_scraper

        assert validate.dblp_client is dblp_client
        assert discover.dblp_client is dblp_client
        assert dblp_scraper.dblp_client is dblp_client
