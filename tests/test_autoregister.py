import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ppr.autoregister import Outcome, Workspace, autoregister, git_commit, outcomes_to_json
from ppr.venues import Venue

README = """### NLP

| Conference | 2026 | 2025 |
|---|---|---|
| COLM | | main |

### SE

| Conference | 2026 | 2025 |
|---|---|---|
| ICSE | | main |
"""

DBLP_SRC = 'DBLP_CONFERENCES = {\n    "icse_2025": {"key": "db/conf/icse/icse2025.bht"},\n}\n'
CVF_SRC = 'CVF_CONFERENCES = {\n}\n'
USENIX_SRC = 'USENIX_CONFERENCES = {\n}\n'


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "data").mkdir()
    scrapers = tmp_path / "ppr" / "scrapers"
    scrapers.mkdir(parents=True)
    (scrapers / "dblp.py").write_text(DBLP_SRC)
    (scrapers / "cvf.py").write_text(CVF_SRC)
    (scrapers / "usenix.py").write_text(USENIX_SRC)
    (tmp_path / "README.md").write_text(README)
    return Workspace(tmp_path)


def _venue(prefix, source, name, **kw):
    return Venue(prefix=prefix, name=name, source=source, cadence="annual",
                 probe={}, announce_month=1, **kw)


REGISTRY = {
    "icse": _venue("icse", "dblp", "ICSE"),
    "colm": _venue("colm", "openreview", "COLM"),
    "neurips": _venue("neurips", "openreview", "NeurIPS", extra_tracks=(
        {"venue_id": "NeurIPS.cc/{year}/Datasets_and_Benchmarks_Track", "prefix": "datasets"},
    )),
    "acl": _venue("acl", "acl", "ACL"),
}


def _row(conf_id, count, registration, status="live"):
    prefix, _, year = conf_id.rpartition("_")
    return {"conf_id": conf_id, "prefix": prefix, "year": int(year), "status": status,
            "count": count, "url": f"https://x.test/{conf_id}", "note": "",
            "registration": registration}


def _crawler(counts):
    """Fake crawl: writes `counts[conf_id]` papers with selection `main`."""
    def crawl(conf_id, venue, ws):
        n = counts[conf_id]
        if isinstance(n, Exception):
            raise n
        out = ws.data_dir / conf_id / "papers.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(
            json.dumps({"title": f"P{i}", "link": "L", "authors": ["A"], "selection": "main"}) + "\n"
            for i in range(n)
        ))
        return n
    return crawl


def _notes(*venues):
    notes = []
    for v in venues:
        n = MagicMock()
        n.content = {"venue": {"value": v}}
        notes.append(n)
    return notes


def _openreview(by_venue_id):
    client = MagicMock()
    client.get_all_notes.side_effect = lambda content: by_venue_id.get(content["venueid"], [])
    return lambda: client


def _run(rows, ws, *, counts, validate=lambda c: "NO_DATA", openreview=None):
    commits = []
    outcomes = autoregister(
        rows, REGISTRY, ws, crawl=_crawler(counts), validate=validate,
        commit=lambda files, msg: commits.append((sorted(str(f) for f in files), msg)),
        openreview=openreview or _openreview({}),
    )
    return outcomes, commits


# 250, not an arbitrary count: 10% of it is a whole number, so the boundary
# tests below can tell `>` from `>=`.
ICSE = _row("icse_2026", 250, {"key": "db/conf/icse/icse2026.bht"})


class TestCandidates:
    def test_only_live_mechanical_rows_are_considered(self, ws):
        rows = [_row("acl_2027", 0, {}, status="needs-manual"),
                _row("icse_2027", 0, {}, status="not-yet"),
                _row("icse_2028", 0, {}, status="unreachable")]
        outcomes, commits = _run(rows, ws, counts={})
        assert outcomes == []
        assert commits == []

    def test_live_non_mechanical_and_unknown_prefix_rows_are_skipped(self, ws):
        rows = [_row("acl_2027", 10, {"url": "https://x.test"}),
                _row("siggraph_2026", 10, {"key": "k"})]
        outcomes, commits = _run(rows, ws, counts={"acl_2027": 10, "siggraph_2026": 10})
        assert outcomes == []
        assert commits == []

    def test_live_row_without_a_registration_payload_holds(self, ws):
        outcomes, _ = _run([_row("icse_2026", 250, {})], ws, counts={"icse_2026": 250})
        assert outcomes[0].status == "held"
        assert "registration" in outcomes[0].reason


