"""Monthly recrawl of a rolling venue (TMLR), never dropping a paper.

A rolling venue's current year keeps growing, so the monthly run crawls it again
(`due_ids`: this year's id, plus last year's through March to catch the stragglers).
A recrawl is written only when every paper already on disk is still in it.

The rule is "every paper on disk is still there", not "the count did not shrink".
OpenReview errors come back as `[]` rather than an exception, and a partial answer
can be padded with new papers: a crawl that lost `b` but gained `c` and `d` is
bigger and still wrong. A paper's identity is its forum id, else its canonical
title. A venue that fails the rule is `held`, a crawl that raises is `failed`; both
keep their file on disk and are reported, not fatal.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from ppr.config import CrawlConfig
from ppr.matching import title_key
from ppr.layout import papers_path
from ppr.models import Paper
from ppr.store import read_papers, save_crawl
from ppr.venues import Venue

logger = logging.getLogger(__name__)


@dataclass
class RollingOutcome:
    conf_id: str
    status: str  # recrawled | held | failed
    before: int = 0
    after: int = 0
    reason: str = ""


def due_ids(registry: dict[str, Venue], data_dir: Path, configs_dir: Path, today: date) -> list[str]:
    """Rolling conference ids to recrawl: registered (config and data both exist).

    Last year stays due through March, so one failed January run does not leave its
    late-December papers out (and the hold in the issue lasts more than a month).
    """
    years = [today.year - 1, today.year] if today.month <= 3 else [today.year]
    ids = []
    for year in years:
        for prefix, venue in registry.items():
            if not venue.rolling:
                continue
            conf_id = f"{prefix}_{year}"
            if (configs_dir / f"{conf_id}.yaml").exists() and papers_path(data_dir, conf_id).exists():
                ids.append(conf_id)
    return ids


def _key(paper: Paper) -> str:
    return paper.forum_id or title_key(paper.title)


def recrawl_rolling(
    conf_ids: list[str],
    configs_dir: Path,
    data_dir: Path,
    fetch: Callable[[CrawlConfig], list[Paper]],
) -> list[RollingOutcome]:
    outcomes = []
    for conf_id in conf_ids:
        path = papers_path(data_dir, conf_id)
        try:
            config = CrawlConfig.from_yaml(configs_dir / f"{conf_id}.yaml")
            old = read_papers(path)
            new = fetch(config)
        except Exception as e:  # one venue's failure must not stop the others
            logger.warning("%s: rolling recrawl failed: %s", conf_id, e)
            outcomes.append(RollingOutcome(conf_id, "failed", reason=f"{type(e).__name__}: {e}"))
            continue
        have = {_key(p) for p in new}
        missing = sorted({_key(p) for p in old} - have)
        if missing:
            shown = ", ".join(missing[:3])
            outcomes.append(RollingOutcome(
                conf_id, "held", len(old), len(new),
                f"{len(missing)} paper(s) on disk missing from the crawl (crawl returned {len(new)}): {shown}"))
            continue
        try:
            save_crawl(new, path)
        except Exception as e:
            outcomes.append(RollingOutcome(conf_id, "failed", len(old), len(new), f"{type(e).__name__}: {e}"))
            continue
        outcomes.append(RollingOutcome(conf_id, "recrawled", len(old), len(new)))
    return outcomes


def results_to_json(outcomes: list[RollingOutcome]) -> str:
    return json.dumps({"results": [asdict(o) for o in outcomes]}, ensure_ascii=False, indent=2)


def format_summary(outcomes: list[RollingOutcome]) -> str:
    lines = []
    for o in outcomes:
        detail = f"{o.before} -> {o.after}" if o.status == "recrawled" else o.reason
        lines.append(f"{o.conf_id:<24} {o.status:<9} {detail}")
    return "\n".join(lines)
