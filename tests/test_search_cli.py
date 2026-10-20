import json

import pytest

from ppr import cli
from ppr.search import cites
from tests.search_helpers import MU, make_dataset


@pytest.fixture
def search_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA_DIR", make_dataset(tmp_path))
    monkeypatch.setattr(cli, "SEARCH_INDEX", tmp_path / ".cache" / "search.sqlite")
    return tmp_path


def run(*argv):
    cli.cmd_search(cli.build_parser().parse_args(["search", *argv]))


def test_find_prints_ranked_lines(search_env, capsys):
    run("find", "unlearning", "--abstract")
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "1 matches · showing 1–1 · relevance"
    assert out[1].endswith(f"| ICLR 2024 · oral · Outstanding Paper | 120 cites | {MU}")
    assert out[2] == "    An unlearning method for LLMs."


def test_find_json_is_one_record_per_line(search_env, capsys):
    run("find", "concept erasure", "data deletion", "--sort", "citations", "--json")
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["corpus_id"] for r in rows] == [102, 104]


def test_find_filters_and_exclude(search_env, capsys):
    judged = search_env / "judged.tsv"
    run("find", "unlearning", "data deletion", "concept erasure", "--json", "--limit", "1")
    first = json.loads(capsys.readouterr().out)["pid"]
    judged.write_text(f"{first}\thigh\n", encoding="utf-8")
    run("find", "unlearning", "data deletion", "concept erasure", "--venue", "iclr,cvpr",
        "--years", "2023-2024", "--exclude", str(judged))
    assert capsys.readouterr().out.startswith("2 matches")
    run("find", "unlearning", "data deletion", "--selection", "poster")
    assert capsys.readouterr().out.startswith("1 matches")


def test_bad_query_exits_2(search_env, capsys):
    with pytest.raises(SystemExit) as exc:
        run("find", "--raw", '"unclosed')
    assert exc.value.code == 2 and capsys.readouterr().err.startswith("error:")
    with pytest.raises(SystemExit) as exc:
        run("find", "x", "--years", "soon")
    assert exc.value.code == 2


def test_lookup_items_and_file(search_env, capsys):
    f = search_env / "asta.txt"
    f.write_text("# from Asta\nCorpusId:999\n", encoding="utf-8")
    run("lookup", "2401.00001", "--file", str(f))
    out = capsys.readouterr().out
    assert out.startswith("found\t2401.00001\n    iclr_2024:")
    assert out.rstrip().endswith("not in dataset\tCorpusId:999")


def test_lookup_json(search_env, capsys):
    run("lookup", "CorpusId:101", "--json")
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "found" and record["papers"][0]["title"] == MU


def test_lookup_needs_something(search_env):
    with pytest.raises(SystemExit):
        run("lookup")


def test_cites_passes_options_through(search_env, capsys, monkeypatch):
    seen = {}

    def fake_chase(con, client, seeds, direction, min_links, limit, exclude, abstracts):
        seen.update(seeds=seeds, direction=direction, min_links=min_links, limit=limit, abstracts=abstracts)
        return cites.CitesReport(1, 1, [], direction, min_links, [], [], 0, 0)

    monkeypatch.setattr(cites, "chase", fake_chase)
    run("cites", "CorpusId:101", "--direction", "refs", "--min-links", "1", "--limit", "5", "--abstract")
    assert seen == {"seeds": ["CorpusId:101"], "direction": "refs", "min_links": 1, "limit": 5, "abstracts": True}
    assert capsys.readouterr().out.startswith("cites · 1 seeds (1 answered) · refs")


def test_cites_s2_down_exits_1(search_env, monkeypatch):
    def down(*args, **kwargs):
        raise cites.S2Unavailable("unreachable")

    monkeypatch.setattr(cites, "chase", down)
    with pytest.raises(SystemExit) as exc:
        run("cites", "CorpusId:101")
    assert "unreachable" in str(exc.value.code)


@pytest.mark.parametrize("argv", [("find", "x"), ("lookup", "2401.00001"), ("cites", "CorpusId:1")])
def test_no_data_exits_with_the_sync_hint(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cli, "SEARCH_INDEX", tmp_path / ".cache" / "search.sqlite")
    with pytest.raises(SystemExit) as exc:
        run(*argv)
    assert "sync_data" in str(exc.value.code)


def test_main_dispatches_search(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "cmd_search", lambda args: called.append(args.search_command))
    monkeypatch.setattr("sys.argv", ["ppr", "search", "find", "x"])
    cli.main()
    assert called == ["find"]
