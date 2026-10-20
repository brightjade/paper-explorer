"""`ppr search verdicts`: the judges' `PREFIX-NN.verdicts.tsv` files into the judged file.

A judge writes `id<TAB>verdict<TAB>reason` for every candidate of its batch. This reads each
batch's ids and verdict file, reports what does not line up (missing, unknown, duplicate or
badly labelled ids), and appends every valid line to the judged file, so a re-batch with
`--exclude` leaves exactly the unjudged papers.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ppr.search.find import read_exclude

LABELS = ("high", "medium", "low", "no")
HEADER = "pid\tverdict\tround\tsource\treason\n"
LISTED = 10
_WHITESPACE = re.compile(r"\s+")


@dataclass
class Result:
    batches: int = 0
    appended: int = 0
    already: int = 0
    counts: dict = field(default_factory=lambda: dict.fromkeys(LABELS, 0))
    problems: list = field(default_factory=list)  # (batch path, {problem: [ids]})

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        by = ", ".join(f"{label} {self.counts[label]}" for label in LABELS)
        return (f"appended {self.appended} ({by}); already judged {self.already}; "
                f"batches with problems {len(self.problems)}")


def batch_files(prefix: str) -> list[Path]:
    prefix_path = Path(prefix)
    pattern = re.compile(re.escape(prefix_path.name) + r"-\d+\.jsonl")
    return sorted(p for p in prefix_path.parent.glob(f"{prefix_path.name}-*.jsonl") if pattern.fullmatch(p.name))


def batch_ids(path: Path) -> list[str]:
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            ids.append(record.get("pid") or record["id"])
    return ids


def verdict_lines(path: Path) -> list[tuple[str, str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        parts += [""] * (3 - len(parts))
        out.append((parts[0].strip(), parts[1].strip(), parts[2]))
    return out


def format_problems(path: Path, problems: dict) -> str:
    parts = []
    for kind, ids in problems.items():
        if not ids:
            parts.append(kind)
            continue
        shown = ", ".join(ids[:LISTED]) + (", …" if len(ids) > LISTED else "")
        parts.append(f"{kind} {len(ids)} ({shown})")
    return f"{path}: " + ", ".join(parts)


def collect(prefix: str, judged: Path, round_no: int, source: str) -> Result:
    result = Result()
    files = batch_files(prefix)
    result.batches = len(files)
    held = set(read_exclude(judged))
    new_lines = []
    for path in files:
        ids = batch_ids(path)
        in_batch = set(ids)
        vpath = path.with_name(path.name.removesuffix(".jsonl") + ".verdicts.tsv")
        if not vpath.exists():
            result.problems.append((path, {"verdict file missing": []}))
            continue
        problems = {"missing": [], "unknown": [], "duplicate": [], "bad label": []}
        got = set()
        for pid, verdict, reason in verdict_lines(vpath):
            if pid not in in_batch:
                problems["unknown"].append(pid)
            elif pid in got:
                problems["duplicate"].append(pid)
            elif verdict not in LABELS:
                problems["bad label"].append(pid)
            else:
                got.add(pid)
                if pid in held:
                    result.already += 1
                    continue
                held.add(pid)
                result.counts[verdict] += 1
                result.appended += 1
                new_lines.append(f"{pid}\t{verdict}\t{round_no}\t{source}\t{_WHITESPACE.sub(' ', reason).strip()}\n")
        problems["missing"] = [i for i in ids if i not in got]
        problems = {kind: found for kind, found in problems.items() if found}
        if problems:
            result.problems.append((path, problems))
    if new_lines:
        judged.parent.mkdir(parents=True, exist_ok=True)
        fresh = not judged.exists() or judged.stat().st_size == 0
        with judged.open("a", encoding="utf-8") as f:
            if fresh:
                f.write(HEADER)
            f.writelines(new_lines)
    return result
