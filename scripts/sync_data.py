"""Mirror the newest data-* release into the checkout's data/.

The mirror itself is `ppr/data_sync.py`; this keeps the command line the
checkout has always used (and a schedule may call):

    uv run python -m scripts.sync_data [--force] [--notify]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ppr.data_sync import SyncRefused, fetch_latest_tag, fetch_zip, sync

ROOT = Path(__file__).resolve().parent.parent


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
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        status, old, new = sync(ROOT, fetch_latest_tag, fetch_zip, force=args.force)
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
