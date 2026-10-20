import json

import pytest

from ppr import cli
from ppr.search import verdicts

HEADER = "pid\tverdict\tround\tsource\treason\n"


def make_batch(tmp_path, n, ids):
    path = tmp_path / f"round-1-batch-{n:02d}.jsonl"
    path.write_text("".join(json.dumps({"pid" if ":" in i and not i.startswith(("s2:", "ext:")) else "id": i}) + "\n"
                            for i in ids), encoding="utf-8")
    return path


def make_verdicts(tmp_path, n, text):
    (tmp_path / f"round-1-batch-{n:02d}.verdicts.tsv").write_text(text, encoding="utf-8")


def run(tmp_path, judged=None, **kw):
    judged = judged or tmp_path / "judged.tsv"
    return verdicts.collect(str(tmp_path / "round-1-batch"), judged, kw.get("round", 1), kw.get("source", "query")), judged


def test_clean_batch_is_appended_with_round_and_source(tmp_path):
    make_batch(tmp_path, 1, ["a_2024:00000001", "s2:9"])
    make_verdicts(tmp_path, 1, "a_2024:00000001\thigh\tcore method\n\ns2:9\tno\n")
    result, judged = run(tmp_path, round=2, source="cites")
    assert result.ok and result.appended == 2
    assert judged.read_text() == HEADER + "a_2024:00000001\thigh\t2\tcites\tcore method\ns2:9\tno\t2\tcites\t\n"
    assert result.counts == {"high": 1, "medium": 0, "low": 0, "no": 1}


def test_problems_are_reported_and_valid_lines_still_appended(tmp_path):
    make_batch(tmp_path, 1, ["a_2024:00000001", "a_2024:00000002", "a_2024:00000003", "a_2024:00000004"])
    make_verdicts(tmp_path, 1, "a_2024:00000001\thigh\tok\n"
                               "a_2024:00000001\tlow\tagain\n"
                               "zzz\tlow\tstray\n"
                               "a_2024:00000003\tmaybe\tx\n")
    result, judged = run(tmp_path)
    assert not result.ok and result.appended == 1
    assert judged.read_text() == HEADER + "a_2024:00000001\thigh\t1\tquery\tok\n"
    [(path, problems)] = result.problems
    assert path.name == "round-1-batch-01.jsonl"
    assert problems["duplicate"] == ["a_2024:00000001"]
    assert problems["unknown"] == ["zzz"]
    assert problems["bad label"] == ["a_2024:00000003"]
    assert problems["missing"] == ["a_2024:00000002", "a_2024:00000003", "a_2024:00000004"]
    line = verdicts.format_problems(path, problems)
    assert line.startswith(f"{path}: missing 3 (a_2024:00000002, ") and "unknown 1 (zzz)" in line


def test_reason_whitespace_is_flattened(tmp_path):
    make_batch(tmp_path, 1, ["s2:1"])
    make_verdicts(tmp_path, 1, "s2:1\tlow\tone\ttwo\r\n")
    _, judged = run(tmp_path)
    assert judged.read_text().splitlines()[1] == "s2:1\tlow\t1\tquery\tone two"


def test_already_judged_ids_are_skipped(tmp_path):
    make_batch(tmp_path, 1, ["s2:1", "s2:2"])
    make_verdicts(tmp_path, 1, "s2:1\thigh\tr\ns2:2\tmedium\tr\n")
    judged = tmp_path / "judged.tsv"
    judged.write_text(HEADER + "s2:1\tlow\t1\tquery\told\n", encoding="utf-8")
    result, _ = run(tmp_path, judged)
    assert result.ok and result.appended == 1 and result.already == 1
    assert judged.read_text().splitlines()[1:] == ["s2:1\tlow\t1\tquery\told", "s2:2\tmedium\t1\tquery\tr"]


def test_missing_verdict_file_is_a_problem(tmp_path):
    make_batch(tmp_path, 1, ["s2:1"])
    result, judged = run(tmp_path)
    assert not result.ok and result.appended == 0
    assert result.problems[0][1] == {"verdict file missing": []}
    assert "verdict file missing" in verdicts.format_problems(*result.problems[0])


def test_no_batches(tmp_path):
    result, _ = run(tmp_path)
    assert result.batches == 0


@pytest.fixture
def go(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "no-data")  # verdicts never opens the index

    def call(*argv):
        code = 0
        try:
            cli.cmd_search(cli.build_parser().parse_args(["search", "verdicts", *argv]))
        except SystemExit as exc:
            code = exc.code
        return code, capsys.readouterr().out
    return call


def test_cli_summary_and_exit_codes(tmp_path, go):
    make_batch(tmp_path, 1, ["s2:1", "s2:2"])
    make_verdicts(tmp_path, 1, "s2:1\thigh\tr\n")
    args = [str(tmp_path / "round-1-batch"), "--judged", str(tmp_path / "judged.tsv"), "--round", "1", "--source", "web"]
    code, out = go(*args)
    assert code == 1
    assert out.splitlines()[-1] == "appended 1 (high 1, medium 0, low 0, no 0); already judged 0; batches with problems 1"
    assert "missing 1 (s2:2)" in out
    make_verdicts(tmp_path, 1, "s2:1\thigh\tr\ns2:2\tno\tr\n")
    code, out = go(*args)
    assert code == 0
    assert out.splitlines()[-1] == "appended 1 (high 0, medium 0, low 0, no 1); already judged 1; batches with problems 0"


def test_cli_without_batches_exits_1(tmp_path, go):
    code, out = go(str(tmp_path / "none"), "--judged", str(tmp_path / "j.tsv"), "--round", "1", "--source", "query")
    assert code == 1 and "no batch files" in out