class TestDblpVenue:
    def test_registers_crawls_fills_readme_and_commits(self, ws):
        outcomes, commits = _run([ICSE], ws, counts={"icse_2026": 250})
        o = outcomes[0]
        assert (o.status, o.count, o.expected) == ("registered", 250, 250)
        assert '"icse_2026": {"key": "db/conf/icse/icse2026.bht"}' in ws.dblp_module.read_text()
        assert "| ICSE | main | main |" in ws.readme.read_text()
        assert commits == [(
            sorted([str(ws.dblp_module), str(ws.readme)]),
            "feat(registry): register icse_2026 (250 papers)",
        )]

    def test_dblp_sources_skip_dblp_validation(self, ws):
        calls = []
        outcomes, _ = _run([ICSE], ws, counts={"icse_2026": 250},
                           validate=lambda c: calls.append(c) or "FAIL")
        assert outcomes[0].status == "registered"
        assert calls == []


class TestCountCheck:
    @pytest.mark.parametrize("crawled", [225, 275])  # exactly 10% either side: inclusive
    def test_within_ten_percent_registers(self, ws, crawled):
        outcomes, _ = _run([ICSE], ws, counts={"icse_2026": crawled})
        assert outcomes[0].status == "registered"

    @pytest.mark.parametrize("crawled", [224, 276, 0])
    def test_outside_ten_percent_holds_and_reverts(self, ws, crawled):
        outcomes, commits = _run([ICSE], ws, counts={"icse_2026": crawled})
        assert outcomes[0].status == "held"
        assert "250" in outcomes[0].reason
        assert ws.dblp_module.read_text() == DBLP_SRC
        assert ws.readme.read_text() == README
        assert not (ws.data_dir / "icse_2026").exists()
        assert commits == []


class TestRevert:
    def test_crawl_crash_is_a_hold_not_a_crash(self, ws):
        outcomes, _ = _run([ICSE], ws, counts={"icse_2026": RuntimeError("site down")})
        assert outcomes[0].status == "held"
        assert "site down" in outcomes[0].reason
        assert ws.dblp_module.read_text() == DBLP_SRC

    def test_one_hold_does_not_stop_the_next_venue(self, ws):
        rows = [_row("icse_2026", 250, {"key": "db/conf/icse/icse2026.bht"}),
                _row("icse_2027", 100, {"key": "db/conf/icse/icse2027.bht"})]
        outcomes, commits = _run(rows, ws, counts={"icse_2026": 10, "icse_2027": 100})
        assert [o.status for o in outcomes] == ["held", "registered"]
        text = ws.dblp_module.read_text()
        assert "icse_2026" not in text and "icse_2027" in text
        assert len(commits) == 1

    def test_preexisting_data_dir_is_restored_on_hold(self, ws):
        # A venue whose push failed last month: its data shipped in the release,
        # but its registration never reached main. A hold must not delete it.
        old = ws.data_dir / "icse_2026"
        old.mkdir()
        (old / "papers.jsonl").write_text("old\n")
        (old / "papers_enriched.jsonl").write_text("old-enriched\n")
        _run([ICSE], ws, counts={"icse_2026": 10})
        assert (old / "papers.jsonl").read_text() == "old\n"
        assert (old / "papers_enriched.jsonl").read_text() == "old-enriched\n"

    def test_already_registered_is_a_hold(self, ws):
        row = _row("icse_2025", 250, {"key": "db/conf/icse/icse2025.bht"})
        outcomes, _ = _run([row], ws, counts={"icse_2025": 250})
        assert outcomes[0].status == "held"
        assert "already registered" in outcomes[0].reason


