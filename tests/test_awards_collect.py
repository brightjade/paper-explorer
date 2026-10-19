import json
from datetime import date

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
from ppr.awards import manual as manual_module
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.manual import CONFIGS_DIR
from ppr.layout import manual_awards_path, papers_path
from ppr.awards.model import Award, awards_path, read_awards, write_awards


def _write_papers(data_dir, conf_id, text):
    path = papers_path(data_dir, conf_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    _write_papers(tmp_path, "demo_2025", json.dumps({"title": "Won"}) + "\n" + json.dumps({"title": "Also"}) + "\n")

    def install(a, b):
        sources = (_src(a), _src(b))
        monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [("a", sources[0]), ("b", sources[1])])
        return sources

    return install


def _previous(tmp_path, *awards):
    write_awards(tmp_path, "demo_2025", list(awards))
    return awards_path(tmp_path, "demo_2025").read_bytes()


def test_award_titles_follow_the_paper_with_the_same_forum_id(monkeypatch, tmp_path):
    _write_papers(tmp_path, "demo_2025", json.dumps({"title": "AlphaEdit: Null-Space Editing", "forum_id": "f1"}) + "\n")
    first = Award(label="Outstanding Papers", kind="award", title="AlphaEdit (Null-Space Constrained Editing)", via="a",
                  source="https://a.test/", forum_id="f1")
    monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [
        ("a", _src([first])), ("b", _src([_a("Best Paper", "award", "AlphaEdit: Null-Space Editing", "b")]))])
    out = collect_conference("demo_2025", tmp_path)
    assert (out.status, out.count, out.matched) == ("collected", 1, 1)
    [only] = read_awards(tmp_path, "demo_2025")
    assert (only.via, only.title, only.forum_id) == ("a", "AlphaEdit: Null-Space Editing", "f1")


class TestOutcomes:
    def test_collected_writes_the_merge_and_counts_joins(self, demo, tmp_path):
        demo([_a("Best Paper", "award", "Won", "a")],
             [_a("Test of Time Award", "test_of_time", "Old", "b"), _a("Honorable Mention", "honorable", "Missing", "b")])
        out = collect_conference("demo_2025", tmp_path)
        assert (out.status, out.count, out.matched, out.unmatched) == ("collected", 3, 1, ["Missing"])
        assert [a.title for a in read_awards(tmp_path, "demo_2025")] == ["Won", "Old", "Missing"]

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

    def test_every_manual_file_belongs_to_a_venue_that_reads_manual_files(self):
        for path in CONFIGS_DIR.glob("*/awards/*.yaml"):
            prefix = path.parent.parent.name
            assert "manual" in [name for name, _ in SOURCES_BY_PREFIX[prefix]], path


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
        _write_papers(tmp_path, "demo_2024", "{broken\n")
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
        assert {a.via for a in read_awards(tmp_path, "demo_2025")} == {"b"}


