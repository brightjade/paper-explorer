import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from ppr.s2_client import (
    BATCH_CHUNK_SIZE,
    BATCH_URL,
    ENRICHMENT_FIELDS,
    MATCH_URL,
    S2Client,
)


@pytest.fixture
def no_sleep(monkeypatch):
    """Make backoff instant so retry tests do not actually wait."""
    monkeypatch.setattr("ppr.s2_client.asyncio.sleep", AsyncMock())


def _client() -> S2Client:
    return S2Client(min_interval=0.0)


class TestMatchTitle:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_raw_entry(self):
        respx.get(MATCH_URL).mock(
            return_value=httpx.Response(
                200, json={"data": [{"title": "Test Paper", "citationCount": 42}]}
            )
        )
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "Test Paper")
        assert entry == {"title": "Test Paper", "citationCount": 42}

    @respx.mock
    @pytest.mark.asyncio
    async def test_404_returns_none(self):
        respx.get(MATCH_URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "Nonexistent")
        assert entry is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_data_returns_none(self):
        respx.get(MATCH_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "Nothing")
        assert entry is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_429_then_success(self, no_sleep):
        route = respx.get(MATCH_URL)
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json={"data": [{"title": "T", "citationCount": 10}]}),
        ]
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "T")
        assert entry["citationCount"] == 10

    @respx.mock
    @pytest.mark.asyncio
    async def test_403_is_retried_not_fatal(self, no_sleep):
        route = respx.get(MATCH_URL)
        route.side_effect = [
            httpx.Response(403),
            httpx.Response(200, json={"data": [{"title": "T", "citationCount": 1}]}),
        ]
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "T")
        assert entry["citationCount"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_persistent_500_returns_none(self, no_sleep):
        respx.get(MATCH_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            entry = await _client().match_title(client, "Fail")
        assert entry is None


class TestClientConfig:
    def test_api_key_sets_header(self):
        assert S2Client(api_key="k").headers == {"x-api-key": "k"}

    def test_no_api_key_sends_no_header(self):
        assert S2Client().headers == {}

    def test_batch_chunk_size_is_api_maximum(self):
        assert BATCH_CHUNK_SIZE == 500

    @pytest.mark.asyncio
    async def test_rate_limit_spaces_requests(self):
        c = S2Client(min_interval=0.05)
        start = asyncio.get_event_loop().time()
        await c._rate_limit()
        await c._rate_limit()
        assert asyncio.get_event_loop().time() - start >= 0.05


from ppr.s2_client import BATCH_URL


class TestGetBatch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_entries_in_request_order(self):
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"title": "A", "citationCount": 1},
                    {"title": "B", "citationCount": 2},
                ],
            )
        )
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1", "CorpusId:2"])
        assert [e["title"] for e in out] == ["A", "B"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_null_entries_are_preserved_as_none(self):
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(
                200, json=[{"title": "A", "citationCount": 1}, None]
            )
        )
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1", "CorpusId:404"])
        assert out[0]["title"] == "A"
        assert out[1] is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_ids_makes_no_request(self):
        route = respx.post(BATCH_URL)
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, [])
        assert out == []
        assert route.call_count == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_chunks_at_500(self):
        """501 IDs must become exactly two requests, of 500 and 1."""
        sizes = []

        def _respond(request):
            import json as _json

            ids = _json.loads(request.content)["ids"]
            sizes.append(len(ids))
            return httpx.Response(
                200, json=[{"title": f"P{i}", "citationCount": 0} for i in ids]
            )

        respx.post(BATCH_URL).mock(side_effect=_respond)
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(
                client, [f"CorpusId:{i}" for i in range(501)]
            )
        assert sizes == [500, 1]
        assert len(out) == 501

    @respx.mock
    @pytest.mark.asyncio
    async def test_exactly_500_is_one_request(self):
        route = respx.post(BATCH_URL).mock(
            side_effect=lambda request: httpx.Response(
                200, json=[{"title": "x", "citationCount": 0}] * 500
            )
        )
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(
                client, [f"CorpusId:{i}" for i in range(500)]
            )
        assert route.call_count == 1
        assert len(out) == 500

    @respx.mock
    @pytest.mark.asyncio
    async def test_429_then_success(self, no_sleep):
        route = respx.post(BATCH_URL)
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json=[{"title": "A", "citationCount": 3}]),
        ]
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1"])
        assert out[0]["citationCount"] == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_failed_chunk_yields_none_padding(self, no_sleep):
        """A chunk that never succeeds must not shift later results."""
        respx.post(BATCH_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1", "CorpusId:2"])
        assert out == [None, None]

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_list_body_is_treated_as_a_failed_chunk(self):
        """A 200 carrying an error object, not a list, must not break the run."""
        respx.post(BATCH_URL).mock(
            return_value=httpx.Response(200, json={"error": "Bad request"})
        )
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1", "CorpusId:2"])
        assert out == [None, None]


from ppr.s2_client import BULK_URL


class TestBulkSearch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_single_page(self):
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(
                200,
                json={"total": 2, "data": [{"title": "A"}, {"title": "B"}]},
            )
        )
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert [e["title"] for e in out] == ["A", "B"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_follows_continuation_token(self):
        route = respx.get(BULK_URL)
        route.side_effect = [
            httpx.Response(
                200, json={"total": 3, "token": "tok1", "data": [{"title": "A"}]}
            ),
            httpx.Response(
                200, json={"total": 3, "token": "tok2", "data": [{"title": "B"}]}
            ),
            httpx.Response(200, json={"total": 3, "data": [{"title": "C"}]}),
        ]
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert [e["title"] for e in out] == ["A", "B", "C"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_sends_venue_and_year_params(self):
        route = respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        async with httpx.AsyncClient() as client:
            await _client().bulk_search(client, "CVPR", 2026)
        request = route.calls[0].request
        assert request.url.params["venue"] == "CVPR"
        assert request.url.params["year"] == "2026"

    @respx.mock
    @pytest.mark.asyncio
    async def test_default_fields_omit_tldr(self):
        # /paper/search/bulk answers `tldr` with a 400 (Unrecognized or
        # unsupported fields), unlike /paper/batch and /paper/search/match
        # which both accept it. Falling back to ENRICHMENT_FIELDS here makes
        # every bulk call fail and silently returns [], with prefetch quietly
        # falling through to per-title matching for the whole venue.
        route = respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json={"total": 0, "data": []})
        )
        async with httpx.AsyncClient() as client:
            await _client().bulk_search(client, "CVPR", 2026)
        fields = route.calls[0].request.url.params["fields"].split(",")
        assert "tldr" not in fields
        assert "title" in fields  # still asking for the rest of the fields

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_page_stops_pagination(self):
        """A token that keeps returning nothing must not loop forever."""
        route = respx.get(BULK_URL).mock(
            return_value=httpx.Response(
                200, json={"total": 99, "token": "same", "data": []}
            )
        )
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert out == []
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_failure_returns_empty_list(self, no_sleep):
        respx.get(BULK_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert out == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_dict_body_returns_empty_list(self):
        """A 200 whose body is a bare list has no `data` key to read."""
        respx.get(BULK_URL).mock(
            return_value=httpx.Response(200, json=[{"title": "A"}])
        )
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert out == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_dict_body_mid_pagination_keeps_earlier_pages(self):
        route = respx.get(BULK_URL)
        route.side_effect = [
            httpx.Response(
                200, json={"total": 2, "token": "tok1", "data": [{"title": "A"}]}
            ),
            httpx.Response(200, json="unexpected"),
        ]
        async with httpx.AsyncClient() as client:
            out = await _client().bulk_search(client, "ICML", 2026)
        assert [e["title"] for e in out] == ["A"]


class TestBatchFields:
    @respx.mock
    @pytest.mark.asyncio
    async def test_default_fields_are_the_enrichment_fields(self):
        route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[{"corpusId": 1}]))
        async with httpx.AsyncClient() as client:
            await _client().get_batch(client, ["CorpusId:1"])
        assert route.calls.last.request.url.params["fields"] == ENRICHMENT_FIELDS

    @respx.mock
    @pytest.mark.asyncio
    async def test_fields_can_be_chosen(self):
        route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[{"corpusId": 1}]))
        async with httpx.AsyncClient() as client:
            out = await _client().get_batch(client, ["CorpusId:1"], fields="corpusId,references.corpusId")
        assert route.calls.last.request.url.params["fields"] == "corpusId,references.corpusId"
        assert out == [{"corpusId": 1}]
