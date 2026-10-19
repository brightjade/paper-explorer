"""Bind data/<venue>/awards.json entries to the papers they name.

Shared by the collector's report and scripts/build_data.py, so "this award is
on that paper" is decided in one place. A test-of-time prize is conference-level where it was given; when the
dataset holds the paper it honors -- an earlier edition of the same venue --
`attach_test_of_time` also puts it on that paper, labeled with the awarding
conference ("Test of Time Award (NeurIPS 2023)").
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ppr.awards.labels import KIND_ORDER
from ppr.layout import awards_path, split_id
from ppr.matching import title_key


@dataclass
class Attached:
    papers: list[dict]        # copies of the input; matched ones carry "awards"
    test_of_time: list[dict]  # {"label", "title", "url"?} per conference-level entry
    unmatched: list[dict]     # paper-level entries no paper matched


def attach(papers: list[dict], entries: list[dict]) -> Attached:
    by_forum = {p["forum_id"]: i for i, p in enumerate(papers) if p.get("forum_id")}
    by_title: dict[str, int] = {}
    for i, p in enumerate(papers):
        by_title.setdefault(title_key(p["title"]), i)

    awards_for: dict[int, list[dict]] = {}
    test_of_time: list[dict] = []
    unmatched: list[dict] = []
    for e in entries:
        if e["kind"] == "test_of_time":
            test_of_time.append({k: e[k] for k in ("label", "title", "url") if e.get(k)})
            continue
        i = by_forum.get(e["forum_id"]) if e.get("forum_id") else None
        if i is None:
            i = by_title.get(title_key(e["title"]))
        if i is None:
            unmatched.append(e)
            continue
        awards_for.setdefault(i, []).append({"label": e["label"], "kind": e["kind"]})

    out = []
    for i, p in enumerate(papers):
        if i in awards_for:
            p = {**p, "awards": sorted(awards_for[i], key=lambda a: KIND_ORDER[a["kind"]])}
        out.append(p)
    return Attached(papers=out, test_of_time=test_of_time, unmatched=unmatched)


def load_entries(data_dir: Path, conf_id: str) -> list[dict]:
    path = awards_path(data_dir, conf_id)
    if not path.exists():
        return []
    _, year = split_id(conf_id)
    return json.loads(path.read_text(encoding="utf-8")).get(str(year), [])


@dataclass
class TestOfTimeLinks:
    papers: dict[str, list[dict]]        # every conference's papers, prizes added (changed papers are copies)
    test_of_time: dict[str, list[dict]]  # each awarding conference's entries, "conference" added where found
    warnings: list[str]
    found: int
    total: int


def _venue_year(conf_id: str) -> tuple[str, int | None]:
    prefix, _, year = conf_id.rpartition("_")
    return prefix, int(year) if year.isdigit() else None


def attach_test_of_time(papers_by_conf: dict[str, list[dict]], tot_by_conf: dict[str, list[dict]],
                        names: dict[str, str]) -> TestOfTimeLinks:
    """Give each test-of-time prize to the paper it honors, when the dataset holds it.

    Every prize in scope honors a paper of its own venue (Longuet-Higgins a CVPR
    paper, ICSE's Most Influential Paper an ICSE paper), so the paper is looked
    for by title_key in the awarding venue's earlier conferences. Found in one,
    it gains {"label": "<label> (<names[awarding id]>)", "kind": "test_of_time"};
    found in two, nothing is attached and a warning names them; not found -- a
    prize for a pre-2013 paper -- is the usual case and silent.
    """
    index: dict[str, dict[str, list[tuple[str, int]]]] = {}
    for conf_id, papers in papers_by_conf.items():
        prefix, year = _venue_year(conf_id)
        if year is None:
            continue
        by_title = index.setdefault(prefix, {})
        for i, paper in enumerate(papers):
            hits = by_title.setdefault(title_key(paper["title"]), [])
            if all(c != conf_id for c, _ in hits):
                hits.append((conf_id, i))

    added: dict[str, dict[int, list[dict]]] = {}
    linked: dict[str, list[dict]] = {}
    warnings: list[str] = []
    found = total = 0
    for conf_id, entries in tot_by_conf.items():
        prefix, year = _venue_year(conf_id)
        out = []
        for entry in entries:
            total += 1
            hits = [(c, i) for c, i in index.get(prefix, {}).get(title_key(entry["title"]), [])
                    if year is not None and (_venue_year(c)[1] or year) < year]
            if len(hits) == 1:
                c, i = hits[0]
                added.setdefault(c, {}).setdefault(i, []).append(
                    {"label": f"{entry['label']} ({names[conf_id]})", "kind": "test_of_time"})
                entry = {**entry, "conference": c}
                found += 1
            elif len(hits) > 1:
                warnings.append(f"{conf_id}: test of time {entry['title']!r} is in "
                                f"{', '.join(sorted(c for c, _ in hits))}; attached to none")
            out.append(entry)
        linked[conf_id] = out

    papers_out: dict[str, list[dict]] = {}
    for conf_id, papers in papers_by_conf.items():
        extra = added.get(conf_id, {})
        papers_out[conf_id] = [
            {**p, "awards": sorted(p.get("awards", []) + extra[i], key=lambda a: KIND_ORDER[a["kind"]])}
            if i in extra else p
            for i, p in enumerate(papers)]
    return TestOfTimeLinks(papers=papers_out, test_of_time=linked, warnings=warnings, found=found, total=total)
