"""An installed ppr's data: downloaded on first use, refreshed daily, never half-swapped.

The home is laid out like the repository root (`ppr/layout.py`), so the
release mirror (`ppr/data_sync.py`) and the search index work on it unchanged.
Every change to it happens under `home_lock`, because Claude runs several `ppr`
calls at once. Messages go through `say` (stderr in the CLI), never stdout.
"""

import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ppr import data_sync
from ppr.data_sync import STATE_FILE, sync
from ppr.layout import Home, conference_ids, split_id

CHECK_INTERVAL = 86400.0
CHECK_FILE = ".update-check"
LOCK_FILE = ".lock"
DOWNLOAD_SIZE = "about 124 MB"

Say = Callable[[str], None]


class DataUnavailable(Exception):
    """No data in the home, and none could be got."""


def fetch_latest_tag_short() -> str:
    """The daily check: a short timeout, so an unreachable GitHub costs seconds, not a minute."""
    return data_sync.fetch_latest_tag(timeout=10.0)


fetch_zip = data_sync.fetch_zip


@contextmanager
def home_lock(root: Path, say: Say) -> Iterator[None]:
    """Exclusive lock on `<root>/.lock`; says so when it has to wait for another process."""
    root.mkdir(parents=True, exist_ok=True)
    with open(root / LOCK_FILE, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            say(f"waiting for another ppr process using {root}…")
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def has_data(root: Path) -> bool:
    return bool(conference_ids(root / "data"))


def _last_check(root: Path) -> float | None:
    try:
        return float((root / CHECK_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def check_due(root: Path, now: float) -> bool:
    last = _last_check(root)
    return last is None or now - last > CHECK_INTERVAL


def installed_tag(root: Path) -> str | None:
    try:
        return json.loads((root / STATE_FILE).read_text(encoding="utf-8")).get("tag") or None
    except (OSError, ValueError):
        return None


def ensure_data(root: Path, *, auto_update: bool, say: Say,
                latest_tag: Callable[[], str] | None = None,
                download: Callable[[str, Path], None] | None = None,
                now: Callable[[], float] = time.time) -> None:
    """Download the newest release into an empty home, or refresh it once a day. The caller holds `home_lock`.

    With data on disk a failed check or download only warns: the search runs on what is there.
    """
    latest_tag = latest_tag or fetch_latest_tag_short
    fetch = download or fetch_zip
    root.mkdir(parents=True, exist_ok=True)

    def announced(tag: str, dest: Path) -> None:
        say(f"downloading data release {tag} into {root} ({DOWNLOAD_SIZE})…")
        fetch(tag, dest)

    if not has_data(root):
        if not auto_update:
            raise DataUnavailable(f"no data in {root}; run `ppr data update`")
        try:
            sync(root, latest_tag, announced)
        except Exception as exc:
            raise DataUnavailable(f"no data in {root}, and could not download it: {exc}") from exc
        _record_check(root, now())
        return

    if not auto_update or not check_due(root, now()):
        return
    try:
        status, old, new = sync(root, latest_tag, announced)
    except Exception as exc:
        hint = "; if this persists, run `uv tool upgrade ppr`" if isinstance(exc, RuntimeError) else ""
        say(f"warning: could not update the data ({exc}); "
            f"searching {installed_tag(root) or 'the data on disk'}{hint}")
    else:
        if status == "updated":
            say(f"data updated: {old or 'none'} -> {new}")
    _record_check(root, now())


def _record_check(root: Path, when: float) -> None:
    (root / CHECK_FILE).write_text(str(when), encoding="utf-8")


def _tree_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, files in os.walk(path, followlinks=True):
        total += sum(os.path.getsize(os.path.join(dirpath, f)) for f in files)
    return total


def status(home: Home, mode: str) -> dict:
    """What `ppr data status` shows. Reads the disk only; never the network."""
    from ppr.readme_table import format_years
    from ppr.venues import load_registry

    years: dict[str, list[int]] = {}
    for conf_id in conference_ids(home.data_dir):
        venue, year = split_id(conf_id)
        years.setdefault(venue, []).append(year)
    known = set(load_registry())
    last = _last_check(home.root)
    return {
        "mode": mode,
        "home": str(home.root),
        "managed": home.managed,
        "tag": installed_tag(home.root),
        "last_check": datetime.fromtimestamp(last, timezone.utc).isoformat(timespec="seconds") if last else None,
        "disk_bytes": _tree_bytes(home.data_dir) + _tree_bytes(home.index_path),
        "venues": {venue: format_years(ys) for venue, ys in sorted(years.items())},
        "unknown_venues": sorted(v for v in years if v not in known),
    }


def format_status(st: dict) -> str:
    lines = [
        f"mode        {st['mode']}",
        f"home        {st['home']}",
        f"release     {st['tag'] or 'none'}",
        f"last check  {st['last_check'] or 'never'}",
        f"disk        {st['disk_bytes'] / 1e6:.0f} MB",
        f"venues      {len(st['venues'])}",
    ]
    lines += [f"  {venue:<16} {ys}" for venue, ys in st["venues"].items()]
    if st["unknown_venues"]:
        lines.append(f"{len(st['unknown_venues'])} venue(s) this ppr does not know "
                     f"({', '.join(st['unknown_venues'])}): run `uv tool upgrade ppr`")
    return "\n".join(lines)
