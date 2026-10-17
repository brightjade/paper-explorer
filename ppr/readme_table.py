"""Keep README's conference table in step with registrations.

The table has one row per venue, with the years and tracks it covers. Rows are
edited in place rather than regenerated, so the hand-written field grouping and
the prose around the table survive.
"""

import re
from collections.abc import Iterable
from pathlib import Path

SELECTION_ORDER = ("oral", "spotlight", "poster", "main", "findings", "industry")

_STRIDE = re.compile(r"^(.*?)\s*\((odd|even) years\)$")
_RANGE = re.compile(r"^(\d{4})(?:\s*[–-]\s*(\d{4}))?$")


def selection_cell(selections: Iterable[str]) -> str:
    """The comma-separated track list README shows for a venue.

    Prefixed extra-track names (`datasets_oral`) are left out: README lists
    those in a note under the table.
    """
    keys = {s for s in selections if s and "_" not in s}
    known = [s for s in SELECTION_ORDER if s in keys]
    return ", ".join(known + sorted(keys - set(SELECTION_ORDER)))


def parse_years(cell: str) -> set[int]:
    """Read a Years cell: "2013, 2015–2026", or "2013–2025 (odd years)"."""
    step = 1
    if m := _STRIDE.match(cell.strip()):
        cell, step = m.group(1), 2
    years: set[int] = set()
    for part in filter(None, (p.strip() for p in cell.split(","))):
        m = _RANGE.match(part)
        if m is None:
            raise ValueError(f"unreadable year range {part!r}")
        start = int(m.group(1))
        years.update(range(start, int(m.group(2) or start) + 1, step))
    return years


def format_years(years: Iterable[int]) -> str:
    """Write years as runs, or one stride for a venue held every other year."""
    ys = sorted(set(years))
    if len(ys) >= 3 and all(b - a == 2 for a, b in zip(ys, ys[1:])):
        return f"{ys[0]}–{ys[-1]} ({'odd' if ys[0] % 2 else 'even'} years)"
    runs: list[list[int]] = []
    for y in ys:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row(cells: list[str]) -> str:
    # An empty cell renders as "| |", matching the hand-written table.
    return "|" + "|".join(f" {c} " if c else " " for c in cells) + "|"


def add_year(readme: str, venue_name: str, year: int, tracks: str) -> str | None:
    """Add `year` and `tracks` to the venue's row; None if no row names it."""
    lines = readme.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        head = _cells(line)
        if not {"Venue", "Years", "Tracks"} <= set(head):
            continue
        venue, years, track = (head.index(h) for h in ("Venue", "Years", "Tracks"))
        for r in range(i + 2, len(lines)):
            if not lines[r].startswith("|"):
                break
            cells = _cells(lines[r])
            if cells[venue] != venue_name:
                continue
            new_years = format_years(parse_years(cells[years]) | {year})
            new_tracks = selection_cell(
                t.strip() for t in f"{cells[track]},{tracks}".split(","))
            if (cells[years], cells[track]) != (new_years, new_tracks):
                cells[years], cells[track] = new_years, new_tracks
                lines[r] = _row(cells)
            return "\n".join(lines)
    return None


def update_readme(path: Path, venue_name: str, year: int, tracks: str) -> bool:
    updated = add_year(path.read_text(encoding="utf-8"), venue_name, year, tracks)
    if updated is None:
        return False
    path.write_text(updated, encoding="utf-8")
    return True
