"""Hand-reviewed award lists for one-off pages: configs/awards_manual/<conf_id>.yaml.

For past years whose only source is a page no future year reuses -- a PDF, a
photo-gallery site's one text page, a venue's own awards page -- the winners
were extracted once, reviewed and committed, rather than kept as a parser for
a page that will never change. Labels go through the same rules as every
other source; a test loads every file, so a bad label fails CI, not the
monthly run.
"""

from pathlib import Path

import yaml

from ppr.awards.labels import UnknownAwardLabel, classify
from ppr.awards.model import Award

MANUAL_DIR = Path(__file__).resolve().parents[2] / "configs" / "awards_manual"


def load_manual(conf_id: str, manual_dir: Path = MANUAL_DIR) -> list[Award] | None:
    path = manual_dir / f"{conf_id}.yaml"
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    prefix = conf_id.rsplit("_", 1)[0]
    awards = []
    for entry in raw["awards"]:
        kind = classify(entry["label"], prefix)
        if kind is None:
            raise UnknownAwardLabel(f"{path.name}: {entry['label']!r} is not an award")
        awards.append(Award(label=entry["label"], kind=kind, title=entry["title"], via="manual",
                            source=raw["source"], url=entry.get("url", "")))
    return awards


def manual(conf_id: str, year: int, earlier: list[Award]) -> list[Award] | None:
    return load_manual(conf_id)
