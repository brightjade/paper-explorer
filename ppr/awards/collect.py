"""Collect each conference's awards into data/<id>/awards.json, never making it worse.

Each venue has an ordered list of sources (SOURCES_BY_PREFIX), so a new year is
covered by rule. Every conference ends in one of four states:

- collected: written atomically, with how many entries landed on a paper;
- not-yet:   every source answered with nothing, and there is no file yet;
- held:      a label no rule knows, or the run would lose entries (the whole
             result going empty, or a source that had entries on file now
             returning none) -- the file on disk stays;
- failed:    a source raised (network, HTTP status, markup that moved) -- the
             file on disk stays.

Held and failed are reported (the monthly issue), not fatal: awards add to the
data, and an unreachable awards page must not stop the month's citation release.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ppr.awards import cvf_registry, iclr_blog, manual, researchr_badges, sigsoft, usenix_notes, virtual
from ppr.awards.join import attach
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.model import Award, awards_path, merge, read_awards, write_awards

logger = logging.getLogger(__name__)

# Tranche 1 covers 2023 onward; older years are not collected by --all.
FIRST_YEAR = 2023

# (conf_id, year, earlier) -> awards, or None when the source chose not to run.
Source = Callable[[str, int, list[Award]], list[Award] | None]

# A manual file before SIGSOFT: a reviewed list counts as "winners already
# found", so SIGSOFT's lagging copy never duplicates it.
_SE: list[tuple[str, Source]] = [
    ("researchr", researchr_badges.researchr_badges),
    ("manual", manual.manual),
    ("sigsoft", sigsoft.sigsoft_backfill),
]

# Venue prefix -> ordered (name, source). An earlier source wins a duplicate
# (merge), and each name is the `via` its source writes, which the lost-source
# guard compares against the file on disk.
SOURCES_BY_PREFIX: dict[str, list[tuple[str, Source]]] = {
    "neurips": [("virtual", virtual.awards_detail), ("manual", manual.manual)],
    "icml": [("virtual", virtual.awards_detail), ("manual", manual.manual)],
    "iclr": [("iclr_blog", iclr_blog.iclr_blog), ("virtual", virtual.awards_detail), ("manual", manual.manual)],
    "cvpr": [("cvf_registry", cvf_registry.cvf_registry), ("virtual", virtual.cvpr_candidates),
             ("manual", manual.manual)],
    "iccv": [("cvf_registry", cvf_registry.cvf_registry), ("manual", manual.manual)],
    "eccv": [("virtual", virtual.awards_detail), ("cvf_registry", cvf_registry.cvf_registry),
             ("manual", manual.manual)],
    "wacv": [("manual", manual.manual)],
    "icse": _SE,
    "fse": _SE,
    "ase": _SE,
    "issta": _SE,
    "usenix_security": [("usenix", usenix_notes.usenix_awards), ("manual", manual.manual)],
}


@dataclass
class Outcome:
    conf_id: str
    status: str  # collected | not-yet | held | failed
    count: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    reason: str = ""


def _papers(data_dir: Path, conf_id: str) -> list[dict]:
    for name in ("papers_enriched.jsonl", "papers.jsonl"):
        path = data_dir / conf_id / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
    return []


def conference_ids(data_dir: Path) -> list[str]:
    """Every data/<id> whose venue has an awards rule and whose year is FIRST_YEAR or later, sorted."""
    if not data_dir.exists():
        return []
    out = []
    for d in data_dir.iterdir():
        prefix, _, year = d.name.rpartition("_")
        if d.is_dir() and prefix in SOURCES_BY_PREFIX and year.isdigit() and int(year) >= FIRST_YEAR:
            out.append(d.name)
    return sorted(out)


def collect_conference(conf_id: str, data_dir: Path) -> Outcome:
    prefix, _, year = conf_id.rpartition("_")
    sources = SOURCES_BY_PREFIX.get(prefix)
    if sources is None:
        return Outcome(conf_id, "failed", reason=f"no awards rule for venue {prefix!r}")

    results: dict[str, list[Award] | None] = {}
    earlier: list[Award] = []
    try:
        for name, source in sources:
            got = source(conf_id, int(year), list(earlier))
            results[name] = got
            earlier.extend(got or [])
    except UnknownAwardLabel as exc:
        return Outcome(conf_id, "held", reason=str(exc))
    except Exception as exc:  # network, HTTP status, markup that moved
        logger.warning("%s: an awards source failed: %s", conf_id, exc)
        return Outcome(conf_id, "failed", reason=f"{type(exc).__name__}: {exc}")

    path = awards_path(data_dir, conf_id)
    previous = read_awards(path) or []
    merged = merge([got for got in results.values() if got])
    if not merged:
        if previous:
            return Outcome(conf_id, "held", count=len(previous),
                           reason=f"every source returned nothing; keeping the {len(previous)} entries on file")
        return Outcome(conf_id, "not-yet")
    lost = sorted(name for name, got in results.items()
                  if got == [] and any(a.via == name for a in previous))
    if lost:
        on_file = sum(a.via in lost for a in previous)
        return Outcome(conf_id, "held", count=len(previous),
                       reason=f"{', '.join(lost)} returned nothing; the file on disk has {on_file} entries from it")

    write_awards(path, conf_id, merged)
    attached = attach(_papers(data_dir, conf_id), [a.to_dict() for a in merged])
    paper_level = sum(a.kind != "test_of_time" for a in merged)
    return Outcome(conf_id, "collected", count=len(merged), matched=paper_level - len(attached.unmatched),
                   unmatched=[e["title"] for e in attached.unmatched])


def collect_all(conf_ids: list[str], data_dir: Path) -> list[Outcome]:
    outcomes = []
    for conf_id in conf_ids:
        outcome = collect_conference(conf_id, data_dir)
        logger.info("%s: %s %s", conf_id, outcome.status, outcome.reason)
        outcomes.append(outcome)
    return outcomes


def results_to_json(outcomes: list[Outcome]) -> str:
    return json.dumps({"results": [asdict(o) for o in outcomes]}, ensure_ascii=False, indent=2)


def format_summary(outcomes: list[Outcome]) -> str:
    lines = []
    for o in outcomes:
        if o.status == "collected":
            detail = f"{o.count} entries, {o.matched} on papers"
            if o.unmatched:
                detail += f", {len(o.unmatched)} matching no paper"
        elif o.status == "not-yet":
            detail = "nothing published yet"
        else:
            detail = o.reason
        lines.append(f"{o.conf_id:<24} {o.status:<9} {detail}")
    return "\n".join(lines)
