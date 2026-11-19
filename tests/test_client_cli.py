import json
import sys

import pytest

import ppr
from ppr import client_cli, data_home, data_sync, entry, layout
from ppr.data_sync import sync
from tests.release_helpers import FakeGitHub
from tests.search_helpers import make_dataset

TAG = "data-2026-11-03"


def boom(*args, **kwargs):
    raise AssertionError("the network was touched")


def dataset_files(tmp_path):
    data = make_dataset(tmp_path / "src")
    return {f"data/{p.relative_to(data).as_posix()}": p.read_text() for p in data.rglob("*") if p.is_file()}


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """An installed-mode home in tmp_path/h, with the update check on and no real network."""
    home = layout.Home(tmp_path / "h", True)
    monkeypatch.setattr(client_cli, "_home", lambda: home)
    monkeypatch.delenv(layout.HOME_ENV, raising=False)
    monkeypatch.delenv(layout.AUTO_UPDATE_ENV, raising=False)
    for module in (data_home, data_sync):
        monkeypatch.setattr(module, "fetch_zip", boom)
    monkeypatch.setattr(data_home, "fetch_latest_tag_short", boom)
    monkeypatch.setattr(data_sync, "fetch_latest_tag", boom)
    return home


def test_installed_find_json_stdout_is_pure_json(managed, tmp_path, monkeypatch, capsys):
    gh = FakeGitHub(tmp_path, TAG, dataset_files(tmp_path))
    monkeypatch.setattr(data_home, "fetch_latest_tag_short", gh.latest_tag)
    monkeypatch.setattr(data_home, "fetch_zip", gh.download)
    client_cli.main(["search", "find", "unlearning", "--json"])
    out, err = capsys.readouterr()
    assert out and all(json.loads(line) for line in out.splitlines())
    assert f"downloading data release {TAG}" in err and gh.downloads == 1


def test_data_status_json_makes_no_network_call(managed, tmp_path, capsys):
    gh = FakeGitHub(tmp_path, TAG, dataset_files(tmp_path))
    managed.root.mkdir(parents=True)
    sync(managed.root, gh.latest_tag, gh.download)
    client_cli.main(["data", "status", "--json"])
    st = json.loads(capsys.readouterr().out)
    assert st["mode"] == "installed" and st["tag"] == TAG and st["venues"]["iclr"] == "2024"


def test_data_status_names_ppr_home(managed, monkeypatch, capsys):
    monkeypatch.setenv(layout.HOME_ENV, str(managed.root))
    client_cli.main(["data", "status"])
    assert "PPR_HOME" in capsys.readouterr().out


def test_data_update_reports_like_sync_data(managed, tmp_path, monkeypatch, capsys):
    gh = FakeGitHub(tmp_path, TAG, dataset_files(tmp_path))
    monkeypatch.setattr(data_sync, "fetch_latest_tag", gh.latest_tag)
    monkeypatch.setattr(data_sync, "fetch_zip", gh.download)
    client_cli.main(["data", "update"])
    assert f"updated: none -> {TAG}" in capsys.readouterr().out
    assert not data_home.check_due(managed.root, __import__("time").time())
    client_cli.main(["data", "update"])
    assert f"already at {TAG}" in capsys.readouterr().out


def test_auto_update_off_with_no_data_says_data_update(managed, monkeypatch):
    monkeypatch.setenv(layout.AUTO_UPDATE_ENV, "0")
    with pytest.raises(SystemExit) as exc:
        client_cli.main(["search", "find", "x"])
    assert "ppr data update" in str(exc.value.code)


def test_lean_help_lists_only_client_commands(capsys):
    with pytest.raises(SystemExit):
        client_cli.main(["--help"])
    out = capsys.readouterr().out
    assert "search" in out and "data" in out and "crawl" not in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        client_cli.main(["--version"])
    assert exc.value.code == 0 and capsys.readouterr().out.startswith("ppr ")


def test_entry_routes_installed_mode_to_the_client(monkeypatch):
    monkeypatch.setattr(layout, "is_checkout", lambda root=layout.ROOT: False)
    seen = []
    monkeypatch.setattr(client_cli, "main", lambda argv=None: seen.append(argv))
    entry.main(["crawl", "iclr_2025"])
    assert seen == [["crawl", "iclr_2025"]]


def test_entry_checkout_without_pipeline_deps_explains(monkeypatch):
    monkeypatch.setattr(layout, "is_checkout", lambda root=layout.ROOT: True)
    monkeypatch.setattr(entry, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delattr(ppr, "cli", raising=False)
    monkeypatch.setitem(sys.modules, "ppr.cli", None)
    seen = []
    monkeypatch.setattr(client_cli, "main", lambda argv=None: seen.append(argv))
    with pytest.raises(SystemExit) as exc:
        entry.main(["crawl", "x"])
    assert "needs the repository environment" in str(exc.value.code)
    assert "uv run ppr crawl" in str(exc.value.code)
    entry.main(["search", "find", "x"])
    entry.main(["--help"])
    assert seen == [["search", "find", "x"], ["--help"]]


def test_dotenv_is_read_only_in_a_checkout(monkeypatch):
    calls = []
    monkeypatch.setattr(entry, "load_dotenv", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(client_cli, "main", lambda argv=None: None)
    monkeypatch.setattr(layout, "is_checkout", lambda root=layout.ROOT: False)
    entry.main(["data", "status"])
    assert calls == []
    monkeypatch.setattr(layout, "is_checkout", lambda root=layout.ROOT: True)
    monkeypatch.setattr("ppr.cli.main", lambda argv=None: None)
    entry.main(["data", "status"])
    assert calls == [(layout.ROOT / ".env",)]
