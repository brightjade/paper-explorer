"""`ppr search` and `ppr data`: the commands an installed ppr has.

Lean on purpose: module-level imports are the standard library and
`ppr.layout`, so these commands run without the pipeline's dependencies
(openreview-py, BeautifulSoup, ...). In a checkout `ppr/cli.py` adds the
pipeline commands around the same parsers.
"""

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from ppr import layout

CLIENT_COMMANDS = ("search", "data")


def _home() -> layout.Home:
    return layout.data_home()


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _mode(home: layout.Home) -> str:
    if os.environ.get(layout.HOME_ENV):
        return "PPR_HOME"
    return "installed" if home.managed else "checkout"


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ppr")
    except PackageNotFoundError:
        return "unknown"


def add_parsers(subparsers) -> None:
    search_parser = subparsers.add_parser("search", help="Search the dataset (the /survey skill's tool)")
    search_sub = search_parser.add_subparsers(dest="search_command", required=True)

    find_parser = search_sub.add_parser("find", help="Ranked keyword search over title, abstract, tldr, keywords")
    find_parser.add_argument("terms", nargs="*", help="Phrases, ORed; end one with * for a prefix")
    find_parser.add_argument("--must", action="append", default=[], help="A phrase every hit must have (repeatable)")
    find_parser.add_argument("--raw", default=None, help="An FTS5 expression, used as is")
    find_parser.add_argument("--venue", default="", help="Venue prefixes, comma-separated (iclr,neurips)")
    find_parser.add_argument("--years", default=None, help="YYYY or YYYY-YYYY")
    find_parser.add_argument("--selection", default="", help="Tracks, comma-separated (oral,spotlight)")
    find_parser.add_argument("--awarded", action="store_true", help="Only papers with an award")
    find_parser.add_argument("--exclude", type=Path, default=None, help="Skip ids in this file's first column")
    find_parser.add_argument("--sort", choices=("relevance", "citations", "year"), default="relevance")
    find_parser.add_argument("--limit", type=int, default=50)
    find_parser.add_argument("--offset", type=int, default=0)
    find_parser.add_argument("--abstract", action="store_true", help="Add the tldr or the abstract's start")
    find_parser.add_argument("--json", action="store_true", help="Full records, one JSON object per line")

    lookup_parser = search_sub.add_parser("lookup", help="Ground arXiv ids, DOIs, OpenReview links or titles")
    lookup_parser.add_argument("items", nargs="*")
    lookup_parser.add_argument("--file", type=Path, default=None, help="One item per line; # starts a comment")
    lookup_parser.add_argument("--json", action="store_true")

    cites_parser = search_sub.add_parser("cites", help="References and citations of seed papers (Semantic Scholar)")
    cites_parser.add_argument("seeds", nargs="+", help="pids, arXiv ids, DOIs, CorpusId:N, s2:N or titles")
    cites_parser.add_argument("--direction", choices=("refs", "citing", "both"), default="both")
    cites_parser.add_argument("--min-links", type=int, default=2, help="Outside papers need this many seeds")
    cites_parser.add_argument("--limit", type=int, default=50, help="Per group")
    cites_parser.add_argument("--abstract", action="store_true", help="Fetch outside papers' tldr")
    cites_parser.add_argument("--exclude", type=Path, default=None)
    cites_parser.add_argument("--json", action="store_true")
    cites_parser.add_argument("--api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
                              help="Semantic Scholar API key (default: SEMANTIC_SCHOLAR_API_KEY env var).")

    batch_parser = search_sub.add_parser("batch", help="Round files (find/cites/lookup --json) into judge batches")
    batch_parser.add_argument("files", nargs="+", type=Path, help="JSONL from find, cites or lookup --json")
    batch_parser.add_argument("--out", required=True, help="Batch path prefix: PREFIX-01.jsonl, PREFIX-02.jsonl, ...")
    batch_parser.add_argument("--exclude", type=Path, default=None, help="Skip ids in this file's first column")
    batch_parser.add_argument("--size", type=int, default=40, help="Candidates per batch")
    verdicts_parser = search_sub.add_parser("verdicts", help="Judges' PREFIX-NN.verdicts.tsv files into the judged file")
    verdicts_parser.add_argument("prefix", help="Batch path prefix, as given to batch --out")
    verdicts_parser.add_argument("--judged", required=True, type=Path, help="The judged.tsv to append to")
    verdicts_parser.add_argument("--round", required=True, type=int, dest="round_no", help="Round number to record")
    verdicts_parser.add_argument("--source", required=True, choices=["query", "cites", "external", "web"],
                                 help="Source to record")

    data_parser = subparsers.add_parser("data", help="The dataset ppr searches: where it is, which release")
    data_sub = data_parser.add_subparsers(dest="data_command", required=True)
    status_parser = data_sub.add_parser("status", help="Mode, data home, release, venues held (no network)")
    status_parser.add_argument("--json", action="store_true")
    update_parser = data_sub.add_parser("update", help="Fetch the newest data release now")
    update_parser.add_argument("--force", action="store_true",
                               help="replace data/ even if it holds files no release installed")


