from unittest.mock import MagicMock

import pytest
import yaml

from ppr.cli import _available_conferences, cmd_crawl
from ppr.layout import crawl_config_ids
from ppr.venues import (
    CADENCES,
    MANUAL_SOURCES,
    REGISTRY_PATH,
    SOURCES,
    Venue,
    load_registry,
)


def _write(tmp_path, data):
    p = tmp_path / "venues.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


VALID = {
    "venues": {
        "icse": {
            "name": "ICSE",
            "source": "dblp",
            "cadence": "annual",
            "announce_month": 12,
            "probe": {"toc": "db/conf/icse/icse{year}.bht"},
        }
    }
}


class TestLoadRegistry:
    def test_loads_a_venue(self, tmp_path):
        reg = load_registry(_write(tmp_path, VALID))
        v = reg["icse"]
        assert isinstance(v, Venue)
        assert v.prefix == "icse"
        assert v.name == "ICSE"
        assert v.source == "dblp"
        assert v.cadence == "annual"
        assert v.announce_month == 12
        assert v.probe == {"toc": "db/conf/icse/icse{year}.bht"}

    def test_rejects_unknown_source(self, tmp_path):
        bad = {"venues": {"x": dict(VALID["venues"]["icse"], source="carrier-pigeon")}}
        with pytest.raises(ValueError, match="carrier-pigeon"):
            load_registry(_write(tmp_path, bad))

    def test_rejects_unknown_cadence(self, tmp_path):
        bad = {"venues": {"x": dict(VALID["venues"]["icse"], cadence="fortnightly")}}
        with pytest.raises(ValueError, match="fortnightly"):
            load_registry(_write(tmp_path, bad))

    def test_rejects_out_of_range_announce_month(self, tmp_path):
        bad = {"venues": {"x": dict(VALID["venues"]["icse"], announce_month=13)}}
        with pytest.raises(ValueError, match="announce_month"):
            load_registry(_write(tmp_path, bad))

    def test_rejects_missing_required_field(self, tmp_path):
        incomplete = dict(VALID["venues"]["icse"])
        del incomplete["source"]
        with pytest.raises(ValueError, match="source"):
            load_registry(_write(tmp_path, {"venues": {"x": incomplete}}))


class TestShippedRegistry:
    def test_shipped_registry_parses(self):
        reg = load_registry(REGISTRY_PATH)
        assert len(reg) == 25
        for prefix, v in reg.items():
            assert v.source in SOURCES
            assert v.cadence in CADENCES
            assert 1 <= v.announce_month <= 12

    def test_biennial_venues_declared(self):
        reg = load_registry(REGISTRY_PATH)
        assert reg["iccv"].cadence == "biennial-odd"
        assert reg["eccv"].cadence == "biennial-even"

    def test_manual_sources_marked(self):
        reg = load_registry(REGISTRY_PATH)
        for prefix in ("acl", "emnlp", "naacl", "eacl", "coling", "aaai"):
            assert reg[prefix].source in MANUAL_SOURCES

    def test_every_tracked_prefix_is_registered(self):
        """A venue absent from the registry is never probed -- a silent blind spot."""
        from pathlib import Path

        from ppr.scrapers import SCRAPERS

        configs = Path(__file__).resolve().parent.parent / "configs"
        ids = set(crawl_config_ids(configs))
        ids |= set(SCRAPERS.keys())
        prefixes = {cid.rsplit("_", 1)[0] for cid in ids}
        assert prefixes <= set(load_registry(REGISTRY_PATH)), (
            f"unregistered: {sorted(prefixes - set(load_registry(REGISTRY_PATH)))}"
        )


class TestConfigsDirExcludesRegistry:
    """configs/venues.yaml sits alone at the root; conference configs live in
    configs/<venue>/<year>.yaml. `crawl_config_ids` only reads those, so the
    registry is never treated as a bogus conference."""

    def test_venues_not_in_available_conferences(self):
        assert "venues" not in _available_conferences()

    def test_crawl_venues_reports_unknown_conference(self):
        """Without the exclusion, `ppr crawl venues` takes the OpenReview branch
        (configs/venues.yaml exists, "venues" isn't in SCRAPERS) and dies inside
        CrawlConfig.from_yaml instead of reporting a clean unknown-conference error."""
        args = MagicMock(conferences=["venues"])
        with pytest.raises(FileNotFoundError, match="venues"):
            cmd_crawl(args)

    def test_cli_and_discover_agree_on_conference_ids(self):
        """_available_conferences() delegates to known_conference_ids() -- this
        pins that agreement so the two copies of the derivation rule can't drift
        apart."""
        from ppr.discover import known_conference_ids

        assert set(_available_conferences()) == known_conference_ids()


class TestExtraTracks:
    def _with(self, tmp_path, source, extra):
        data = {"venues": {"neurips": {
            "name": "NeurIPS", "source": source, "cadence": "annual",
            "announce_month": 9, "probe": {"venue_id": "NeurIPS.cc/{year}/Conference"},
            "extra_tracks": extra,
        }}}
        return _write(tmp_path, data)

    def test_parsed_into_a_tuple(self, tmp_path):
        reg = load_registry(self._with(tmp_path, "openreview", [
            {"venue_id": "NeurIPS.cc/{year}/Datasets_and_Benchmarks_Track", "prefix": "datasets"},
        ]))
        assert reg["neurips"].extra_tracks == (
            {"venue_id": "NeurIPS.cc/{year}/Datasets_and_Benchmarks_Track", "prefix": "datasets"},
        )

    def test_defaults_to_empty(self, tmp_path):
        assert load_registry(_write(tmp_path, VALID))["icse"].extra_tracks == ()

    def test_rejected_on_a_non_openreview_source(self, tmp_path):
        with pytest.raises(ValueError, match="extra_tracks"):
            load_registry(self._with(tmp_path, "dblp", [{"venue_id": "x", "prefix": "d"}]))

    def test_prefix_must_be_lowercase_letters(self, tmp_path):
        with pytest.raises(ValueError, match="prefix"):
            load_registry(self._with(tmp_path, "openreview", [{"venue_id": "x", "prefix": "D&B"}]))

    def test_shipped_neurips_declares_datasets_track(self):
        assert load_registry()["neurips"].extra_tracks[0]["prefix"] == "datasets"


class TestRolling:
    def _venue(self, source="openreview", **extra):
        return {"venues": {"j": {
            "name": "J", "source": source, "cadence": "annual", "announce_month": 1,
            "probe": {"venue_id": "J"}, **extra,
        }}}

    def test_tmlr_is_a_rolling_openreview_venue(self):
        tmlr = load_registry()["tmlr"]
        assert tmlr.rolling is True
        assert tmlr.source == "openreview"
        assert tmlr.announce_month == 1
        assert tmlr.probe == {"venue_id": "TMLR"}

    def test_rolling_defaults_to_false(self, tmp_path):
        assert load_registry(_write(tmp_path, self._venue()))["j"].rolling is False

    def test_rolling_must_be_a_bool(self, tmp_path):
        with pytest.raises(ValueError, match="rolling"):
            load_registry(_write(tmp_path, self._venue(rolling="yes")))

    def test_rolling_is_openreview_only(self, tmp_path):
        with pytest.raises(ValueError, match="rolling"):
            load_registry(_write(tmp_path, self._venue(source="dblp", rolling=True)))
