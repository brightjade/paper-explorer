"""Conferences crawled from DBLP toc pages (see `DBLP_CONFERENCES`).

Records come from DBLP's SPARQL endpoint through `ppr/dblp_client.py`, which
owns pacing, retries and cleaning (entities, trailing periods, author
disambiguation suffixes), so this module only maps records to papers.
"""

import logging
from functools import partial

from ppr import dblp_client
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


def _scrape_dblp(conf_id: str) -> list[Paper]:
    """Scrape all papers for a conference from DBLP.

    The proceedings volume itself is excluded by the client. Records without a
    document page are skipped, as the search-API scraper skipped entries
    without an `ee`.
    """
    conf = DBLP_CONFERENCES[conf_id]
    records = dblp_client.toc_papers(conf["key"], number=conf.get("number"))
    papers = [
        Paper(title=r["title"], link=r["link"], authors=r["authors"], selection="main")
        for r in records
        if r["link"]
    ]
    logger.info("Scraped %d papers for %s", len(papers), conf_id)
    return papers


SCRAPERS = {conf_id: partial(_scrape_dblp, conf_id) for conf_id in DBLP_CONFERENCES}
