import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from ppr.s2_client import BATCH_URL, S2Client
from ppr.search import cites
from ppr.search.index import open_index
from tests.search_helpers import CDR, make_dataset


@pytest.fixture
def con(tmp_path):
    return open_index(make_dataset(tmp_path), tmp_path / ".cache" / "search.sqlite")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("ppr.s2_client.asyncio.sleep", AsyncMock())
    return S2Client(min_interval=0.0)


def link(cid, title, year=2022, venue="arXiv.org", ext=None, cited=0):
    return {"corpusId": cid, "title": title, "year": year, "venue": venue,
            "externalIds": ext or {}, "citationCount": cited}


OUT_A = link(900, "Outside Paper A", ext={"ArXiv": "2201.00001"}, cited=40)
SEED_101 = {"corpusId": 101,
            "references": [link(102, CDR), OUT_A],
            "citations": [link(104, "Erasing Concepts from Diffusion Models"), link(901, "Outside Paper B")]}
SEED_104 = {"corpusId": 104,
            "references": [OUT_A, link(101, "Machine Unlearning for Large Language Models")],
            "citations": [link(102, CDR)]}


def pid_of(con, corpus_id):
    return con.execute("SELECT pid FROM papers WHERE corpus_id = ?", (corpus_id,)).fetchone()[0]


@respx.mock
def test_counts_links_across_seeds_and_splits_inside_outside(con, client):
    route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101, SEED_104]))
    report = cites.chase(con, client, [pid_of(con, 101), "CorpusId:104"])
    assert json.loads(route.calls.last.request.content)["ids"] == ["CorpusId:101", "CorpusId:104"]
    fields = route.calls.last.request.url.params["fields"]
    assert "references.corpusId" in fields and "citations.corpusId" in fields
    assert [(x.corpus_id, x.links) for x in report.inside] == [(102, 2)]  # seeds themselves left out
    assert [(x.corpus_id, x.links) for x in report.outside] == [(900, 2)]
    assert (report.inside_total, report.outside_total, report.seeds, report.answered) == (1, 1, 2, 2)


@respx.mock
def test_direction_refs_asks_only_for_references(con, client):
    route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101]))
    cites.chase(con, client, ["CorpusId:101"], direction="refs", min_links=1)
    fields = route.calls.last.request.url.params["fields"]
    assert "references.corpusId" in fields and "citations" not in fields


@respx.mock
def test_min_links_one_shows_every_outside_paper(con, client):
    respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101, SEED_104]))
    report = cites.chase(con, client, ["CorpusId:101", "CorpusId:104"], min_links=1)
    assert [x.corpus_id for x in report.outside] == [900, 901]


@respx.mock
def test_exclude_drops_judged_papers_inside_and_outside(con, client):
    respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101, SEED_104]))
    report = cites.chase(con, client, ["CorpusId:101", "CorpusId:104"],
                         exclude=frozenset({pid_of(con, 102), "s2:900"}))
    assert report.inside == [] and report.outside == []


@respx.mock
def test_mixed_seeds_skip_only_the_unresolvable(con, client):
    route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101, None]))
    report = cites.chase(con, client, [pid_of(con, 101), "arXiv:2201.00001", "A Title Nobody Wrote"])
    assert json.loads(route.calls.last.request.content)["ids"] == ["CorpusId:101", "ARXIV:2201.00001"]
    assert report.skipped == ["A Title Nobody Wrote"] and report.answered == 1


def test_no_resolvable_seed_makes_no_request(con, client):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(BATCH_URL)
        report = cites.chase(con, client, ["A Title Nobody Wrote"])
    assert not route.called and report.seeds == 0 and report.skipped == ["A Title Nobody Wrote"]


@respx.mock
def test_semantic_scholar_down_raises(con, client):
    respx.post(BATCH_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(cites.S2Unavailable):
        cites.chase(con, client, ["CorpusId:101"])


@respx.mock
def test_abstract_fetches_outside_snippets(con, client):
    respx.post(BATCH_URL).mock(side_effect=[
        httpx.Response(200, json=[SEED_101, SEED_104]),
        httpx.Response(200, json=[{"corpusId": 900, "tldr": {"model": "tldr@v2.0.0", "text": "An outside tldr."},
                                   "abstract": "Long abstract."}]),
    ])
    report = cites.chase(con, client, ["CorpusId:101", "CorpusId:104"], abstracts=True)
    assert report.outside[0].snippet == "An outside tldr."


@respx.mock
def test_format_and_records(con, client):
    respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101, SEED_104]))
    report = cites.chase(con, client, ["CorpusId:101", "CorpusId:104"])
    lines = cites.format_report(report).splitlines()
    assert lines[0] == "cites · 2 seeds (2 answered) · both"
    assert lines[1] == "in dataset (1, showing 1)"
    assert lines[2].startswith("  2 links | ") and lines[2].endswith(f"| 700 cites | {CDR}")
    assert lines[3] == "outside (1 with ≥2 links, showing 1)"
    assert lines[4] == "  2 links | s2:900 | 2022 | arXiv.org | arXiv:2201.00001 | 40 cites | Outside Paper A"
    records = cites.report_records(report)
    assert [(r["group"], r["links"]) for r in records] == [("dataset", 2), ("outside", 2)]
    assert records[0]["pid"] == pid_of(con, 102) and records[1]["id"] == "s2:900"


@respx.mock
def test_duplicate_seeds_are_sent_and_counted_once(con, client):
    route = respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[SEED_101]))
    report = cites.chase(con, client, [pid_of(con, 101), "CorpusId:101"], min_links=1)
    assert json.loads(route.calls.last.request.content)["ids"] == ["CorpusId:101"]
    assert report.seeds == 1 and [(x.corpus_id, x.links) for x in report.inside] == [(102, 1), (104, 1)]


@respx.mock
def test_linked_dataset_paper_with_another_corpus_id_is_matched_by_title(con, client):
    seeds = [{"corpusId": 101, "references": [link(77777, CDR.upper() + "."), link(88888, "Nobody Wrote This")]},
             {"corpusId": 104, "references": [link(77777, CDR), link(88888, "Nobody Wrote This")]}]
    respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=seeds))
    report = cites.chase(con, client, ["CorpusId:101", "CorpusId:104"])
    assert [x.rows[0]["title"] for x in report.inside] == [CDR]
    assert [x.corpus_id for x in report.outside] == [88888]
