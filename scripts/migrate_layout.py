"""One-off: rebuild an old-layout data/ in the per-venue layout of ppr/layout.py.

    uv run python -m scripts.migrate_layout OLD_DATA_DIR NEW_DATA_DIR

The old layout is data/<id>/papers.jsonl + papers_enriched.jsonl + awards.json.
Each year file is the enriched records as they stand, with `abstract_source:
"s2"` on an abstract the crawl did not supply. OLD_DATA_DIR is never written;
nothing is written at all unless every conference-year can be converted, and
the result is checked against the source before the command reports success.
Deleted once the release in the new layout is out.
"""

import json
import shutil
import sys
from pathlib import Path

from ppr.awards.model import Award, read_awards, write_awards
from ppr.layout import conference_ids, papers_path, split_id
from ppr.models import Paper
from ppr.store import normalize_title, read_papers, save_enriched

KNOWN = {"papers.jsonl", "papers_enriched.jsonl", "awards.json"}


class MigrationError(Exception):
    pass


def _titles(papers: list[Paper]) -> list[str]:
    return sorted(normalize_title(p.title) for p in papers)


def _convert(conf_dir: Path) -> list[Paper]:
    raw = read_papers(conf_dir / "papers.jsonl")
    enriched = read_papers(conf_dir / "papers_enriched.jsonl") or raw
    if _titles(raw) != _titles(enriched):
        raise MigrationError(f"{conf_dir.name}: papers.jsonl and papers_enriched.jsonl list different "
                             f"papers; run `ppr enrich {conf_dir.name}` first")
    crawl: dict[str, set[str]] = {}
    for p in raw:
        crawl.setdefault(normalize_title(p.title), set()).add(p.abstract)
    for p in enriched:
        if p.abstract and p.abstract not in crawl[normalize_title(p.title)]:
            p.abstract_source = "s2"
    return enriched


def _awards(conf_dir: Path) -> list[Award] | None:
    path = conf_dir / "awards.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("conf_id") != conf_dir.name:
        raise MigrationError(f"{path}: names {raw.get('conf_id')!r}")
    return [Award.from_dict(d) for d in raw["awards"]]


def migrate(old: Path, new: Path) -> dict[str, int]:
    if new.exists() and any(new.iterdir()):
        raise MigrationError(f"{new} is not empty")
    plan: dict[str, tuple[list[Paper], list[Award] | None]] = {}
    for conf_dir in sorted(d for d in old.iterdir() if d.is_dir()):
        try:
            split_id(conf_dir.name)  # a folder that is not a conference id is an error, not data
        except ValueError as exc:
            raise MigrationError(str(exc)) from exc
        unknown = sorted({f.name for f in conf_dir.iterdir()} - KNOWN)
        if unknown:
            raise MigrationError(f"{conf_dir.name}: unexpected {unknown} (finish or delete an "
                                 f"unfinished enrich run's checkpoint first)")
        if not (conf_dir / "papers.jsonl").exists():
            raise MigrationError(f"{conf_dir.name}: no papers.jsonl")
        plan[conf_dir.name] = (_convert(conf_dir), _awards(conf_dir))
    for conf_id, (papers, awards) in plan.items():
        save_enriched(papers, papers_path(new, conf_id))
        if awards is not None:
            write_awards(new, conf_id, awards)
    for f in old.iterdir():
        if f.is_file():
            shutil.copy2(f, new / f.name)
    return {conf_id: len(papers) for conf_id, (papers, _) in plan.items()}


def verify(old: Path, new: Path) -> None:
    """Check `new` holds exactly `old`'s data. Raises MigrationError on the first difference."""
    old_ids = sorted(d.name for d in old.iterdir() if d.is_dir())
    if conference_ids(new) != old_ids:
        raise MigrationError(f"conference ids differ: {sorted(set(old_ids) ^ set(conference_ids(new)))}")
    for conf_id in old_ids:
        expected = read_papers(old / conf_id / "papers_enriched.jsonl") or read_papers(old / conf_id / "papers.jsonl")
        got = read_papers(papers_path(new, conf_id))
        for p in got:
            p.abstract_source = ""
        if got != expected:
            raise MigrationError(f"{conf_id}: migrated papers differ from papers_enriched.jsonl")
        before = _awards(old / conf_id)
        if before != read_awards(new, conf_id):
            raise MigrationError(f"{conf_id}: migrated awards differ")
    for f in old.iterdir():
        if f.is_file() and f.read_bytes() != (new / f.name).read_bytes():
            raise MigrationError(f"{f.name} differs")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    old, new = Path(argv[0]), Path(argv[1])
    try:
        counts = migrate(old, new)
        verify(old, new)
    except MigrationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"migrated {len(counts)} conference-years, {sum(counts.values())} papers -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
