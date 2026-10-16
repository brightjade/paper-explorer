"""Tests for the CLI's own file handling.

Subcommand argument wiring is tested next to the module each subcommand drives
(`tests/test_discover.py` for `discover`, and so on); what lives here is the
behaviour `ppr/cli.py` itself owns.
"""

import json

import pytest

from ppr import cli
from ppr.models import EmptyOverwriteError, Paper


def _paper(title: str) -> Paper:
    return Paper(title=title, link=f"https://x.test/{title}", authors=["A"], selection="main")


class TestSavePapers:
    def test_writes_under_the_conference_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        path = cli._save_papers([_paper("P1")], "ijcai_2026")
        assert path == tmp_path / "ijcai_2026" / "papers.jsonl"
        assert path.read_text(encoding="utf-8").strip() == _paper("P1").to_json()

    def test_refuses_to_erase_an_existing_crawl(self, tmp_path, monkeypatch):
        """A scraper that returns `[]` after a site redesign is the same failure
        as a swallowed API error, and must not truncate the last good crawl
        either -- the two save paths have to agree on that rule."""
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        saved = cli._save_papers([_paper("P1"), _paper("P2")], "ijcai_2026")
        before = saved.read_bytes()

        with pytest.raises(EmptyOverwriteError):
            cli._save_papers([], "ijcai_2026")

        assert saved.read_bytes() == before

    def test_first_crawl_of_a_venue_with_no_papers_still_writes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        path = cli._save_papers([], "ijcai_2027")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""


class TestAwardsCommand:
    def test_all_collects_every_venue_with_a_rule_and_writes_the_report(self, tmp_path, monkeypatch):
        from ppr.awards import collect

        monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
        (tmp_path / "icml_2025").mkdir()
        (tmp_path / "acl_2025").mkdir()
        seen = []
        monkeypatch.setattr(collect, "collect_conference",
                            lambda conf_id, data_dir: seen.append(conf_id) or collect.Outcome(conf_id, "not-yet"))
        report = tmp_path / "awards.json"

        cli.cmd_awards(cli.build_parser().parse_args(["awards", "--all", "--report", str(report)]))

        assert seen == ["icml_2025"]
        assert json.loads(report.read_text(encoding="utf-8"))["results"][0]["status"] == "not-yet"

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
