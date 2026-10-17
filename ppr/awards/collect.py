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
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable

from ppr.awards import ase_mip, cvf_registry, iclr_blog, icse_mip, issta_impact, manual, researchr_badges, sigsoft, tmlr_certifications, usenix_notes, usenix_tot, virtual
from ppr.awards.join import attach
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.model import Award, awards_path, merge, read_awards, write_awards
from ppr.matching import title_key

logger = logging.getLogger(__name__)

# (conf_id, year, earlier) -> awards, or None when the source chose not to run.
Source = Callable[[str, int, list[Award]], list[Award] | None]

# Every venue reads its reviewed manual file first, so the file wins any
# duplicate (correcting another source's label) and, being "winners already
# found", keeps SIGSOFT's lagging copy from duplicating it.
_SE: list[tuple[str, Source]] = [
    ("manual", manual.manual),
    ("researchr", researchr_badges.researchr_badges),
    ("sigsoft", sigsoft.sigsoft_backfill),
]

# Venue prefix -> ordered (name, source). An earlier source wins a duplicate
# (merge), and each name is the `via` its source writes, which the lost-source
# guard compares against the file on disk.
SOURCES_BY_PREFIX: dict[str, list[tuple[str, Source]]] = {
    "neurips": [("manual", manual.manual), ("virtual", virtual.awards_detail)],
    "icml": [("manual", manual.manual), ("virtual", virtual.awards_detail)],
    "iclr": [("manual", manual.manual), ("iclr_blog", iclr_blog.iclr_blog), ("virtual", virtual.awards_detail),
             ("iclr_tot", iclr_blog.iclr_test_of_time)],
    "cvpr": [("manual", manual.manual), ("cvf_registry", cvf_registry.cvf_registry),
             ("virtual", virtual.cvpr_candidates)],
    "iccv": [("manual", manual.manual), ("cvf_registry", cvf_registry.cvf_registry)],
    "eccv": [("manual", manual.manual), ("virtual", virtual.awards_detail),
             ("cvf_registry", cvf_registry.cvf_registry)],
    "wacv": [("manual", manual.manual)],
    "icse": _SE + [("icse_mip", icse_mip.icse_mip)],
    "fse": _SE,
    "ase": _SE + [("ase_mip", ase_mip.ase_mip)],
    "issta": _SE + [("issta_impact", issta_impact.issta_impact)],
    "usenix_security": [("manual", manual.manual), ("usenix", usenix_notes.usenix_awards),
                        ("usenix_tot", usenix_tot.usenix_tot)],
    "tmlr": [("tmlr", tmlr_certifications.tmlr_certifications)],
}

# The monthly run collects this year and last year. Awards arrive at or after a
# conference and keep arriving in stages (candidates, then winners; SIGSOFT's
# list months later), and twelve-plus months after a conference has covered
# every late source seen. Older years are final: `all_years` collects them on
# request (`ppr awards --all --all-years`, the workflow's awards_all_years).
RECENT_YEARS = 2

# A venue whose older years stay in the monthly run, from this year on: a TMLR
# certification can land on a paper published years earlier.
FIRST_YEAR_BY_PREFIX = {"tmlr": 2022}


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


def _retitle(awards: list[Award], papers: list[dict]) -> list[Award]:
    """Give an award the title of the paper its forum id names, so two spellings of one paper dedupe in merge."""
    titles = {p["forum_id"]: p["title"] for p in papers if p.get("forum_id") and p.get("title")}
    return [replace(a, title=titles[a.forum_id]) if a.forum_id in titles else a for a in awards]


def conference_ids(data_dir: Path, today: date | None = None, all_years: bool = False) -> list[str]:
    """Every data/<id> whose venue has an awards rule and whose awards can still change, sorted.

    That is this year and last year (RECENT_YEARS), plus every year from a
    venue's FIRST_YEAR_BY_PREFIX on. `all_years` drops the year test.
    """
    if not data_dir.exists():
        return []
    first_recent = (today or date.today()).year - RECENT_YEARS + 1
    out = []
    for d in data_dir.iterdir():
        prefix, _, year = d.name.rpartition("_")
        if not (d.is_dir() and prefix in SOURCES_BY_PREFIX and year.isdigit()):
            continue
        first = min(first_recent, FIRST_YEAR_BY_PREFIX.get(prefix, first_recent))
        if all_years or int(year) >= first:
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

    try:
        return _merge_and_write(conf_id, data_dir, results)
    except Exception as exc:  # corrupt awards.json, malformed papers, failed write
        logger.warning("%s: collecting failed after the sources ran: %s", conf_id, exc)
        return Outcome(conf_id, "failed", reason=f"{type(exc).__name__}: {exc}")


def _merge_and_write(conf_id: str, data_dir: Path, results: dict[str, list[Award] | None]) -> Outcome:
    path = awards_path(data_dir, conf_id)
    previous = read_awards(path) or []
    papers = _papers(data_dir, conf_id)
    replaced = manual.replaced_titles(conf_id)
    kept = [got if name == "manual" else [a for a in got if (a.kind, title_key(a.title)) not in replaced]
            for name, got in results.items() if got]
    merged = merge([_retitle(got, papers) for got in kept])
    if not merged:
        if previous:
            return Outcome(conf_id, "held", count=len(previous),
                           reason=f"every source returned nothing; keeping the {len(previous)} entries on file")
        return Outcome(conf_id, "not-yet")
    covered = {(a.kind, title_key(a.title)) for a in merged}
    uncovered: dict[str, int] = {}
    for a in previous:
        if results.get(a.via) == [] and (a.kind, title_key(a.title)) not in covered:
            uncovered[a.via] = uncovered.get(a.via, 0) + 1
    if uncovered:
        names = sorted(uncovered)
        return Outcome(conf_id, "held", count=len(previous),
                       reason=f"{', '.join(names)} returned nothing; the file on disk has "
                              f"{sum(uncovered.values())} entries from it")
    attached = attach(papers, [a.to_dict() for a in merged])  # before the write, so a failure leaves the file alone
    write_awards(path, conf_id, merged)
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
