"""Bind awards.json entries to the papers they name.

Shared by the collector's report and scripts/build_data.py, so "this award is
on that paper" is decided in one place. Test-of-time prizes go to papers from
a decade earlier, which the dataset does not hold, so they are never joined:
they stay conference-level.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ppr.awards.labels import KIND_ORDER
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


def load_entries(conf_dir: Path) -> list[dict]:
    path = conf_dir / "awards.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["awards"]
