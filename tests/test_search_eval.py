import json

import httpx
import pytest
import respx

from ppr.s2_client import BATCH_URL, S2Client
from ppr.search.index import open_index
from scripts import search_eval
from tests.search_helpers import CDR, ERASE, MU, make_dataset


@pytest.fixture
def con(tmp_path):
    return open_index(make_dataset(tmp_path), tmp_path / ".cache" / "search.sqlite")


def pids(con, *titles):
    return [con.execute("SELECT pid FROM papers WHERE title = ?", (t,)).fetchone()[0] for t in titles]


def gold_file(tmp_path, con, queries, *titles):
    path = tmp_path / "topic.json"
    path.write_text(json.dumps({"topic": "unlearning", "queries": queries,
                                "gold": [{"pid": p} for p in pids(con, *titles)]}), encoding="utf-8")
    return path


def test_recall():
    assert search_eval.recall({"a", "b"}, {"b", "c"}) == 0.5
    assert search_eval.recall(set(), set()) == 0.0


def test_grep_is_a_substring_match_and_find_stems(con):
    grep = search_eval.grep_candidates(con, ["removal"])
    found = search_eval.find_candidates(con, ["removal"], k=50)
    assert set(grep) == set(pids(con, CDR))  # "removing", "removes" are not substrings of "removal"
    assert set(found) == set(pids(con, CDR, MU, ERASE))
    assert all(size > 0 for size in [*grep.values(), *found.values()])


def test_evaluate_without_cites(con, tmp_path):
    result = search_eval.evaluate(con, gold_file(tmp_path, con, ["removal"], CDR, MU, ERASE), k=50, client=None)
    assert result["gold"] == 3
    assert result["grep"]["recall"] == pytest.approx(1 / 3)
    assert result["find"]["recall"] == 1.0
    assert "find+cites" not in result
    table = search_eval.format_table([result])
    assert "| unlearning | 3 |" in table


@respx.mock
def test_draft_gold_keeps_references_in_the_dataset(con):
    respx.post(BATCH_URL).mock(return_value=httpx.Response(200, json=[{
        "title": "A Survey of Unlearning",
        "references": [{"corpusId": 101, "title": MU}, {"corpusId": 999, "title": "Elsewhere"},
                       {"corpusId": None, "title": "No id"}]}]))
    draft = search_eval.draft_gold(con, S2Client(min_interval=0.0), "unlearning", "ARXIV:2310.00001")
    assert draft["survey"] == {"id": "ARXIV:2310.00001", "title": "A Survey of Unlearning"}
    assert (draft["references_total"], draft["references_in_dataset"]) == (2, 1)
    assert [g["title"] for g in draft["gold"]] == [MU]
    assert draft["queries"] == [] and draft["excluded"] == []


def test_score_run_classifies_misses(con, tmp_path):
    mu, cdr, erase = pids(con, MU, CDR, ERASE)
    run = tmp_path / "run"
    run.mkdir()
    (run / "judged.tsv").write_text(
        f"pid\tverdict\tround\tsource\treason\n{mu}\thigh\t1\tquery\tx\n{cdr}\tno\t1\tquery\tx\n"
        "s2:900\tmedium\t2\tcites\tx\n", encoding="utf-8")
    score = search_eval.score_run(con, gold_file(tmp_path, con, [], MU, CDR, ERASE), run)
    assert score["recall"] == pytest.approx(1 / 3)
    assert score["misses"] == {"never_candidate": 1, "judged_out": 1, "no_abstract": 0}
    assert score["found_not_gold"] == ["s2:900"]


def test_score_list_grounds_titles(con, tmp_path):
    listing = tmp_path / "refs.txt"
    listing.write_text(f"{MU}\nA Title Nobody Wrote\n", encoding="utf-8")
    score = search_eval.score_list(con, gold_file(tmp_path, con, [], MU, CDR), listing)
    assert score["recall"] == 0.5 and score["unmatched"] == 1
