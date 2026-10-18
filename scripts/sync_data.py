"""Mirror the newest data-* release into data/.

The newest data release is the dataset's source of truth (ppr/release.py), so
a working copy only goes stale. This brings it up to date, and is safe to run
on a schedule: it does nothing while data/ already holds that release, and it
refuses to replace a data/ that has changed since it was installed -- that is
local work no release has seen, and a mirror must not be the thing that loses
it.

    uv run python -m scripts.sync_data [--force] [--notify]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import zlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath

from ppr.net import PROJECT_USER_AGENT

REPO = "brightjade/paper-explorer"
STATE_FILE = ".data-release.json"  # the installed tag, and what it wrote


class SyncRefused(Exception):
    """data/ holds something the newest release would silently overwrite."""


def newest_data_tag(releases: list[dict]) -> str:
    """The same rule the monthly workflow starts from: the newest published non-draft data-*.

    Not created_at, which is the tagged commit's date: releases made from one
    commit tie on it.
    """
    data = [r for r in releases if r["tag_name"].startswith("data-") and not r.get("draft")]
    if not data:
        raise RuntimeError("no data-* release found")
    return max(data, key=lambda r: r["published_at"])["tag_name"]


def fetch_latest_tag() -> str:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases?per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": PROJECT_USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return newest_data_tag(json.load(resp))


def fetch_zip(tag: str, dest: Path) -> None:
    req = urllib.request.Request(
        f"https://github.com/{REPO}/releases/download/{tag}/data.zip",
        headers={"User-Agent": PROJECT_USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _crc(path: Path) -> int:
    crc = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            crc = zlib.crc32(chunk, crc)
    return crc


def _snapshot(root: Path) -> dict[str, int]:
    """Every file under data/, keyed the way data.zip names it, with its CRC-32."""
    return {p.relative_to(root).as_posix(): _crc(p)
            for p in sorted((root / "data").rglob("*")) if p.is_file()}


def _differences(installed: dict[str, int], current: dict[str, int]) -> list[str]:
    return ([f"changed {n}" for n in sorted(installed.keys() & current.keys())
             if installed[n] != current[n]]
            + [f"added {n}" for n in sorted(current.keys() - installed.keys())]
            + [f"deleted {n}" for n in sorted(installed.keys() - current.keys())])


def _check_zip(z: zipfile.ZipFile) -> dict[str, int]:
    bad = z.testzip()
    if bad is not None:
        raise RuntimeError(f"data.zip is corrupt at {bad}")
    files = {i.filename: i.CRC for i in z.infolist() if not i.is_dir()}
    for name in files:
        parts = PurePosixPath(name).parts
        if name.startswith("/") or ".." in parts or len(parts) < 2 or parts[0] != "data":
            raise RuntimeError(f"data.zip has an entry outside data/: {name}")
    if not any(re.fullmatch(r"data/[^/]+/papers\.jsonl", name) for name in files):
        raise RuntimeError("data.zip holds no conference data")
    return files


def sync(root: Path, latest_tag: Callable[[], str], download: Callable[[str, Path], None],
         *, force: bool = False) -> tuple[str, str | None, str]:
    """Bring root/data to the newest release. Returns (status, old_tag, new_tag),
    status being "current" or "updated"."""
    root = Path(root)
    data = root / "data"
    state_path = root / STATE_FILE
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    old = state["tag"] if state else None
    has_data = data.is_dir() and any(data.iterdir())

    tag = latest_tag()
    if has_data and tag == old:
        return "current", old, tag

    if has_data and not force:
        if state is None:
            raise SyncRefused(
                "data/ was not installed by this script, so local work in it cannot be "
                "told apart from a release; check it, then rerun with --force")
        diffs = _differences(state["files"], _snapshot(root))
        if diffs:
            more = f" (+{len(diffs) - 5} more)" if len(diffs) > 5 else ""
            raise SyncRefused(
                f"data/ has changed since {old} was installed: {'; '.join(diffs[:5])}{more}. "
                f"Release or move that work, then rerun (--force discards it)")

    # Unpacked beside data/ so the swap is a rename on one filesystem, and a
    # failure anywhere before it leaves data/ exactly as it was.
    work = Path(tempfile.mkdtemp(prefix=".data-sync-", dir=root))
    try:
        zip_path = work / "data.zip"
        download(tag, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            files = _check_zip(z)
            z.extractall(work / "new")
        if data.exists():
            data.rename(work / "old")
        try:
            (work / "new" / "data").rename(data)
        except OSError:
            if (work / "old").exists():
                (work / "old").rename(data)
            raise
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tag": tag, "files": files}, indent=0, sort_keys=True))
        os.replace(tmp, state_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return "updated", old, tag


def _notify(message: str) -> None:
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title \"paper-explorer\""
        subprocess.run(["osascript", "-e", script], check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror the newest data-* release into data/.")
    parser.add_argument("--force", action="store_true",
                        help="replace data/ even if it holds files no release installed")
    parser.add_argument("--notify", action="store_true",
                        help="post a macOS notification when data/ changes or a sync is refused")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        status, old, new = sync(root, fetch_latest_tag, fetch_zip, force=args.force)
    except SyncRefused as exc:
        print(f"{stamp} refused: {exc}", file=sys.stderr)
        if args.notify:
            _notify("data/ not synced: it has local changes (see the sync log)")
        return 2
    if status == "current":
        print(f"{stamp} data/ already at {new}")
    else:
        print(f"{stamp} data/ updated: {old or 'none'} -> {new}")
        if args.notify:
            _notify(f"data/ updated to {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
