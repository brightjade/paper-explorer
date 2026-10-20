import argparse
import asyncio
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from ppr.scrapers import SCRAPERS
from ppr.api_client import OpenReviewAPIClient, create_openreview_client, create_openreview_v1_client
from ppr.config import CrawlConfig
from ppr.enrich import (
    NO_DEADLINE,
    Deadline,
    enrich_all,
    format_enrich_summary,
    parse_duration,
    results_to_json,
)
from ppr.layout import conference_ids, crawl_config_ids, crawl_config_path, papers_path, search_index_path
from ppr.models import Paper
from ppr.s2_client import S2Client
from ppr.store import save_crawl

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEARCH_INDEX = search_index_path(DATA_DIR.parent)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _available_conferences() -> list[str]:
    from ppr.discover import known_conference_ids

    return sorted(known_conference_ids())


def all_conference_ids(data_dir: Path) -> list[str]:
    """Every conference-year with a papers file under data/, sorted."""
    return conference_ids(data_dir)


def _save_papers(papers: list[Paper], conf_id: str) -> Path:
    # Shares `save_crawl`'s refusals with the OpenReview save path: a scraper
    # whose selector a site redesign outgrew returns `[]` just as an API error
    # does, and must not silently erase the last good crawl either.
    return save_crawl(papers, papers_path(DATA_DIR, conf_id))


def _add_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--username",
        default=os.environ.get("OPENREVIEW_USERNAME"),
        help="OpenReview username (default: OPENREVIEW_USERNAME env var).",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("OPENREVIEW_PASSWORD"),
        help="OpenReview password (default: OPENREVIEW_PASSWORD env var).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ppr",
        description="Crawl, enrich and publish accepted-paper metadata from tracked conferences.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # crawl
    crawl_parser = subparsers.add_parser(
        "crawl", help="Fetch accepted papers (e.g., ppr crawl iclr_2025 neurips_2025)"
    )
    crawl_parser.add_argument(
        "conferences", nargs="+",
        help="Conference IDs (e.g., iclr_2025 neurips_2025).",
    )
    _add_auth_args(crawl_parser)

    # enrich
    enrich_parser = subparsers.add_parser(
        "enrich", help="Enrich papers with Semantic Scholar metadata (e.g., ppr enrich iclr_2025 neurips_2025)"
    )
    enrich_parser.add_argument(
        "conferences", nargs="*", default=[],
        help="Conference IDs (e.g., iclr_2026 neurips_2026). Omit with --all.",
    )
    enrich_parser.add_argument(
        "--all", action="store_true",
        help="Enrich every conference under data/. Archive years (4+ years old) "
        "follow a monthly cohort, batch-only.",
    )
    enrich_parser.add_argument(
        "--full", action="store_true",
        help="Discard existing enrichment and re-run the cold path.",
    )
    enrich_parser.add_argument(
        "--api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
        help="Semantic Scholar API key (optional, increases rate limits).",
    )
    enrich_parser.add_argument(
        "--time-budget", type=parse_duration, default=None,
        help="Stop per-title matching after this long (e.g. 4h); the rest is retried next run.",
    )
    enrich_parser.add_argument(
        "--report", type=Path, default=None,
        help="Write per-conference results as JSON (written even when a conference fails).",
    )
    enrich_parser.add_argument(
        "--require", nargs="+", default=[], metavar="CONF_ID",
        help="Exit non-zero unless each of these ends enriched or nothing-to-do (used after a re-crawl).",
    )

    # awards
    awards_parser = subparsers.add_parser(
        "awards", help="Collect paper awards into data/<venue>/awards.json"
    )
    awards_parser.add_argument("conferences", nargs="*", help="Conference IDs (e.g. neurips_2024)")
    awards_parser.add_argument("--all", action="store_true",
                               help="Every data/<venue>/<year>.jsonl whose venue has an awards rule")
    awards_parser.add_argument("--all-years", action="store_true",
                               help="With --all: also every older year, whose awards are final "
                                    "(--all alone collects this year and last year)")
    awards_parser.add_argument("--report", type=Path, default=None,
                               help="Write per-conference outcomes as JSON")

    # rolling
    rolling_parser = subparsers.add_parser(
        "rolling", help="Recrawl rolling venues (TMLR), keeping every paper already on disk"
    )
    rolling_parser.add_argument("--report", type=Path, default=None,
                                help="Write per-conference outcomes as JSON")
    _add_auth_args(rolling_parser)

    # validate
    validate_parser = subparsers.add_parser(
        "validate", help="Cross-reference paper counts against DBLP (e.g., ppr validate iclr_2025)"
    )
    validate_parser.add_argument(
        "conferences", nargs="+",
        help="Conference IDs to validate.",
    )
    validate_parser.add_argument(
        "--tolerance", type=float, default=0.1,
        help="Maximum allowed relative difference (default: 0.1 = 10%%).",
    )

    # discover
    discover_parser = subparsers.add_parser(
        "discover", help="Check tracked venues for newly published accepted-paper lists"
    )
    discover_parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of a table.",
    )
    discover_parser.add_argument(
        "--venue", action="append", default=[],
        help="Limit the sweep to these venue prefixes (repeatable).",
    )
    _add_auth_args(discover_parser)

    # autoregister
    autoregister_parser = subparsers.add_parser(
        "autoregister", help="Register, crawl and check live venues from a discover --json report"
    )
    autoregister_parser.add_argument("discover_json", type=Path)
    autoregister_parser.add_argument("--report", type=Path, required=True,
                                     help="Where to write the per-venue outcomes as JSON.")
    autoregister_parser.add_argument("--commit", action="store_true",
                                     help="Commit each registered venue (used by the monthly workflow).")
    _add_auth_args(autoregister_parser)

    # report
    report_parser = subparsers.add_parser("report", help="Pipeline state and issue decisions")
    report_sub = report_parser.add_subparsers(dest="report_command", required=True)
    state_parser = report_sub.add_parser("state", help="Update deferral streaks from an enrich report")
    state_parser.add_argument("--enrich", type=Path, required=True)
    state_parser.add_argument("--state", type=Path, required=True)
    issue_parser = report_sub.add_parser("issue", help="Decide the tracking-issue action")
    for name in ("discover", "register", "enrich", "state", "awards", "rolling"):
        issue_parser.add_argument(f"--{name}", type=Path, default=None)
    issue_parser.add_argument("--pipeline-result", required=True)
    issue_parser.add_argument("--run-url", required=True)
    issue_parser.add_argument("--out", type=Path, required=True)

    # release
    release_parser = subparsers.add_parser("release", help="Publish data/ as a GitHub Release")
    release_parser.add_argument("--base-tag", required=True,
                                help="The data release this run started from.")
    release_parser.add_argument("--register", type=Path, default=None)
    release_parser.add_argument("--enrich", type=Path, default=None)
    release_parser.add_argument("--run-url", default="(manual)")
    release_parser.add_argument("--dry-run", action="store_true")

    # search
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

    return parser


