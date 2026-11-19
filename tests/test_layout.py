# tests/test_layout.py
import re
from pathlib import Path

import pytest

from ppr import layout
from ppr.release import CHECKPOINT_SUFFIX
from ppr.venues import load_registry


def _touch(root: Path, *rels: str) -> None:
    for rel in rels:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")


class TestSplitId:
    def test_plain(self):
        assert layout.split_id("iclr_2025") == ("iclr", 2025)

    def test_venue_with_an_underscore_splits_on_the_last_one(self):
        assert layout.split_id("usenix_security_2025") == ("usenix_security", 2025)

    @pytest.mark.parametrize("bad", ["venues", "iclr", "iclr_25", "_2025", "iclr_2025x", "iclr_"])
    def test_rejects_what_is_not_a_conference_id(self, bad):
        with pytest.raises(ValueError, match=bad):
            layout.split_id(bad)


class TestDataPaths:
    def test_papers_path(self, tmp_path):
        assert layout.papers_path(tmp_path, "usenix_security_2025") == tmp_path / "usenix_security" / "2025.jsonl"

    def test_checkpoint_is_hidden_and_left_out_of_releases(self, tmp_path):
        path = layout.checkpoint_path(tmp_path, "iclr_2025")
        assert path == tmp_path / "iclr" / ".2025.tmp.jsonl"
        assert path.name.endswith(CHECKPOINT_SUFFIX)

    def test_one_awards_file_per_venue(self, tmp_path):
        assert layout.awards_path(tmp_path, "iclr_2016") == tmp_path / "iclr" / "awards.json"
        assert layout.awards_path(tmp_path, "iclr_2025") == layout.awards_path(tmp_path, "iclr_2016")


class TestConferenceIds:
    def test_lists_year_files_only(self, tmp_path):
        _touch(tmp_path, "iclr/2025.jsonl", "iclr/2016.jsonl", "usenix_security/2024.jsonl",
               "iclr/.2026.tmp.jsonl", "iclr/2026.jsonl.tmp", "iclr/awards.json",
               "iclr/notes.jsonl", "pipeline_state.json", "citation_updated.txt")
        assert layout.conference_ids(tmp_path) == ["iclr_2016", "iclr_2025", "usenix_security_2024"]

    def test_round_trips_through_papers_path(self, tmp_path):
        _touch(tmp_path, "usenix_security/2024.jsonl")
        [conf_id] = layout.conference_ids(tmp_path)
        assert layout.papers_path(tmp_path, conf_id).exists()

    def test_a_missing_directory_has_none(self, tmp_path):
        assert layout.conference_ids(tmp_path / "absent") == []


class TestConfigPaths:
    def test_crawl_config_path(self, tmp_path):
        assert layout.crawl_config_path(tmp_path, "iclr_2025") == tmp_path / "iclr" / "2025.yaml"

    def test_manual_awards_path(self, tmp_path):
        assert layout.manual_awards_path(tmp_path, "cvpr_2019") == tmp_path / "cvpr" / "awards" / "2019.yaml"

    def test_crawl_config_ids_skip_the_registry_awards_and_dblp(self, tmp_path):
        _touch(tmp_path, "venues.yaml", "iclr/2025.yaml", "tmlr/2026.yaml", "iclr/awards/2016.yaml",
               "aaai/dblp.yaml")
        assert layout.crawl_config_ids(tmp_path) == ["iclr_2025", "tmlr_2026"]

    def test_config_conference_id(self):
        assert layout.config_conference_id(Path("configs/usenix_security/2025.yaml")) == "usenix_security_2025"

    def test_a_flat_config_is_rejected(self):
        with pytest.raises(ValueError, match="configs/<venue>/<year>.yaml"):
            layout.config_conference_id(Path("configs/iclr_2025.yaml"))

    def test_dblp_config_paths(self, tmp_path):
        _touch(tmp_path, "aaai/dblp.yaml", "acl/dblp.yaml", "iclr/2025.yaml")
        assert layout.dblp_config_paths(tmp_path) == [tmp_path / "aaai" / "dblp.yaml", tmp_path / "acl" / "dblp.yaml"]


def test_every_config_file_follows_the_layout():
    configs = layout.CONFIGS_DIR
    for path in configs.rglob("*.yaml"):
        rel = path.relative_to(configs).parts
        ok = (rel == ("venues.yaml",)
              or (len(rel) == 2 and (re.fullmatch(r"\d{4}\.yaml", rel[1]) or rel[1] == "dblp.yaml"))
              or (len(rel) == 3 and rel[1] == "awards" and re.fullmatch(r"\d{4}\.yaml", rel[2])))
        assert ok, path
    assert {p.name for p in configs.iterdir() if p.is_dir()} <= set(load_registry())


def test_the_move_kept_every_config():
    configs = layout.CONFIGS_DIR
    assert len(layout.crawl_config_ids(configs)) == 33
    assert len(list(configs.glob("*/awards/*.yaml"))) == 40


def test_search_index_path_is_outside_data(tmp_path):
    from ppr.layout import DATA_DIR, ROOT, search_index_path

    assert search_index_path(tmp_path) == tmp_path / ".cache" / "search.sqlite"
    assert search_index_path() == ROOT / ".cache" / "search.sqlite"
    assert DATA_DIR not in search_index_path().parents


class TestDataHome:
    def test_ppr_home_wins_and_is_managed(self, tmp_path):
        (tmp_path / "repo").mkdir()
        (tmp_path / "repo" / "pyproject.toml").write_text("")
        home = layout.data_home({"PPR_HOME": str(tmp_path / "h")}, root=tmp_path / "repo")
        assert home == layout.Home(tmp_path / "h", True)

    def test_checkout_is_root_and_unmanaged(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        home = layout.data_home({}, root=tmp_path)
        assert home == layout.Home(tmp_path, False)
        assert home.data_dir == tmp_path / "data"
        assert home.index_path == tmp_path / ".cache" / "search.sqlite"

    def test_installed_uses_xdg_cache_home(self, tmp_path):
        home = layout.data_home({"XDG_CACHE_HOME": str(tmp_path / "xdg")}, root=tmp_path / "site-packages")
        assert home == layout.Home(tmp_path / "xdg" / "paper-explorer", True)

    def test_installed_default_is_dot_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        home = layout.data_home({}, root=tmp_path / "site-packages")
        assert home == layout.Home(tmp_path / ".cache" / "paper-explorer", True)

    def test_empty_variables_count_as_unset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        home = layout.data_home({"PPR_HOME": "", "XDG_CACHE_HOME": ""}, root=tmp_path / "site-packages")
        assert home == layout.Home(tmp_path / ".cache" / "paper-explorer", True)

    def test_cwd_pyproject_does_not_make_a_checkout(self, tmp_path, monkeypatch):
        project = tmp_path / "my-research"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname = 'mine'\n")
        monkeypatch.chdir(project)
        home = layout.data_home({"XDG_CACHE_HOME": str(tmp_path / "xdg")}, root=tmp_path / "site-packages")
        assert home.managed

    def test_this_repository_is_a_checkout(self):
        assert layout.is_checkout()


@pytest.mark.parametrize("module", ["layout", "matching"])
def test_module_stays_stdlib_only(module):
    import ast
    import importlib
    import sys

    tree = ast.parse(Path(importlib.import_module(f"ppr.{module}").__file__).read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods - {"ppr"} <= set(sys.stdlib_module_names)