def add_version(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version", version=f"ppr {_version()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ppr", description="Search accepted papers at tracked venues, with their tracks and awards.")
    add_version(parser)
    add_parsers(parser.add_subparsers(dest="command", help="Available commands"))
    return parser


def _exit_on_sigterm(signum, frame) -> None:
    raise SystemExit(128 + signum)


def dispatch(args: argparse.Namespace) -> None:
    # A Bash tool timeout ends ppr with SIGTERM; as an exit, it runs the download's and index build's cleanup.
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    if args.command == "data":
        _cmd_data(args)
    else:
        _cmd_search(args)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    dispatch(args)


def _open(home: layout.Home):
    """The index of the home's data, downloading or refreshing it first in a managed home."""
    import sqlite3

    from ppr.data_home import DataUnavailable, ensure_data, home_lock
    from ppr.search.index import NoData, open_index

    try:
        if not home.managed:
            return open_index(home.data_dir, home.index_path)
        with home_lock(home.root, say=_err):
            ensure_data(home.root, auto_update=os.environ.get(layout.AUTO_UPDATE_ENV) != "0", say=_err)
            return open_index(home.data_dir, home.index_path)
    except DataUnavailable as exc:
        raise SystemExit(str(exc))
    except NoData as exc:
        if home.managed:
            raise SystemExit(f"no conference data in {home.root}; run `ppr data update`")
        raise SystemExit(str(exc))
    except (sqlite3.Error, OSError) as exc:
        raise SystemExit(f"search index build failed: {exc}")


def _cmd_search(args: argparse.Namespace) -> None:
    import json

    from ppr.search import batch, cites, find, lookup, verdicts

    if args.search_command == "batch":
        if args.size < 1:
            raise SystemExit("--size must be at least 1")
        missing = [str(f) for f in args.files if not f.exists()]
        if missing:
            raise SystemExit(f"batch: no such file: {', '.join(missing)}")
        if args.exclude and not args.exclude.exists():
            print(f"warning: --exclude file {args.exclude} does not exist; nothing excluded", file=sys.stderr)
        cands = batch.collect(args.files, find.read_exclude(args.exclude))
        written = batch.write_batches(cands, args.out, args.size)
        if not cands:
            print("0 candidates")
            return
        for path, n in written:
            print(f"{path}\t{n}")
        print(f"{len(cands)} candidates in {len(written)} batches")
        return

    if args.search_command == "verdicts":
        result = verdicts.collect(args.prefix, args.judged, args.round_no, args.source)
        if not result.batches:
            print(f"no batch files for {args.prefix}")
            raise SystemExit(1)
        for path, problems in result.problems:
            print(verdicts.format_problems(path, problems))
        print(result.summary())
        if not result.ok:
            raise SystemExit(1)
        return

    con = _open(_home())

    if args.search_command in ("find", "cites") and args.exclude and not args.exclude.exists():
        print(f"warning: --exclude file {args.exclude} does not exist; nothing excluded", file=sys.stderr)

    if args.search_command == "find":
        try:
            match = find.build_match(args.terms, args.must, args.raw)
            filters = find.Filters(
                venues=find.split_list(args.venue),
                years=find.parse_years(args.years) if args.years else None,
                selections=find.split_list(args.selection),
                awarded=args.awarded,
            )
            total, rows = find.search(con, match, filters, find.read_exclude(args.exclude),
                                      args.sort, args.limit, args.offset)
        except find.QueryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2)
        if args.json:
            for row in rows:
                print(json.dumps(find.row_dict(row), ensure_ascii=False))
        else:
            print(find.format_results(total, rows, args.offset, args.sort, args.abstract))
        return

    if args.search_command == "lookup":
        items = lookup.read_items(args.items, args.file)
        if not items:
            raise SystemExit("Nothing to look up: pass ids or titles, or --file.")
        results = [lookup.lookup(con, item) for item in items]
        if args.json:
            for result in results:
                print(json.dumps(lookup.result_dict(result), ensure_ascii=False))
        else:
            print("\n".join(lookup.format_result(result) for result in results))
        return

    from ppr.s2_client import S2Client

    client = S2Client(api_key=args.api_key or None)
    try:
        report = cites.chase(con, client, args.seeds, args.direction, args.min_links, args.limit,
                             find.read_exclude(args.exclude), args.abstract)
    except cites.S2Unavailable as exc:
        raise SystemExit(f"cites: {exc}")
    if args.json:
        for record in cites.report_records(report):
            print(json.dumps(record, ensure_ascii=False))
        if len(report.inside) < report.inside_total or len(report.outside) < report.outside_total:
            print(f"cites: in dataset {report.inside_total} (showing {len(report.inside)}), "
                  f"outside {report.outside_total} (showing {len(report.outside)}); raise --limit for more",
                  file=sys.stderr)
    else:
        print(cites.format_report(report))


def _cmd_data(args: argparse.Namespace) -> None:
    import json
    import time

    from ppr import data_home, data_sync

    home = _home()
    if args.data_command == "status":
        st = data_home.status(home, _mode(home))
        print(json.dumps(st, ensure_ascii=False) if args.json else data_home.format_status(st))
        return

    from ppr.search.index import open_index

    with data_home.home_lock(home.root, say=_err):
        if home.managed:
            data_home.clear_leftovers(home.root)
        try:
            status, old, new = data_sync.sync(home.root, data_sync.fetch_latest_tag, data_sync.fetch_zip,
                                              force=args.force)
        except data_sync.SyncRefused as exc:
            _err(f"refused: {exc}")
            raise SystemExit(2)
        except Exception as exc:
            raise SystemExit(f"data update failed: {exc}")
        if home.managed:
            data_home.record_check(home.root, time.time())
        # The index build is the other slow step; doing it here keeps it out of the next search.
        try:
            open_index(home.data_dir, home.index_path).close()
        except Exception as exc:
            raise SystemExit(f"data updated to {new}, but the search index build failed: {exc}")
    print(f"data/ already at {new}" if status == "current" else f"data/ updated: {old or 'none'} -> {new}")
