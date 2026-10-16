import json

import pytest
import requests

from ppr.awards.collect import (
    SOURCES_BY_PREFIX,
    collect_all,
    collect_conference,
    conference_ids,
    format_summary,
    results_to_json,
)
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.manual import MANUAL_DIR
from ppr.awards.model import Award, awards_path, read_awards, write_awards


def _a(label, kind, title, via):
    return Award(label=label, kind=kind, title=title, via=via, source=f"https://{via}.test/")


def _src(result):
    calls = []

    def source(conf_id, year, earlier):
        calls.append((conf_id, year, [a.title for a in earlier]))
        if isinstance(result, Exception):
            raise result
        return result

    source.calls = calls
    return source


@pytest.fixture
def demo(monkeypatch, tmp_path):
    """A fake venue "demo" with sources "a" then "b", and a demo_2025 with two papers."""
    conf_dir = tmp_path / "demo_2025"
    conf_dir.mkdir()
    (conf_dir / "papers.jsonl").write_text(
        json.dumps({"title": "Won"}) + "\n" + json.dumps({"title": "Also"}) + "\n", encoding="utf-8")

    def install(a, b):
        sources = (_src(a), _src(b))
        monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [("a", sources[0]), ("b", sources[1])])
        return sources

    return install


def _previous(tmp_path, *awards):
    write_awards(awards_path(tmp_path, "demo_2025"), "demo_2025", list(awards))
    return awards_path(tmp_path, "demo_2025").read_bytes()


def test_award_titles_follow_the_paper_with_the_same_forum_id(monkeypatch, tmp_path):
    conf_dir = tmp_path / "demo_2025"
    conf_dir.mkdir()
    (conf_dir / "papers.jsonl").write_text(
        json.dumps({"title": "AlphaEdit: Null-Space Editing", "forum_id": "f1"}) + "\n", encoding="utf-8")
    first = Award(label="Outstanding Papers", kind="award", title="AlphaEdit (Null-Space Constrained Editing)", via="a",
                  source="https://a.test/", forum_id="f1")
    monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [
        ("a", _src([first])), ("b", _src([_a("Best Paper", "award", "AlphaEdit: Null-Space Editing", "b")]))])
    out = collect_conference("demo_2025", tmp_path)
    assert (out.status, out.count, out.matched) == ("collected", 1, 1)
    [only] = read_awards(awards_path(tmp_path, "demo_2025"))
    assert (only.via, only.title, only.forum_id) == ("a", "AlphaEdit: Null-Space Editing", "f1")


class TestOutcomes:
    def test_collected_writes_the_merge_and_counts_joins(self, demo, tmp_path):
        demo([_a("Best Paper", "award", "Won", "a")],
             [_a("Test of Time Award", "test_of_time", "Old", "b"), _a("Honorable Mention", "honorable", "Missing", "b")])
        out = collect_conference("demo_2025", tmp_path)
        assert (out.status, out.count, out.matched, out.unmatched) == ("collected", 3, 1, ["Missing"])
        assert [a.title for a in read_awards(awards_path(tmp_path, "demo_2025"))] == ["Won", "Missing", "Old"]

    def test_later_sources_see_what_earlier_ones_found(self, demo, tmp_path):
        _, b = demo([_a("Best Paper", "award", "Won", "a")], [])
        collect_conference("demo_2025", tmp_path)
        assert b.calls == [("demo_2025", 2025, ["Won"])]

    def test_nothing_published_yet_writes_nothing(self, demo, tmp_path):
        demo([], None)
        assert collect_conference("demo_2025", tmp_path).status == "not-yet"
        assert not awards_path(tmp_path, "demo_2025").exists()

    def test_unknown_label_holds_and_keeps_the_file(self, demo, tmp_path):
        before = _previous(tmp_path, _a("Best Paper", "award", "Won", "a"))
        demo(UnknownAwardLabel("no award rule matches 'Spotlight Prize'"), [])
        out = collect_conference("demo_2025", tmp_path)
        assert out.status == "held" and "Spotlight Prize" in out.reason
        assert awards_path(tmp_path, "demo_2025").read_bytes() == before

    def test_everything_going_empty_holds(self, demo, tmp_path):
        before = _previous(tmp_path, _a("Best Paper", "award", "Won", "a"))
        demo([], [])
        out = collect_conference("demo_2025", tmp_path)
        assert (out.status, out.count) == ("held", 1)
        assert awards_path(tmp_path, "demo_2025").read_bytes() == before

    def test_a_source_that_went_quiet_holds(self, demo, tmp_path):
        before = _previous(tmp_path, _a("Best Paper", "award", "Won", "a"),
                           _a("Honorable Mention", "honorable", "Also", "b"))
        demo([], [_a("Honorable Mention", "honorable", "Also", "b")])
        out = collect_conference("demo_2025", tmp_path)
        assert out.status == "held" and out.reason.startswith("a returned nothing")
        assert awards_path(tmp_path, "demo_2025").read_bytes() == before

    def test_a_source_that_chose_not_to_run_is_not_lost(self, demo, tmp_path):
        _previous(tmp_path, _a("Best Paper", "award", "Won", "a"), _a("Honorable Mention", "honorable", "Also", "b"))
        demo([_a("Best Paper", "award", "Won", "a")], None)
        assert collect_conference("demo_2025", tmp_path).status == "collected"

    def test_a_failing_source_keeps_the_file(self, demo, tmp_path):
        before = _previous(tmp_path, _a("Best Paper", "award", "Won", "a"))
        demo(requests.ConnectionError("down"), [])
        out = collect_conference("demo_2025", tmp_path)
        assert (out.status, out.reason) == ("failed", "ConnectionError: down")
        assert awards_path(tmp_path, "demo_2025").read_bytes() == before

    def test_a_venue_without_a_rule_fails(self, tmp_path):
        assert collect_conference("acl_2025", tmp_path).status == "failed"

    def test_a_rerun_with_nothing_new_is_byte_identical(self, demo, tmp_path):
        demo([_a("Best Paper", "award", "Won", "a")], [])
        collect_conference("demo_2025", tmp_path)
        first = awards_path(tmp_path, "demo_2025").read_bytes()
        collect_conference("demo_2025", tmp_path)
        assert awards_path(tmp_path, "demo_2025").read_bytes() == first

    def test_collect_all_and_the_report(self, demo, tmp_path):
        demo([], None)
        outcomes = collect_all(["demo_2025", "acl_2025"], tmp_path)
        assert [o.status for o in outcomes] == ["not-yet", "failed"]
        report = json.loads(results_to_json(outcomes))
        assert report["results"][0] == {"conf_id": "demo_2025", "status": "not-yet", "count": 0,
                                        "matched": 0, "unmatched": [], "reason": ""}

    def test_format_summary(self, demo, tmp_path):
        demo([_a("Best Paper", "award", "Won", "a"), _a("Best Paper", "award", "Gone", "a")], [])
        text = format_summary([collect_conference("demo_2025", tmp_path)])
        assert "demo_2025" in text and "collected" in text and "2 entries, 1 on papers, 1 matching no paper" in text