def cmd_crawl(args: argparse.Namespace) -> None:
    conf_ids = args.conferences

    # Split into scraped vs OpenReview conferences
    configured = set(crawl_config_ids(CONFIGS_DIR))
    scraped = [c for c in conf_ids if c in SCRAPERS]
    openreview = [c for c in conf_ids if c not in SCRAPERS and c in configured]
    unknown = [c for c in conf_ids if c not in scraped and c not in openreview]

    if unknown:
        available = _available_conferences()
        raise FileNotFoundError(
            f"Unknown conference(s): {', '.join(unknown)}. "
            f"Available: {', '.join(available)}"
        )

    # Scrape non-OpenReview conferences (no login needed)
    for conf_id in scraped:
        papers = SCRAPERS[conf_id]()
        save_path = _save_papers(papers, conf_id)
        logger.info("Done: %s (%d papers) -> %s", conf_id, len(papers), save_path)

    # Fetch OpenReview conferences (one login per API version, reuse clients)
    if openreview:
        configs = [CrawlConfig.from_yaml(crawl_config_path(CONFIGS_DIR, c)) for c in openreview]
        api_versions = {c.api_version for c in configs}

        # Create only the clients needed (avoids unnecessary logins)
        or_clients = {}
        if 1 in api_versions:
            or_clients[1] = create_openreview_v1_client(
                username=args.username, password=args.password
            )
        if 2 in api_versions:
            or_clients[2] = create_openreview_client(
                username=args.username, password=args.password
            )

        for config in configs:
            client = OpenReviewAPIClient(config, or_clients[config.api_version])
            papers = client.fetch_papers()
            client.save_papers(papers)
            logger.info(
                "Done: %s %s (%d papers) -> %s",
                config.name, config.year, len(papers), config.get_save_path(),
            )


