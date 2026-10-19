"""Tests for the CLI's own file handling.

Subcommand argument wiring is tested next to the module each subcommand drives
(`tests/test_discover.py` for `discover`, and so on); what lives here is the
behaviour `ppr/cli.py` itself owns.
"""

import json

import pytest

from ppr import cli
from ppr.layout import papers_path
from ppr.models import Paper
from ppr.store import ShrinkError, read_papers, save_enriched


def _paper(title: str) -> Paper:
    return Paper(title=title, link=f"https://x.test/{title}", authors=["A"], selection="main")


class TestSavePapers:
    def test_writes_under_the_conference_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        path = cli._save_papers([_paper("P1")], "ijcai_2026")
        assert path == papers_path(tmp_path, "ijcai_2026")
        assert path.read_text(encoding="utf-8").strip() == _paper("P1").to_json()

    def test_refuses_to_erase_an_existing_crawl(self, tmp_path, monkeypatch):
        """A scraper that returns `[]` after a site redesign is the same failure
        as a swallowed API error, and must not truncate the last good crawl
        either -- the two save paths have to agree on that rule."""
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        saved = cli._save_papers([_paper("P1"), _paper("P2")], "ijcai_2026")
        before = saved.read_bytes()

        with pytest.raises(ShrinkError):
            cli._save_papers([], "ijcai_2026")

        assert saved.read_bytes() == before

    def test_save_keeps_enrichment_across_a_recrawl(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        path = papers_path(tmp_path, "ijcai_2026")
        save_enriched([Paper(title="P", link="L", authors=["A"], citation_count=3)], path)
        cli._save_papers([Paper(title="P", link="L", authors=["A"])], "ijcai_2026")
        assert read_papers(path)[0].citation_count == 3

    def test_first_crawl_of_a_venue_with_no_papers_still_writes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        path = cli._save_papers([], "ijcai_2027")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""


class TestAwardsCommand:
    def test_all_collects_every_venue_with_a_rule_and_writes_the_report(self, tmp_path, monkeypatch):
        from datetime import date

        from ppr.awards import collect, manual

        this_year = f"icml_{date.today().year}"
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        # configs/ has an icml_2013 manual file, which would make that old year pending.
        monkeypatch.setattr(manual, "CONFIGS_DIR", tmp_path / "no-manual-files")
        for name in (this_year, "acl_2025", "icml_2013"):
            (tmp_path / name).mkdir()
        seen = []
        monkeypatch.setattr(collect, "collect_conference",
                            lambda conf_id, data_dir: seen.append(conf_id) or collect.Outcome(conf_id, "not-yet"))
        report = tmp_path / "awards.json"

        cli.cmd_awards(cli.build_parser().parse_args(["awards", "--all", "--report", str(report)]))

        assert seen == [this_year]
        assert json.loads(report.read_text(encoding="utf-8"))["results"][0]["status"] == "not-yet"

    def test_all_years_adds_the_final_years(self, tmp_path, monkeypatch):
        from datetime import date

        from ppr.awards import collect

        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        for name in (f"icml_{date.today().year}", "icml_2013"):
            (tmp_path / name).mkdir()
        seen = []
        monkeypatch.setattr(collect, "collect_conference",
                            lambda conf_id, data_dir: seen.append(conf_id) or collect.Outcome(conf_id, "not-yet"))
        cli.cmd_awards(cli.build_parser().parse_args(["awards", "--all", "--all-years"]))
        assert seen == sorted(["icml_2013", f"icml_{date.today().year}"])

    def test_all_years_without_all_is_a_usage_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit):
            cli.cmd_awards(cli.build_parser().parse_args(["awards", "--all-years", "icml_2013"]))

    def test_held_and_failed_conferences_do_not_fail_the_command(self, tmp_path, monkeypatch):
        from ppr.awards import collect

        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        monkeypatch.setattr(collect, "collect_conference",
                            lambda conf_id, data_dir: collect.Outcome(conf_id, "failed", reason="HTTPError: 503"))
        cli.cmd_awards(cli.build_parser().parse_args(["awards", "cvpr_2026"]))  # no SystemExit

    def test_no_conferences_is_a_usage_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit):
            cli.cmd_awards(cli.build_parser().parse_args(["awards"]))


def test_rolling_parses():
    args = cli.build_parser().parse_args(["rolling", "--report", "r.json"])
    assert args.command == "rolling" and str(args.report) == "r.json"


def test_rolling_with_nothing_due_never_logs_in(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "CONFIGS_DIR", tmp_path)

    def no_login(**kwargs):
        raise AssertionError("logged in")

    monkeypatch.setattr(cli, "create_openreview_client", no_login)
    report = tmp_path / "r.json"
    cli.cmd_rolling(cli.build_parser().parse_args(["rolling", "--report", str(report)]))
    assert json.loads(report.read_text(encoding="utf-8")) == {"results": []}