class TestConferenceIds:
    @pytest.fixture(autouse=True)
    def manual_dir(self, tmp_path_factory, monkeypatch):
        """No manual files unless a test writes one: the window tests must not depend on configs/."""
        d = tmp_path_factory.mktemp("manual")
        monkeypatch.setattr(manual_module, "CONFIGS_DIR", d)
        return d

    @staticmethod
    def _dirs(tmp_path, *names):
        for name in names:
            _write_papers(tmp_path, name, "")
        (tmp_path / "pipeline_state.json").write_text("{}")

    def test_an_old_year_with_a_manual_file_but_no_awards_file_is_retried(self, tmp_path, manual_dir):
        # neurips_2014 failed on a 503 in the one all-years run (2026-10-17): its
        # reviewed list must not wait for the next all-years run.
        self._dirs(tmp_path, "neurips_2013", "neurips_2014", "neurips_2015", "neurips_2026")
        for conf_id in ("neurips_2013", "neurips_2014"):
            path = manual_awards_path(manual_dir, conf_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("awards: []\n", encoding="utf-8")
        write_awards(tmp_path, "neurips_2013",
                     [Award("Outstanding Paper Award", "award", "P", "manual", "https://x.test/")])
        assert conference_ids(tmp_path, date(2026, 10, 18)) == ["neurips_2014", "neurips_2026"]

    def test_this_year_and_last_year_of_venues_with_rules(self, tmp_path):
        self._dirs(tmp_path, "iclr_2024", "iclr_2025", "iclr_2026", "acl_2026", "usenix_security_2025")
        assert conference_ids(tmp_path, date(2026, 10, 17)) == ["iclr_2025", "iclr_2026", "usenix_security_2025"]

    def test_the_window_moves_with_the_year(self, tmp_path):
        self._dirs(tmp_path, "iclr_2025", "iclr_2026", "iclr_2027")
        assert conference_ids(tmp_path, date(2027, 1, 5)) == ["iclr_2026", "iclr_2027"]

    def test_tmlr_keeps_every_year_from_2022(self, tmp_path):
        self._dirs(tmp_path, "tmlr_2021", "tmlr_2022", "tmlr_2023", "iclr_2022")
        assert conference_ids(tmp_path, date(2026, 10, 17)) == ["tmlr_2022", "tmlr_2023"]

    def test_all_years_drops_the_year_test(self, tmp_path):
        self._dirs(tmp_path, "cvpr_2013", "iclr_2024", "acl_2013")
        assert conference_ids(tmp_path, date(2026, 10, 17), all_years=True) == ["cvpr_2013", "iclr_2024"]

    def test_missing_data_dir(self, tmp_path):
        assert conference_ids(tmp_path / "missing") == []


def _manual_file(monkeypatch, tmp_path, body):
    configs_dir = tmp_path / "configs"
    path = manual_awards_path(configs_dir, "demo_2025")
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(manual_module, "CONFIGS_DIR", configs_dir)


class TestManualFirst:
    def test_every_venue_reads_its_manual_file_first(self):
        for prefix, sources in SOURCES_BY_PREFIX.items():
            if prefix != "tmlr":
                assert sources[0][0] == "manual", prefix

    def test_se_venues_consult_researchr_then_sigsoft_after_manual(self):
        for prefix in ("icse", "fse", "ase", "issta"):
            assert [name for name, _ in SOURCES_BY_PREFIX[prefix]][:3] == ["manual", "researchr", "sigsoft"]

    def test_a_manual_entry_wins_a_duplicate_and_corrects_its_label(self, monkeypatch, tmp_path):
        _write_papers(tmp_path, "demo_2025", json.dumps({"title": "Won"}) + "\n")
        _manual_file(monkeypatch, tmp_path, 'source: https://m.test/\nretrieved: 2026-10-17\nawards:\n'
                                            '  - {label: "Best Student Paper Honorable Mention", title: "Won"}\n')
        monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [
            ("manual", manual_module.manual), ("b", _src([_a("Best Paper Honorable Mention", "honorable", "Won", "b")]))])
        collect_conference("demo_2025", tmp_path)
        assert [(a.label, a.via) for a in read_awards(tmp_path, "demo_2025")] == [
            ("Best Student Paper Honorable Mention", "manual")]

    def test_replaces_drops_another_sources_spelling_of_the_same_kind(self, monkeypatch, tmp_path):
        _write_papers(tmp_path, "demo_2025", json.dumps({"title": "Pose-NDF: Modeling Poses"}) + "\n")
        _manual_file(monkeypatch, tmp_path, 'source: https://m.test/\nretrieved: 2026-10-17\nawards:\n'
                                            '  - {label: "Honorable Mention", title: "Pose-NDF: Modeling Poses",'
                                            ' replaces: "Pose-NDF: Modelling Poses"}\n')
        monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [
            ("manual", manual_module.manual),
            ("b", _src([_a("Honorable Mention", "honorable", "Pose-NDF: Modelling Poses", "b"),
                        _a("Best Paper", "award", "Pose-NDF: Modelling Poses", "b")]))])
        out = collect_conference("demo_2025", tmp_path)
        assert [(a.kind, a.title, a.via) for a in read_awards(tmp_path, "demo_2025")] == [
            ("award", "Pose-NDF: Modelling Poses", "b"),
            ("honorable", "Pose-NDF: Modeling Poses", "manual"),
        ]
        assert (out.matched, out.unmatched) == (1, ["Pose-NDF: Modelling Poses"])

    def test_a_replaces_that_drops_nothing_is_logged(self, monkeypatch, tmp_path, caplog):
        _write_papers(tmp_path, "demo_2025", json.dumps({"title": "Won"}) + "\n")
        _manual_file(monkeypatch, tmp_path, 'source: https://m.test/\nretrieved: 2026-10-17\nawards:\n'
                                            '  - {label: "Honorable Mention", title: "Won", replaces: "Typo Title"}\n')
        monkeypatch.setitem(SOURCES_BY_PREFIX, "demo", [
            ("manual", manual_module.manual), ("b", _src([_a("Best Paper", "award", "Other", "b")]))])
        with caplog.at_level("WARNING", logger="ppr.awards.collect"):
            out = collect_conference("demo_2025", tmp_path)
        assert out.status == "collected"
        assert any("demo_2025" in r.message and "typotitle" in r.message for r in caplog.records)
