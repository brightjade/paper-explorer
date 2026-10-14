"""Keep README's conference tables in step with registrations.

The tables are hand-grouped by field (ML, NLP, CV, ...) with prose between
them, so they are edited cell by cell rather than regenerated.
"""

from collections.abc import Iterable
from pathlib import Path

SELECTION_ORDER = ("oral", "spotlight", "poster", "main", "findings", "industry")


def selection_cell(selections: Iterable[str]) -> str:
    """The comma-separated track list README shows for one conference-year.

    Prefixed extra-track names (`datasets_oral`) are left out: README lists
    those in a note under the table.
    """
    keys = {s for s in selections if s and "_" not in s}
    known = [s for s in SELECTION_ORDER if s in keys]
    return ", ".join(known + sorted(keys - set(SELECTION_ORDER)))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row(cells: list[str]) -> str:
    # An empty cell renders as "| |", matching the hand-written tables.
    return "|" + "|".join(f" {c} " if c else " " for c in cells) + "|"


def set_cell(readme: str, venue_name: str, year: int, value: str) -> str | None:
    lines = readme.split("\n")
    i = 0
    while i < len(lines):
        if not lines[i].startswith("| Conference |"):
            i += 1
            continue
        header, sep = i, i + 1
        end = sep + 1
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        rows = range(sep + 1, end)
        target = next((r for r in rows if _cells(lines[r])[0] == venue_name), None)
        if target is None:
            i = end
            continue

        head = _cells(lines[header])
        col = str(year)
        if col not in head:
            years = [int(h) for h in head[1:] if h.isdigit()]
            at = 1 + next((n for n, y in enumerate(years) if y < year), len(years))
            head.insert(at, col)
            lines[header] = _row(head)
            lines[sep] = "|" + "|".join("---" for _ in head) + "|"
            for r in rows:
                cells = _cells(lines[r])
                cells.insert(at, "")
                lines[r] = _row(cells)
        index = head.index(col)
        cells = _cells(lines[target])
        cells[index] = value
        lines[target] = _row(cells)
        return "\n".join(lines)
    return None


def update_readme(path: Path, venue_name: str, year: int, value: str) -> bool:
    updated = set_cell(path.read_text(encoding="utf-8"), venue_name, year, value)
    if updated is None:
        return False
    path.write_text(updated, encoding="utf-8")
    return True
