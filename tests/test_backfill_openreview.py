from pathlib import Path

import pytest

from ppr.config import CrawlConfig
from ppr.validate import DBLP_VALIDATION_KEYS

CONFIGS = Path(__file__).resolve().parent.parent / "configs"
BACKFILL_OPENREVIEW = [f"iclr_{y}" for y in range(2017, 2023)] + [
    "neurips_2021", "neurips_2022", "corl_2021", "corl_2022"]


@pytest.mark.parametrize("conf_id", BACKFILL_OPENREVIEW)
def test_config_is_v1_and_named_for_its_year(conf_id):
    cfg = CrawlConfig.from_yaml(CONFIGS / f"{conf_id}.yaml")
    assert cfg.api_version == 1
    assert cfg.year == int(conf_id.rsplit("_", 1)[1])


@pytest.mark.parametrize("conf_id", BACKFILL_OPENREVIEW)
def test_counts_are_cross_checked_against_dblp(conf_id):
    assert conf_id in DBLP_VALIDATION_KEYS


@pytest.mark.parametrize("conf_id,mode", [("iclr_2018", "invitation"),
                                          ("iclr_2019", "reply_suffix"),
                                          ("iclr_2020", "reply_suffix")])
def test_iclr_2018_to_2020_read_decisions(conf_id, mode):
    assert mode in CrawlConfig.from_yaml(CONFIGS / f"{conf_id}.yaml").decisions
