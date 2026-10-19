"""Conferences crawled from DBLP toc pages (see `DBLP_CONFERENCES`).

Records come from DBLP's SPARQL endpoint through `ppr/dblp_client.py`, which
owns pacing, retries and cleaning (entities, trailing periods, author
disambiguation suffixes), so this module only maps records to papers.

Two kinds of entry share the dict. Live years are written here one toc key at
a time, by hand or by autoregister (`register_dblp`), and crawl as `main`. The
2013-2022 backfill lives in `configs/<venue>/dblp.yaml`: each conference-year
lists its proceedings volumes with the selection their papers get.
"""

import logging
from functools import partial
from pathlib import Path

import yaml

from ppr import dblp_client
from ppr.layout import CONFIGS_DIR, dblp_config_paths
from ppr.models import Paper

logger = logging.getLogger(__name__)

DBLP_CONFERENCES = {
    # Robotics
    "icra_2023": {"key": "db/conf/icra/icra2023.bht"},
    "icra_2024": {"key": "db/conf/icra/icra2024.bht"},
    "icra_2025": {"key": "db/conf/icra/icra2025.bht"},
    "iros_2023": {"key": "db/conf/iros/iros2023.bht"},
    "iros_2024": {"key": "db/conf/iros/iros2024.bht"},
    "iros_2025": {"key": "db/conf/iros/iros2025.bht"},
    # AI
    "ijcai_2023": {"key": "db/conf/ijcai/ijcai2023.bht"},
    "ijcai_2024": {"key": "db/conf/ijcai/ijcai2024.bht"},
    "ijcai_2025": {"key": "db/conf/ijcai/ijcai2025.bht"},
}


class EmptyTocError(Exception):
    """A backfill toc page answered with no listable papers: a registry error."""


def load_backfill(configs_dir: Path = CONFIGS_DIR) -> dict[str, dict]:
    """The reviewed 2013-2022 registry, from every configs/<venue>/dblp.yaml:
    conf_id -> {"tocs": [{"key", "selection"}]}."""
    out = {}
    for path in dblp_config_paths(configs_dir):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for year, entry in raw.items():
            tocs = entry.get("tocs") if isinstance(entry, dict) else None
            if not isinstance(year, int) or not tocs:
                raise ValueError(f"{path}: {year!r} needs a year key and a tocs list")
            out[f"{path.parent.name}_{year}"] = {
                "tocs": [{"key": t["key"], "selection": t["selection"]} for t in tocs]}
    return out


def merge_backfill(conferences: dict, backfill: dict) -> None:
    clash = sorted(conferences.keys() & backfill.keys())
    if clash:
        raise ValueError(f"backfill conference ids already registered in dblp.py: {clash}")
    conferences.update(backfill)


merge_backfill(DBLP_CONFERENCES, load_backfill())


def _scrape_dblp(conf_id: str) -> list[Paper]:
    """Scrape all papers for a conference from DBLP.

    The proceedings volume itself is excluded by the client. Records without a
    document page are skipped: a paper a reader cannot open is not one we list.
    A backfill toc that yields no paper at all is a registry error -- a wrong
    key or a volume DBLP reorganised -- and fails the conference rather than
    writing a short file.
    """
    entry = DBLP_CONFERENCES[conf_id]
    tocs = entry.get("tocs") or [{"key": entry["key"], "selection": "main"}]
    papers = []
    for toc in tocs:
        records = dblp_client.toc_papers(toc["key"])
        found = [
            Paper(title=r["title"], link=r["link"], authors=r["authors"], selection=toc["selection"])
            for r in records
            if r["link"]
        ]
        if not found and "tocs" in entry:
            raise EmptyTocError(f"{conf_id}: DBLP toc {toc['key']} yielded no papers")
        papers += found
    logger.info("Scraped %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_dblp, conf_id) for conf_id in DBLP_CONFERENCES}