class TestValidate:
    COLM = _row("colm_2026", 856, {"venue_id": "colmweb.org/COLM/2026/Conference"})
    OR = {"colmweb.org/COLM/2026/Conference": _notes(*["COLM 2026"] * 856)}

    def test_fail_holds(self, ws):
        outcomes, _ = _run([self.COLM], ws, counts={"colm_2026": 856},
                           validate=lambda c: "FAIL", openreview=_openreview(self.OR))
        assert outcomes[0].status == "held"
        assert not (ws.configs_dir / "colm_2026.yaml").exists()

    @pytest.mark.parametrize("status", ["PASS", "ERROR", "NO_DATA", "SKIP"])
    def test_anything_but_fail_passes(self, ws, status):
        outcomes, _ = _run([self.COLM], ws, counts={"colm_2026": 856},
                           validate=lambda c: status, openreview=_openreview(self.OR))
        assert outcomes[0].status == "registered"


class TestOpenReview:
    def test_writes_config_with_derived_selections(self, ws):
        row = _row("colm_2026", 856, {"venue_id": "colmweb.org/COLM/2026/Conference"})
        _run([row], ws, counts={"colm_2026": 856},
             openreview=_openreview({"colmweb.org/COLM/2026/Conference": _notes(*["COLM 2026"] * 856)}))
        text = (ws.configs_dir / "colm_2026.yaml").read_text()
        assert 'main: "COLM 2026"' in text
        assert "| COLM | main | main |" in ws.readme.read_text()

    def test_unknown_track_name_holds(self, ws):
        row = _row("colm_2026", 4, {"venue_id": "v"})
        outcomes, _ = _run([row], ws, counts={"colm_2026": 4},
                           openreview=_openreview({"v": _notes("COLM 2026 Long", "COLM 2026 Poster")}))
        assert outcomes[0].status == "held"
        assert 'unknown track name "COLM 2026 Long"' in outcomes[0].reason
        assert not (ws.configs_dir / "colm_2026.yaml").exists()

    def test_extra_track_included_only_when_it_has_papers(self, ws):
        main_id = "NeurIPS.cc/2026/Conference"
        dnb_id = "NeurIPS.cc/2026/Datasets_and_Benchmarks_Track"
        row = _row("neurips_2026", 5, {"venue_id": main_id})
        notes = {
            main_id: _notes("NeurIPS 2026 oral", *["NeurIPS 2026 poster"] * 4),
            dnb_id: _notes("NeurIPS 2026 Datasets and Benchmarks Track oral",
                           *["NeurIPS 2026 Datasets and Benchmarks Track poster"] * 2),
        }
        outcomes, _ = _run([row], ws, counts={"neurips_2026": 8}, openreview=_openreview(notes))
        assert (outcomes[0].status, outcomes[0].expected) == ("registered", 8)
        text = (ws.configs_dir / "neurips_2026.yaml").read_text()
        assert dnb_id in text
        assert 'datasets_poster: "NeurIPS 2026 Datasets and Benchmarks Track poster"' in text

    def test_empty_extra_track_is_left_out(self, ws):
        main_id = "NeurIPS.cc/2026/Conference"
        row = _row("neurips_2026", 5, {"venue_id": main_id})
        notes = {main_id: _notes("NeurIPS 2026 oral", *["NeurIPS 2026 poster"] * 4)}
        _run([row], ws, counts={"neurips_2026": 5}, openreview=_openreview(notes))
        assert "extra_venue_ids" not in (ws.configs_dir / "neurips_2026.yaml").read_text()


class TestReadmeRowMissing:
    def test_is_a_note_not_a_hold(self, ws):
        ws.readme.write_text("# no tables\n")
        outcomes, _ = _run([ICSE], ws, counts={"icse_2026": 250})
        assert outcomes[0].status == "registered"
        assert any("README" in n for n in outcomes[0].notes)


class TestJson:
    def test_round_trip(self):
        payload = json.loads(outcomes_to_json([Outcome("icse_2026", "held", reason="r")]))
        assert payload["outcomes"][0]["conf_id"] == "icse_2026"
        assert payload["outcomes"][0]["status"] == "held"


