"""`ppr search batch`: round files (find / cites / lookup `--json`) into judge batches.

Each candidate is cut down to the fields a judge reads (`compact`). One candidate per paper however many tools found it, none the judge has seen,
and a lookup record flattened to the papers it found (or to an `ext:` item
when the dataset holds none).
"""

import json
import re
from pathlib import Path

from ppr.search.find import snippet
from ppr.search.lookup import classify

SLUG_CHARS = 60
_NON_WORD = re.compile(r"[^a-z0-9]+")


def external_id(raw: str) -> str:
    """`ext:` plus the item's id value, or a dash-joined lowercase slug of a title."""
    item = classify(raw)
    if item.kind != "title":
        return f"ext:{item.value}"
    return "ext:" + _NON_WORD.sub("-", item.value.lower()).strip("-")[:SLUG_CHARS].strip("-")


def candidates(record: dict) -> list[dict]:
    """The records one JSONL line stands for."""
    if "status" in record and "papers" in record:  # a lookup record
        if record["papers"]:
            return record["papers"]
        raw = record["input"]
        return [{"id": external_id(raw), "title": raw, "group": "external"}]
    return [record]


def compact(cand: dict) -> dict:
    """What a judge reads of a candidate: no abstract, authors, counts or other columns."""
    if "pid" in cand:
        row = {"tldr": cand.get("tldr") or "", "abstract": cand.get("abstract") or ""}
        return {"pid": cand["pid"], "title": cand.get("title"), "tldr": snippet(row),
                "venue_name": cand.get("venue_name"), "year": cand.get("year"), "selection": cand.get("selection")}
    if str(cand.get("id", "")).startswith("s2:"):
        return {"id": cand["id"], "title": cand.get("title"), "year": cand.get("year"),
                "venue": cand.get("venue"), "snippet": cand.get("snippet") or ""}
    return {"id": cand["id"], "title": cand.get("title"), "group": "external"}


def collect(files: list[Path], exclude: frozenset[str] = frozenset()) -> list[dict]:
    """Candidates in file order, the first of each id kept, judged ids dropped."""
    seen, out = set(exclude), []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for cand in candidates(json.loads(line)):
                cid = cand.get("pid") or cand.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    out.append(compact(cand))
    return out


def write_batches(cands: list[dict], prefix: str, size: int = 40) -> list[tuple[Path, int]]:
    """`PREFIX-01.jsonl`, `PREFIX-02.jsonl`, … of at most `size` candidates each."""
    written = []
    for n, start in enumerate(range(0, len(cands), size), 1):
        chunk = cands[start:start + size]
        path = Path(f"{prefix}-{n:02d}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunk), encoding="utf-8")
        written.append((path, len(chunk)))
    return written
