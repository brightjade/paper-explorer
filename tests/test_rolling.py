import json
from datetime import date

import pytest

from ppr.models import Paper, write_papers
from ppr.register import render_openreview_config
from ppr.rolling import RollingOutcome, due_ids, format_summary, recrawl_rolling, results_to_json
from ppr.venues import load_registry


def _papers(forum_ids):
    return [Paper(title=f"T {f}", link="", authors=["A"], selection="main", forum_id=f) for f in forum_ids]


def _seed(data_dir, conf_id, forum_ids):
    (data_dir / conf_id).mkdir(parents=True, exist_ok=True)
    write_papers(_papers(forum_ids), data_dir / conf_id / "papers.jsonl")


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def env(tmp_path):
    venues = tmp_path / "venues.yaml"
    venues.write_text(
        "venues:\n"
        "  tmlr:\n    name: TMLR\n    source: openreview\n    cadence: annual\n"
        "    announce_month: 1\n    rolling: true\n    probe: {venue_id: TMLR}\n"
        "  iclr:\n    name: ICLR\n    source: openreview\n    cadence: annual\n"
        "    announce_month: 1\n    probe: {venue_id: \"ICLR.cc/{year}/Conference\"}\n",
        encoding="utf-8",
    )
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    (configs_dir / "tmlr_2026.yaml").write_text(
        render_openreview_config("TMLR", 2026, "TMLR", {"main": "Accepted by TMLR"}, year_from_pdate=True),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return load_registry(venues), data_dir, configs_dir


def test_january_adds_last_year_and_skips_unregistered_years(env):
    registry, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a"])
    _seed(data_dir, "iclr_2026", ["a"])
    assert due_ids(registry, data_dir, configs_dir, date(2027, 1, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2026, 11, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2027, 2, 3)) == []


def test_a_growing_crawl_is_written(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a", "b"])
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: _papers(["a", "b", "c"]))
    assert (o.status, o.before, o.after) == ("recrawled", 2, 3)
    assert len(_lines(data_dir / "tmlr_2026" / "papers.jsonl")) == 3


def test_a_vanished_paper_holds_even_when_the_count_grows(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a", "b"])
    path = data_dir / "tmlr_2026" / "papers.jsonl"
    before = path.read_bytes()
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: _papers(["a", "c", "d"]))
    assert o.status == "held" and "b" in o.reason
    assert path.read_bytes() == before


def test_an_empty_crawl_holds_and_keeps_the_file(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a"])
    path = data_dir / "tmlr_2026" / "papers.jsonl"
    before = path.read_bytes()
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: [])
    assert o.status == "held"
    assert path.read_bytes() == before


def test_a_raising_fetch_fails_that_venue_only(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a"])

    def boom(cfg):
        raise RuntimeError("login refused")

    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, boom)
    assert o.status == "failed" and "RuntimeError" in o.reason


def test_papers_without_a_forum_id_are_keyed_by_title(env):
    _, data_dir, configs_dir = env
    old = [Paper(title="Same Title", link="", authors=["A"], selection="main")]
    (data_dir / "tmlr_2026").mkdir()
    write_papers(old, data_dir / "tmlr_2026" / "papers.jsonl")
    new = old + [Paper(title="Other", link="", authors=["A"], selection="main")]
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: new)
    assert o.status == "recrawled"


def test_report_shape_and_summary():
    outs = [RollingOutcome("tmlr_2026", "recrawled", 2, 3), RollingOutcome("tmlr_2025", "held", 5, 0, "x")]
    assert json.loads(results_to_json(outs))["results"][0] == {
        "conf_id": "tmlr_2026", "status": "recrawled", "before": 2, "after": 3, "reason": ""}
    assert "tmlr_2026" in format_summary(outs) and "held" in format_summary(outs)
