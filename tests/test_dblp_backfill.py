import re
from pathlib import Path

import pytest

from ppr import dblp_client
from ppr.layout import crawl_config_ids
from ppr.scrapers.dblp import load_backfill

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = load_backfill()
TOCS = [(conf_id, t) for conf_id, e in REGISTRY.items() for t in e["tocs"]]


def test_registry_is_loaded():
    # Changes only with a reviewed edit of configs/<venue>/dblp.yaml. A missing or
    # moved file makes load_backfill() return {}, and every other test would pass on nothing.
    assert len(REGISTRY) == 190


def test_every_entry_has_tocs():
    assert all(e["tocs"] for e in REGISTRY.values())


def test_keys_are_well_formed_and_unique():
    keys = [t["key"] for _, t in TOCS]
    assert all(dblp_client._KEY.fullmatch(k) and k.endswith(".bht") for k in keys)
    assert len(keys) == len(set(keys))


def test_years_are_the_backfill_range_and_match_the_key():
    for conf_id, t in TOCS:
        year = conf_id.rsplit("_", 1)[1]
        assert 2013 <= int(year) <= 2022, conf_id
        assert year in t["key"].rsplit("/", 1)[1], (conf_id, t["key"])


def test_selections_are_the_dblp_vocabulary():
    assert {t["selection"] for _, t in TOCS} <= {"main", "findings", "industry"}


def test_only_main_volume_suffixes():
    """Allowed after <stem><year>: nothing, -N (volume), f (findings), i (industry).
    Workshops (w, -wN), demos (d), student (s), tutorials (t), companions (c),
    NIER and SEIS volumes never belong here."""
    for conf_id, t in TOCS:
        name = t["key"].rsplit("/", 1)[1].removesuffix(".bht")
        suffix = re.fullmatch(r"[a-z]+\d{4}(.*)", name).group(1)
        assert re.fullmatch(r"(?:-\d+|f|i)?", suffix), (conf_id, name)


def test_ids_do_not_collide_with_other_sources():
    import importlib

    configs = set(crawl_config_ids(ROOT / "configs"))
    others = set(configs)
    for name in ("acl", "aaai", "usenix", "researchr", "crossref", "cvf",
                 "roboticsproceedings", "ijcai"):
        others |= set(importlib.import_module(f"ppr.scrapers.{name}").SCRAPERS)
    assert not (set(REGISTRY) & others)


def test_load_backfill_reads_each_venue_file_keyed_by_year(tmp_path):
    (tmp_path / "aaai").mkdir()
    (tmp_path / "aaai" / "dblp.yaml").write_text(
        "2013:  # 251 papers\n  tocs:\n    - {key: db/conf/aaai/aaai2013.bht, selection: main}\n")
    assert load_backfill(tmp_path) == {
        "aaai_2013": {"tocs": [{"key": "db/conf/aaai/aaai2013.bht", "selection": "main"}]}}


def test_load_backfill_rejects_an_entry_without_tocs(tmp_path):
    (tmp_path / "aaai").mkdir()
    (tmp_path / "aaai" / "dblp.yaml").write_text("2013: {}\n")
    with pytest.raises(ValueError, match="2013"):
        load_backfill(tmp_path)
