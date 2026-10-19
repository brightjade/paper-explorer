"""Where every per-conference file lives. No other module builds these paths.

A conference ID is `<venue>_<year>` wherever it is read or shown; only storage
is grouped by venue:

    data/<venue>/<year>.jsonl            papers: crawl + enrich, sorted by citations
    data/<venue>/.<year>.tmp.jsonl       an unfinished enrich run's checkpoint
    data/<venue>/awards.json             {"<year>": [entry, ...], ...}
    configs/<venue>/<year>.yaml          OpenReview crawl config
    configs/<venue>/awards/<year>.yaml   hand-reviewed award list
    configs/<venue>/dblp.yaml            2013-2022 DBLP toc pages, keyed by year

`configs/venues.yaml`, `data/pipeline_state.json` and `data/citation_updated.txt`
sit at the roots and are no conference's.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIGS_DIR = ROOT / "configs"

_YEAR = re.compile(r"\d{4}")


def split_id(conf_id: str) -> tuple[str, int]:
    """`usenix_security_2025` -> ("usenix_security", 2025): the venue is everything before the last `_`."""
    venue, _, year = conf_id.rpartition("_")
    if not venue or not _YEAR.fullmatch(year):
        raise ValueError(f"not a conference id: {conf_id!r}")
    return venue, int(year)


def papers_path(data_dir: Path, conf_id: str) -> Path:
    venue, year = split_id(conf_id)
    return data_dir / venue / f"{year}.jsonl"


def checkpoint_path(data_dir: Path, conf_id: str) -> Path:
    """Hidden, and ending in `.tmp.jsonl` so `ppr release` leaves it out of data.zip."""
    venue, year = split_id(conf_id)
    return data_dir / venue / f".{year}.tmp.jsonl"


def awards_path(data_dir: Path, conf_id: str) -> Path:
    venue, _ = split_id(conf_id)
    return data_dir / venue / "awards.json"


def conference_ids(data_dir: Path) -> list[str]:
    """Every conference-year with a papers file under `data_dir`, sorted."""
    if not data_dir.is_dir():
        return []
    return sorted(f"{p.parent.name}_{p.stem}" for p in data_dir.glob("*/*.jsonl") if _YEAR.fullmatch(p.stem))


def crawl_config_path(configs_dir: Path, conf_id: str) -> Path:
    venue, year = split_id(conf_id)
    return configs_dir / venue / f"{year}.yaml"


def manual_awards_path(configs_dir: Path, conf_id: str) -> Path:
    venue, year = split_id(conf_id)
    return configs_dir / venue / "awards" / f"{year}.yaml"


def config_conference_id(path: Path) -> str:
    """The conference a `configs/<venue>/<year>.yaml` crawl config belongs to."""
    path = Path(path)
    if not _YEAR.fullmatch(path.stem) or not path.parent.name:
        raise ValueError(f"{path}: a crawl config lives at configs/<venue>/<year>.yaml")
    return f"{path.parent.name}_{path.stem}"


def crawl_config_ids(configs_dir: Path) -> list[str]:
    """Every conference with an OpenReview crawl config, sorted."""
    return sorted(config_conference_id(p) for p in configs_dir.glob("*/*.yaml") if _YEAR.fullmatch(p.stem))


def dblp_config_paths(configs_dir: Path) -> list[Path]:
    return sorted(configs_dir.glob("*/dblp.yaml"))