class TestRegistry:
    def test_tranche_one_venues_have_rules(self):
        assert set(SOURCES_BY_PREFIX) >= {"neurips", "icml", "iclr", "cvpr", "iccv", "eccv", "wacv",
                                          "icse", "fse", "ase", "issta", "usenix_security"}

    def test_via_names_are_unique_per_venue(self):
        for prefix, sources in SOURCES_BY_PREFIX.items():
            names = [name for name, _ in sources]
            assert len(names) == len(set(names)), prefix

    def test_se_venues_consult_manual_before_sigsoft(self):
        for prefix in ("icse", "fse", "ase", "issta"):
            assert [name for name, _ in SOURCES_BY_PREFIX[prefix]] == ["researchr", "manual", "sigsoft"]

    def test_every_manual_file_belongs_to_a_venue_that_reads_manual_files(self):
        for path in MANUAL_DIR.glob("*.yaml"):
            prefix = path.stem.rpartition("_")[0]
            assert "manual" in [name for name, _ in SOURCES_BY_PREFIX[prefix]], path.name

    def test_conference_ids_are_the_data_dirs_of_venues_with_rules(self, tmp_path):
        for name in ("iclr_2025", "acl_2025", "usenix_security_2025", "iclr_2019"):
            (tmp_path / name).mkdir()
        (tmp_path / "pipeline_state.json").write_text("{}")
        assert conference_ids(tmp_path) == ["iclr_2025", "usenix_security_2025"]
        assert conference_ids(tmp_path / "missing") == []


class TestTailFailures:
    def test_a_corrupt_awards_file_fails_and_stays_untouched(self, demo, tmp_path):
        demo([_a("Best Paper", "award", "Won", "a")], [])
        path = awards_path(tmp_path, "demo_2025")
        path.write_text("{not json", encoding="utf-8")
        out = collect_conference("demo_2025", tmp_path)
        assert out.status == "failed" and "JSONDecodeError" in out.reason
        assert path.read_bytes() == b"{not json"

    def test_one_bad_conference_does_not_stop_the_next(self, demo, tmp_path, monkeypatch):
        demo([_a("Best Paper", "award", "Won", "a")], [])
        bad = tmp_path / "demo_2024"
        bad.mkdir()
        (bad / "papers.jsonl").write_text("{broken\n", encoding="utf-8")
        outs = collect_all(["demo_2024", "demo_2025"], tmp_path)
        assert [o.status for o in outs] == ["failed", "collected"]


class TestLostSource:
    def test_a_source_covered_by_another_is_not_lost(self, demo, tmp_path):
        _previous(tmp_path, _a("Best Paper Candidate", "candidate", "Won", "a"),
                  _a("Best Paper Candidate", "candidate", "Also", "a"))
        demo([], [_a("Best Paper Candidate", "candidate", "Won", "b"),
                  _a("Best Paper Candidate", "candidate", "Also", "b")])
        out = collect_conference("demo_2025", tmp_path)
        assert (out.status, out.count) == ("collected", 2)
        assert {a.via for a in read_awards(awards_path(tmp_path, "demo_2025"))} == {"b"}


def test_conference_ids_start_tmlr_at_2022(tmp_path):
    for d in ("tmlr_2022", "iclr_2022", "iclr_2023"):
        (tmp_path / d).mkdir()
    assert conference_ids(tmp_path) == ["iclr_2023", "tmlr_2022"]
