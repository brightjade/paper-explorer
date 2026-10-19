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
