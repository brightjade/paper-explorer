import json

import pytest

from ppr import cli
from ppr.search import batch


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def paper(pid, title="T"):
    return {"pid": pid, "title": title, "abstract": "a"}


def test_a_paper_found_twice_is_kept_once(tmp_path):
    found = write_jsonl(tmp_path / "round-1-find.jsonl", [paper("iclr_2024:aaaaaaaa"), paper("iclr_2024:bbbbbbbb")])
    cited = write_jsonl(tmp_path / "round-1-cites.jsonl",
                        [{"group": "dataset", "links": 3, **paper("iclr_2024:aaaaaaaa")},
                         {"group": "outside", "id": "s2:900", "title": "Out"}])
    cands = batch.collect([found, cited])
    assert [c.get("pid") or c["id"] for c in cands] == ["iclr_2024:aaaaaaaa", "iclr_2024:bbbbbbbb", "s2:900"]
    assert "links" not in cands[0]  # the first occurrence wins


def test_lookup_records_flatten(tmp_path):
    lookups = write_jsonl(tmp_path / "round-0-external.jsonl", [
        {"input": "2401.00001", "kind": "arxiv", "status": "found", "papers": [paper("a_2024:11111111"), paper("b_2023:22222222")]},
        {"input": "arXiv:2501.99999", "kind": "arxiv", "status": "not in dataset", "papers": []},
        {"input": "A Title: Nobody Wrote!! ;; Ann", "kind": "title", "status": "not in dataset", "papers": []},
        {"input": "10.1000/XYZ", "kind": "doi", "status": "not in dataset", "papers": []},
    ])
    cands = batch.collect([lookups])
    assert [c.get("pid") or c["id"] for c in cands] == [
        "a_2024:11111111", "b_2023:22222222", "ext:2501.99999", "ext:a-title-nobody-wrote", "ext:10.1000/xyz"]
    assert cands[2] == {"id": "ext:2501.99999", "title": "arXiv:2501.99999", "group": "external"}


def test_slug_is_capped_at_60_chars():
    assert len(batch.external_id("word " * 40)) == len("ext:") + 59  # no trailing dash


def test_judged_ids_are_dropped(tmp_path):
    f = write_jsonl(tmp_path / "f.jsonl", [paper("x_2024:00000001"), paper("x_2024:00000002"),
                                           {"id": "s2:900", "title": "Out", "group": "outside"}])
    judged = tmp_path / "judged.tsv"
    judged.write_text("pid\tverdict\nx_2024:00000001\thigh\ns2:900\tlow\n", encoding="utf-8")
    from ppr.search.find import read_exclude
    assert [c["pid"] for c in batch.collect([f], read_exclude(judged))] == ["x_2024:00000002"]


def test_batches_are_sized_and_numbered(tmp_path):
    cands = [paper(f"x_2024:{i:08d}") for i in range(5)]
    written = batch.write_batches(cands, str(tmp_path / "round-1-batch"), size=2)
    assert [(p.name, n) for p, n in written] == [
        ("round-1-batch-01.jsonl", 2), ("round-1-batch-02.jsonl", 2), ("round-1-batch-03.jsonl", 1)]
    assert len((tmp_path / "round-1-batch-03.jsonl").read_text().splitlines()) == 1


@pytest.fixture
def run(capsys):
    def go(*argv):
        cli.cmd_search(cli.build_parser().parse_args(["search", "batch", *argv]))
        return capsys.readouterr().out
    return go


def test_cli_prints_one_line_per_file_and_a_summary(tmp_path, run, monkeypatch):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "no-data")  # batch never opens the index
    f = write_jsonl(tmp_path / "f.jsonl", [paper(f"x_2024:{i:08d}") for i in range(3)])
    prefix = tmp_path / "out" / "round-1-batch"
    out = run(str(f), "--out", str(prefix), "--size", "2").splitlines()
    assert out == [f"{prefix}-01.jsonl\t2", f"{prefix}-02.jsonl\t1", "3 candidates in 2 batches"]


def test_cli_with_no_candidates_writes_nothing(tmp_path, run):
    f = write_jsonl(tmp_path / "f.jsonl", [paper("x_2024:00000001")])
    judged = tmp_path / "judged.tsv"
    judged.write_text("x_2024:00000001\thigh\n", encoding="utf-8")
    assert run(str(f), "--out", str(tmp_path / "b"), "--exclude", str(judged)) == "0 candidates\n"
    assert not list(tmp_path.glob("b-*"))