class TestCommitFailure:
    def test_failing_commit_is_a_hold_and_restores_files(self, ws):
        def boom(files, msg):
            raise subprocess.CalledProcessError(1, "git")
        outcomes = autoregister([ICSE], REGISTRY, ws, crawl=_crawler({"icse_2026": 250}),
                                validate=lambda c: "NO_DATA", commit=boom,
                                openreview=_openreview({}))
        assert outcomes[0].status == "held"
        assert ws.dblp_module.read_text() == DBLP_SRC
        assert ws.readme.read_text() == README


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "seed").write_text("s")
    _git(tmp_path, "add", "seed")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


class TestGitCommit:
    def test_failed_commit_leaves_nothing_staged(self, repo):
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        f = repo / "a.txt"
        f.write_text("a")
        with pytest.raises(subprocess.CalledProcessError):
            git_commit(repo)([f], "msg")
        assert _git(repo, "diff", "--cached", "--name-only") == ""

    def test_commit_carries_no_claude_trailer(self, repo):
        f = repo / "a.txt"
        f.write_text("a")
        git_commit(repo)([f], "msg")
        assert "Co-Authored-By" not in _git(repo, "log", "-1", "--format=%B")

    def test_unrelated_staged_file_is_not_swept_in(self, repo):
        other = repo / "other.txt"
        other.write_text("o")
        _git(repo, "add", "other.txt")
        f = repo / "a.txt"
        f.write_text("a")
        git_commit(repo)([f], "msg")
        assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["a.txt"]
        assert _git(repo, "diff", "--cached", "--name-only").split() == ["other.txt"]


class TestCli:
    def _run(self, tmp_path, monkeypatch, fake, extra=()):
        from ppr import cli

        discover = tmp_path / "discover.json"
        discover.write_text(json.dumps({"results": [ICSE], "live_count": 1, "stale_empty": []}))
        report = tmp_path / "register.json"
        monkeypatch.setattr("ppr.autoregister.autoregister", fake)
        args = cli.build_parser().parse_args(
            ["autoregister", str(discover), "--report", str(report), *extra]
        )
        cli.cmd_autoregister(args)
        return report

    def test_reads_discover_json_and_writes_the_report(self, tmp_path, monkeypatch):
        seen = {}

        def fake_autoregister(rows, registry, ws, **kw):
            seen["rows"] = rows
            seen["commit"] = kw["commit"]
            return [Outcome("icse_2026", "registered", count=245)]

        report = self._run(tmp_path, monkeypatch, fake_autoregister)
        assert seen["rows"] == [ICSE]
        assert json.loads(report.read_text())["outcomes"][0]["status"] == "registered"
        from ppr.autoregister import no_commit
        assert seen["commit"] is no_commit  # --commit not given

    def test_commit_flag_selects_git_commit(self, tmp_path, monkeypatch):
        seen = {}

        def fake(rows, registry, ws, **kw):
            seen["commit"] = kw["commit"]
            return []

        self._run(tmp_path, monkeypatch, fake, extra=["--commit"])
        from ppr.autoregister import no_commit
        assert seen["commit"] is not no_commit

    def test_openreview_logs_in_lazily_and_once(self, tmp_path, monkeypatch):
        logins = []
        monkeypatch.setattr(
            "ppr.cli.create_openreview_client",
            lambda **kw: logins.append(kw) or object(),
        )
        seen = {}

        def fake(rows, registry, ws, **kw):
            seen["logins_before"] = len(logins)
            a, b = kw["openreview"](), kw["openreview"]()
            assert a is b
            return []

        self._run(tmp_path, monkeypatch, fake)
        assert seen["logins_before"] == 0
        assert len(logins) == 1

    def test_validate_returns_the_status_string(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ppr.validate.validate_conference", lambda cid: MagicMock(status="PASS")
        )
        got = {}

        def fake(rows, registry, ws, **kw):
            got["v"] = kw["validate"]("icse_2026")
            return []

        self._run(tmp_path, monkeypatch, fake)
        assert got["v"] == "PASS"