def cmd_enrich(args: argparse.Namespace) -> None:
    conf_ids = all_conference_ids(DATA_DIR) if args.all else args.conferences
    if not conf_ids:
        raise SystemExit(
            "No conferences given. Pass conference IDs or use --all."
        )

    deadline = Deadline(args.time_budget) if args.time_budget is not None else NO_DEADLINE
    client = S2Client(api_key=args.api_key or None)
    # Only the monthly --all run applies the archive rule. Named conferences,
    # and those a re-crawl requires, get a full enrich; so does --full, which
    # exists to re-run every cold path.
    today = date.today() if args.all and not args.full else None
    results = asyncio.run(
        enrich_all(
            conf_ids,
            client,
            DATA_DIR,
            full=args.full,
            deadline=deadline,
            today=today,
            exempt=frozenset(args.require),
        )
    )
    print(format_enrich_summary(results))
    if args.report:
        # Before the exit below: the notify job needs this most when it failed.
        args.report.write_text(results_to_json(results), encoding="utf-8")

    # `ppr enrich --all` feeds ./build.sh and a data release, so a crashed
    # conference must not read as success to the calling shell. Guard skips are
    # a correct outcome and stay exit-0 -- except for a required conference, where
    # a skip keeps the crawl's papers with old enrichment and a release would ship it.
    failures = [r for r in results if r.status == "failed"]
    status = {r.conf_id: r.status for r in results}
    unmet = [c for c in args.require if status.get(c) not in ("enriched", "nothing-to-do")]
    for conf_id in unmet:
        print(f"required conference {conf_id} ended {status.get(conf_id, 'missing')}; failing the run")
    if failures or unmet:
        raise SystemExit(1)


def cmd_awards(args: argparse.Namespace) -> None:
    from ppr.awards.collect import collect_all, conference_ids, format_summary, results_to_json

    if args.all_years and not args.all:
        raise SystemExit("--all-years goes with --all.")
    conf_ids = conference_ids(DATA_DIR, all_years=args.all_years) if args.all else args.conferences
    if not conf_ids:
        raise SystemExit("No conferences given. Pass conference IDs or use --all.")
    outcomes = collect_all(conf_ids, DATA_DIR)
    print(format_summary(outcomes))
    if args.report:
        args.report.write_text(results_to_json(outcomes), encoding="utf-8")
    # Held and failed conferences keep their previous awards.json and go to the
    # monthly issue; they do not fail the run (ppr/awards/collect.py says why).


def cmd_rolling(args: argparse.Namespace) -> None:
    from ppr.rolling import due_ids, format_summary, recrawl_rolling, results_to_json
    from ppr.venues import load_registry

    conf_ids = due_ids(load_registry(), DATA_DIR, CONFIGS_DIR, date.today())
    client = None

    def fetch(config: CrawlConfig) -> list[Paper]:
        # Log in on first use: a month with nothing due never touches the
        # rate-limited login.
        nonlocal client
        if client is None:
            client = create_openreview_client(username=args.username, password=args.password)
        return OpenReviewAPIClient(config, client).fetch_papers()

    outcomes = recrawl_rolling(conf_ids, CONFIGS_DIR, DATA_DIR, fetch)
    print(format_summary(outcomes))
    if args.report:
        args.report.write_text(results_to_json(outcomes), encoding="utf-8")
    # Held and failed venues keep their file and go to the monthly issue; they
    # do not fail the run (ppr/rolling.py says why).


def cmd_validate(args: argparse.Namespace) -> None:
    from ppr.validate import validate_conference

    results = []
    for conf_id in args.conferences:
        logger.info("Validating %s...", conf_id)
        result = validate_conference(conf_id, tolerance=args.tolerance)
        results.append(result)

    # Print results table
    print(f"\n{'Conference':<28} {'Scraped':>8} {'DBLP':>8} {'Status':<10} {'Message'}")
    print("-" * 80)
    for r in results:
        scraped_str = str(r.scraped) if r.scraped else "-"
        dblp_str = str(r.dblp) if r.dblp else "-"
        print(f"{r.conf_id:<28} {scraped_str:>8} {dblp_str:>8} {r.status:<10} {r.message}")

    failures = [r for r in results if r.status == "FAIL"]
    if failures:
        print(f"\n{len(failures)} conference(s) FAILED validation.")
        raise SystemExit(1)


