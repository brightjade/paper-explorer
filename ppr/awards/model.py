"""One award entry, how several sources' entries combine, and data/<id>/awards.json."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ppr.awards.labels import KIND_ORDER
from ppr.matching import title_key


@dataclass(frozen=True)
class Award:
    label: str      # exactly as the source names it; the only text the site shows
    kind: str       # one of labels.KINDS
    title: str      # the paper's title as the source gives it; joined by title_key
    via: str        # the source module that read it ("virtual", "manual", ...)
    source: str     # the page it was read from
    forum_id: str = ""  # OpenReview forum id, when the source links one
    url: str = ""       # an external link worth showing (test of time)

    def to_dict(self) -> dict:
        d = {"label": self.label, "kind": self.kind, "title": self.title}
        if self.forum_id:
            d["forum_id"] = self.forum_id
        if self.url:
            d["url"] = self.url
        d["via"] = self.via
        d["source"] = self.source
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Award":
        return cls(label=d["label"], kind=d["kind"], title=d["title"], via=d["via"],
                   source=d["source"], forum_id=d.get("forum_id", ""), url=d.get("url", ""))


def merge(results: list[list[Award]]) -> list[Award]:
    """Combine sources' results, given in priority order.

    Within one source, an entry repeating a (label, title) is dropped: ICML and
    ICLR list an award paper once for its oral and again for its poster. Across
    sources, an entry whose (kind, title) an earlier source already gave is
    dropped, so ECCV's "Best Paper Honorable Mention" from awards_detail and the
    registry's plain "Honorable Mention" for the same paper become one entry.
    A paper with two different labels of one kind from one source keeps both.
    """
    out: list[Award] = []
    claimed: set[tuple[str, str]] = set()
    for awards in results:
        seen: set[tuple[str, str]] = set()
        batch: list[Award] = []
        for a in awards:
            key = (a.label, title_key(a.title))
            if key not in seen:
                seen.add(key)
                batch.append(a)
        out.extend(a for a in batch if (a.kind, title_key(a.title)) not in claimed)
        claimed.update((a.kind, title_key(a.title)) for a in batch)
    return sorted(out, key=lambda a: (KIND_ORDER[a.kind], a.label, a.title))


def awards_path(data_dir: Path, conf_id: str) -> Path:
    return data_dir / conf_id / "awards.json"


def read_awards(path: Path) -> list[Award] | None:
    """The entries in `path`, or None when there is no file yet."""
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Award.from_dict(d) for d in raw["awards"]]


def write_awards(path: Path, conf_id: str, awards: list[Award]) -> None:
    """Replace `path` atomically: a crash mid-write leaves the previous file whole."""
    text = json.dumps({"conf_id": conf_id, "awards": [a.to_dict() for a in awards]},
                      ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".awards-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
