import argparse
import asyncio
import logging
import os
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
from ppr.models import Paper, write_papers
from ppr.s2_client import S2Client
from ppr.venues import REGISTRY_STEM

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _available_conferences() -> list[str]:
    from ppr.discover import known_conference_ids

    return sorted(known_conference_ids())


def all_conference_ids(data_dir: Path) -> list[str]:
    """Every conference directory under data/, sorted."""
    if not data_dir.exists():
        return []
    return sorted(d.name for d in data_dir.iterdir() if d.is_dir())


def _save_papers(papers: list[Paper], conf_id: str) -> Path:
    # Shares `write_papers`' refusal with the OpenReview save path: a scraper
    # whose selector a site redesign outgrew returns `[]` just as an API error
    # does, and must not silently erase the last good crawl either.
    return write_papers(papers, DATA_DIR / conf_id / "papers.jsonl")


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
        description="Crawl accepted papers from OpenReview conferences.",
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
        help="Enrich every conference under data/.",
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
    for name in ("discover", "register", "enrich", "state"):
        issue_parser.add_argument(f"--{name}", type=Path, default=None)
    issue_parser.add_argument("--pipeline-result", required=True)
    issue_parser.add_argument("--run-url", required=True)
    issue_parser.add_argument("--out", type=Path, required=True)

    return parser


def cmd_crawl(args: argparse.Namespace) -> None:
    conf_ids = args.conferences

    # Split into scraped vs OpenReview conferences
    scraped = [c for c in conf_ids if c in SCRAPERS]
    openreview = [
        c for c in conf_ids
        if c not in SCRAPERS and c != REGISTRY_STEM and (CONFIGS_DIR / f"{c}.yaml").exists()
    ]
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
        configs = [CrawlConfig.from_yaml(CONFIGS_DIR / f"{c}.yaml") for c in openreview]
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
    results = asyncio.run(
        enrich_all(
            conf_ids,
            client,
            DATA_DIR,
            full=args.full,
            deadline=deadline,
        )
    )
    print(format_enrich_summary(results))
    if args.report:
        # Before the exit below: the notify job needs this most when it failed.
        args.report.write_text(results_to_json(results), encoding="utf-8")

    # `ppr enrich --all` feeds ./build.sh and a data release, so a crashed
    # conference must not read as success to the calling shell. Guard skips are
    # a correct outcome and stay exit-0.
    failures = [r for r in results if r.status == "failed"]
    if failures:
        raise SystemExit(1)


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
        pipeline_result=args.pipeline_result, run_url=args.run_url,
        today=date.today().isoformat(),
    )
    args.out.write_text(json.dumps(action, indent=2), encoding="utf-8")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "crawl": cmd_crawl,
        "enrich": cmd_enrich,
        "validate": cmd_validate,
        "discover": cmd_discover,
        "autoregister": cmd_autoregister,
        "report": cmd_report,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