def cmd_discover(args: argparse.Namespace) -> None:
    from datetime import date

    from ppr.discover import (
        discover,
        format_discover_table,
        known_conference_ids,
        results_to_json,
        stale_empty,
    )
    from ppr.venues import load_registry

    registry = load_registry()
    if args.venue:
        # A prefix that matches nothing would silently narrow the sweep to zero
        # venues and report "no new lists ready to register" -- a typo reading
        # as good news. Name the offenders instead.
        unknown = sorted(set(args.venue) - set(registry))
        if unknown:
            raise SystemExit(
                f"Unknown venue prefix(es): {', '.join(unknown)}. "
                f"Known prefixes: {', '.join(sorted(registry))}"
            )
        registry = {k: v for k, v in registry.items() if k in args.venue}

    # OpenReview refuses anonymous venueid queries, so probe those venues only
    # when credentials exist. Without them the sweep still covers the rest --
    # five unprobed venues must not read as "nothing new".
    or_client = None
    if args.username and args.password:
        try:
            or_client = create_openreview_client(
                username=args.username, password=args.password
            )
        except Exception as exc:
            logger.warning("OpenReview login failed (%s); those venues will be skipped", exc)
    else:
        logger.warning("No OpenReview credentials; those venues will be reported unreachable")

    today = date.today()
    results = discover(
        registry, known_conference_ids(), today.year, openreview_client=or_client
    )
    stale = stale_empty(results, registry, today.month, today.year)
    if args.json:
        print(results_to_json(results, stale=stale))
    else:
        print(format_discover_table(results))
        if stale:
            print(
                "\nPast their usual announce month but still parsing 0 papers "
                "(possible broken selector): "
                + ", ".join(r.conf_id for r in stale)
            )


def cmd_autoregister(args: argparse.Namespace) -> None:
    import json

    from ppr import autoregister as ar
    from ppr.validate import validate_conference
    from ppr.venues import load_registry

    rows = json.loads(args.discover_json.read_text(encoding="utf-8"))["results"]
    root = CONFIGS_DIR.parent
    client = None

    def openreview():
        nonlocal client
        if client is None:  # one login, and only if an OpenReview venue needs it
            client = create_openreview_client(username=args.username, password=args.password)
        return client

    outcomes = ar.autoregister(
        rows, load_registry(), ar.Workspace(root),
        crawl=ar.default_crawl(openreview),
        validate=lambda conf_id: validate_conference(conf_id).status,
        commit=ar.git_commit(root) if args.commit else ar.no_commit,
        openreview=openreview,
    )
    args.report.write_text(ar.outcomes_to_json(outcomes), encoding="utf-8")
    for o in outcomes:
        print(f"{o.conf_id:<24} {o.status:<11} {o.count:>6}/{o.expected:<6} {o.reason}")


def _read_json(path: Path | None):
    import json

    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # A partial report from a failed run must not stop the issue decision.
        logger.warning("Ignoring unreadable JSON %s (%s)", path, exc)
        return None


def cmd_report(args: argparse.Namespace) -> None:
    import json
    from datetime import date

    from ppr.report import decide_issue, update_state

    if args.report_command == "state":
        state = _read_json(args.state) or {}
        enrich = _read_json(args.enrich) or {"results": []}
        args.state.write_text(json.dumps(update_state(state, enrich["results"]), indent=2),
                              encoding="utf-8")
        return
    action = decide_issue(
        discover=_read_json(args.discover), register=_read_json(args.register),
        enrich=_read_json(args.enrich), state=_read_json(args.state),
        awards=_read_json(args.awards), rolling=_read_json(args.rolling),
        pipeline_result=args.pipeline_result, run_url=args.run_url,
        today=date.today().isoformat(),
    )
    args.out.write_text(json.dumps(action, indent=2), encoding="utf-8")


def cmd_release(args: argparse.Namespace) -> None:
    from datetime import date

    from ppr.release import gh, publish, render_notes

    notes = render_notes(args.base_tag, _read_json(args.register), _read_json(args.enrich),
                         DATA_DIR, args.run_url)
    tag = publish(DATA_DIR, args.base_tag, notes, date.today().isoformat(), gh,
                  zip_path=DATA_DIR.parent / "data.zip", dry_run=args.dry_run)
    print(tag)


def cmd_search(args: argparse.Namespace) -> None:
    import json
    import sqlite3
    import sys

    from ppr.search import cites, find, lookup
    from ppr.search.index import NoData, open_index

    try:
        con = open_index(DATA_DIR, SEARCH_INDEX)
    except NoData as exc:
        raise SystemExit(str(exc))
    except (sqlite3.Error, OSError) as exc:
        raise SystemExit(f"search index build failed: {exc}")

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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "crawl": cmd_crawl,
        "enrich": cmd_enrich,
        "awards": cmd_awards,
        "rolling": cmd_rolling,
        "validate": cmd_validate,
        "discover": cmd_discover,
        "autoregister": cmd_autoregister,
        "report": cmd_report,
        "release": cmd_release,
        "search": cmd_search,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
