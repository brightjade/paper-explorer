"""Hand-reviewed award lists: configs/awards_manual/<conf_id>.yaml.

For pages no parser reads -- a PDF, a past year's static awards page, a
venue's one-off announcement -- the winners were extracted once, reviewed and
committed. Labels go through the same rules as every other source; a test
loads every file, so a bad label fails CI, not the monthly run.

    source: https://...            # where the list is (required)
    retrieved: 2026-10-17
    official: false                # optional; a list from secondary sources...
    also: [https://..., ...]       # ...names the sources that corroborate it
    note: partial (9 of 10)        # optional, for readers
    awards:
      - {label: "...", title: "...", url: "...", forum_id: "...", replaces: "..."}

A manual file is every venue's first source, so it wins any duplicate: that is
how it corrects another source's label. `replaces` corrects a title: another
source's entry of the same kind whose title is `replaces` is dropped, and this
entry, titled as the dataset titles the paper, stands instead.
"""

from pathlib import Path

import yaml

from ppr.awards.labels import UnknownAwardLabel, classify
from ppr.awards.model import Award
from ppr.matching import title_key

MANUAL_DIR = Path(__file__).resolve().parents[2] / "configs" / "awards_manual"


def _read(conf_id: str, manual_dir: Path | None) -> tuple[dict | None, Path]:
    path = (manual_dir or MANUAL_DIR) / f"{conf_id}.yaml"
    if not path.exists():
        return None, path
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("official", True) is False and not raw.get("also"):
        raise ValueError(f"{path.name}: a list from secondary sources names its corroboration under 'also'")
    return raw, path


def _kind(label: str, prefix: str, path: Path) -> str:
    kind = classify(label, prefix)
    if kind is None:
        raise UnknownAwardLabel(f"{path.name}: {label!r} is not an award")
    return kind


def load_manual(conf_id: str, manual_dir: Path | None = None) -> list[Award] | None:
    raw, path = _read(conf_id, manual_dir)
    if raw is None:
        return None
    prefix = conf_id.rsplit("_", 1)[0]
    return [Award(label=entry["label"], kind=_kind(entry["label"], prefix, path), title=entry["title"],
                  via="manual", source=raw["source"], forum_id=entry.get("forum_id", ""),
                  url=entry.get("url", ""))
            for entry in raw["awards"]]


def replaced_titles(conf_id: str, manual_dir: Path | None = None) -> set[tuple[str, str]]:
    """(kind, title_key) of every other source's title a reviewed entry replaces."""
    raw, path = _read(conf_id, manual_dir)
    if raw is None:
        return set()
    prefix = conf_id.rsplit("_", 1)[0]
    return {(_kind(entry["label"], prefix, path), title_key(entry["replaces"]))
            for entry in raw["awards"] if entry.get("replaces")}


def manual(conf_id: str, year: int, earlier: list[Award]) -> list[Award] | None:
    return load_manual(conf_id)
