import json
from datetime import date

import pytest

from ppr.layout import papers_path
from ppr.models import Paper
from ppr.register import render_openreview_config
from ppr.store import read_papers, save_crawl, save_enriched
from ppr.rolling import RollingOutcome, due_ids, format_summary, recrawl_rolling, results_to_json
from ppr.venues import load_registry


def _papers(forum_ids):
    return [Paper(title=f"T {f}", link="", authors=["A"], selection="main", forum_id=f) for f in forum_ids]


def _seed(data_dir, conf_id, forum_ids):
    save_crawl(_papers(forum_ids), papers_path(data_dir, conf_id))


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


def test_last_year_is_due_january_through_march_and_unregistered_years_are_skipped(env):
    registry, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a"])
    _seed(data_dir, "iclr_2026", ["a"])
    assert due_ids(registry, data_dir, configs_dir, date(2027, 1, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2026, 11, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2027, 2, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2027, 3, 3)) == ["tmlr_2026"]
    assert due_ids(registry, data_dir, configs_dir, date(2027, 4, 3)) == []


def test_january_lists_last_year_before_this_year(env):
    registry, data_dir, configs_dir = env
    (configs_dir / "tmlr_2027.yaml").write_text(
        render_openreview_config("TMLR", 2027, "TMLR", {"main": "Accepted by TMLR"}, year_from_pdate=True),
        encoding="utf-8",
    )
    _seed(data_dir, "tmlr_2026", ["a"])
    _seed(data_dir, "tmlr_2027", ["a"])
    assert due_ids(registry, data_dir, configs_dir, date(2027, 1, 3)) == ["tmlr_2026", "tmlr_2027"]


def test_a_growing_crawl_is_written(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a", "b"])
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: _papers(["a", "b", "c"]))
    assert (o.status, o.before, o.after) == ("recrawled", 2, 3)
    assert len(_lines(papers_path(data_dir, "tmlr_2026"))) == 3


def test_a_recrawl_keeps_the_papers_enrichment(env):
    registry, data_dir, configs_dir = env
    path = papers_path(data_dir, "tmlr_2026")
    enriched = _papers(["a", "b"])
    for p in enriched:
        p.citation_count = 5
    save_enriched(enriched, path)
    recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda config: _papers(["a", "b", "c"]))
    assert sorted((p.forum_id, p.citation_count) for p in read_papers(path)) == [("a", 5), ("b", 5), ("c", None)]


def test_a_vanished_paper_holds_even_when_the_count_grows(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a", "b"])
    path = papers_path(data_dir, "tmlr_2026")
    before = path.read_bytes()
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: _papers(["a", "c", "d"]))
    assert o.status == "held" and "b" in o.reason and "crawl returned 3" in o.reason
    assert path.read_bytes() == before


def test_an_empty_crawl_holds_and_keeps_the_file(env):
    _, data_dir, configs_dir = env
    _seed(data_dir, "tmlr_2026", ["a"])
    path = papers_path(data_dir, "tmlr_2026")
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
    save_crawl(old, papers_path(data_dir, "tmlr_2026"))
    new = old + [Paper(title="Other", link="", authors=["A"], selection="main")]
    (o,) = recrawl_rolling(["tmlr_2026"], configs_dir, data_dir, lambda cfg: new)
    assert o.status == "recrawled"


def test_report_shape_and_summary():
    outs = [RollingOutcome("tmlr_2026", "recrawled", 2, 3), RollingOutcome("tmlr_2025", "held", 5, 0, "x")]
    assert json.loads(results_to_json(outs))["results"][0] == {
        "conf_id": "tmlr_2026", "status": "recrawled", "before": 2, "after": 3, "reason": ""}
    assert "tmlr_2026" in format_summary(outs) and "held" in format_summary(outs)
