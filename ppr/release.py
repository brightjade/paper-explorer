"""Publish data/ as a GitHub Release -- the dataset's source of truth.

The new release is created first and pruning is best-effort: deleting old
releases before creating the new one would leave no release at all if creation
failed, and the site would deploy against nothing.
"""

import json
import logging
import subprocess
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from ppr.layout import conference_ids, papers_path

logger = logging.getLogger(__name__)

KEEP = 3
PREFIX = "data-"
CHECKPOINT_SUFFIX = ".tmp.jsonl"

Runner = Callable[[list[str]], str]


class ReleaseAborted(Exception):
    """Publishing now would overwrite a release this run did not start from."""


def gh(cmd: list[str]) -> str:
    # stderr stays with the parent so gh's own error reaches the job log.
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True).stdout


def data_releases(run: Runner) -> list[str]:
    """Non-draft data releases, newest published first.

    Not by createdAt: GitHub sets it to the tagged commit's date, so releases
    made from one commit tie on it (data-2026-10-17-2 and -3), and a tie broken
    differently here and in the workflow aborted a release.
    """
    rows = json.loads(run(["gh", "release", "list", "--limit", "100",
                           "--json", "tagName,publishedAt,isDraft"]))
    rows = [r for r in rows if r["tagName"].startswith(PREFIX) and not r.get("isDraft")]
    rows.sort(key=lambda r: r["publishedAt"], reverse=True)
    return [r["tagName"] for r in rows]


def next_tag(today: str, existing: set[str]) -> str:
    base = f"{PREFIX}{today}"
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def make_zip(data_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(data_dir.rglob("*")):
            if path.is_file() and not path.name.endswith(CHECKPOINT_SUFFIX):
                z.write(path, path.relative_to(data_dir.parent).as_posix())


def _match_counts(data_dir: Path) -> Counter:
    counts: Counter = Counter()
    for conf_id in conference_ids(data_dir):
        with open(papers_path(data_dir, conf_id), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    counts[json.loads(line).get("match_status") or "unattempted"] += 1
    return counts


def render_notes(base_tag: str, register: dict | None, enrich: dict | None,
                 data_dir: Path, run_url: str) -> str:
    outcomes = (register or {}).get("outcomes", [])
    added = [f"{o['conf_id']} ({o['count']} papers)" for o in outcomes if o["status"] == "registered"]
    held = [f"{o['conf_id']} ({o['reason']})" for o in outcomes if o["status"] == "held"]
    deferred = sum(r.get("deferred", 0) for r in (enrich or {}).get("results", []))
    counts = _match_counts(data_dir)
    return "\n".join([
        f"Monthly pipeline run: {run_url}",
        f"Built on: {base_tag}",
        f"Added: {', '.join(added) or 'none'}",
        f"Held: {', '.join(held) or 'none'}",
        "Enrichment: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        + f", deferred {deferred}",
        "",
        "Download and extract with ./setup.sh",
    ])


def publish(data_dir: Path, base_tag: str, notes: str, today: str, run: Runner, *,
            zip_path: Path, dry_run: bool = False) -> str:
    tags = data_releases(run)
    if not tags or tags[0] != base_tag:
        raise ReleaseAborted(
            f"newest data release is {tags[0] if tags else 'missing'}, not {base_tag} "
            "-- someone released during this run; refusing to overwrite it"
        )
    tag = next_tag(today, set(tags))
    stale = tags[KEEP - 1:]
    if dry_run:
        logger.info("Would create %s and delete %s", tag, stale)
        return tag

    make_zip(data_dir, zip_path)
    run(["gh", "release", "create", tag, str(zip_path), "--title", f"Data release {today}",
         "--notes", notes, "--latest"])
    for old in stale:
        try:
            run(["gh", "release", "delete", old, "--yes", "--cleanup-tag"])
        except Exception as exc:  # an extra old release is harmless
            logger.warning("Could not delete %s: %s", old, exc)
            print(f"::warning::Could not delete {old}: {exc}")
    zip_path.unlink(missing_ok=True)
    return tag
