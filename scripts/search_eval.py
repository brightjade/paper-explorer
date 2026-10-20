"""Measure /survey's retrieval against gold sets in eval/gold/<topic>.json.

    uv run python -m scripts.search_eval gold TOPIC SURVEY_ID      # draft a gold file from a survey's references
    uv run python -m scripts.search_eval retrieval [--k 50] [--no-cites]
    uv run python -m scripts.search_eval score TOPIC --run outputs/<run>/   # a new-skill run's judged.tsv
    uv run python -m scripts.search_eval score TOPIC --list refs.txt        # ids or titles, e.g. an old report's references

A gold file holds a topic, the survey it came from, the topic's criteria, a frozen
list of queries (single terms, as `ppr search find` takes them), the gold papers
(the survey's references in the dataset that fit the topic) and the excluded
background references. `gold` drafts one with every in-dataset reference under
"gold"; moving background ones to "excluded" is a reviewed step.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from ppr.layout import DATA_DIR, ROOT, search_index_path
from ppr.s2_client import S2Client
from ppr.search import cites, find
from ppr.search.index import open_index
from ppr.search.lookup import lookup

GOLD_DIR = ROOT / "eval" / "gold"
BYTES_PER_TOKEN = 4
FOUND_VERDICTS = ("high", "medium")


def recall(found: set[str], gold: set[str]) -> float:
    return len(found & gold) / len(gold) if gold else 0.0


def _gold(path: Path) -> tuple[dict, set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, {g["pid"] for g in data["gold"]}


def grep_candidates(con, queries: list[str]) -> dict[str, int]:
    """pid -> record size, for papers whose text contains a query (case-insensitive substring), as a grep finds them."""
    needles = [q.rstrip("*").strip().lower() for q in queries]
    out = {}
    for row in con.execute("SELECT * FROM papers"):
        text = f"{row['title']} {row['abstract']} {row['tldr']} {row['keywords']}".lower()
        if any(n in text for n in needles):
            out[row["pid"]] = len(json.dumps(find.row_dict(row), ensure_ascii=False))
    return out


def find_candidates(con, queries: list[str], k: int) -> dict[str, int]:
    """pid -> shown size, for the union of each query's top k."""
    out = {}
    for query in queries:
        _, rows = find.search(con, find.build_match([query]), limit=k)
        for row in rows:
            out.setdefault(row["pid"], len(find.format_line(row)) + len(find.snippet(row)))
    return out


def _cited_pids(con, client: S2Client, seeds: set[str]) -> set[str]:
    if not seeds:
        return set()
    report = cites.chase(con, client, sorted(seeds), "both", min_links=1, limit=10**6)
    return {row["pid"] for x in report.inside for row in x.rows}


def _stats(candidates: dict[str, int], gold: set[str]) -> dict:
    return {"recall": recall(set(candidates), gold), "candidates": len(candidates),
            "tokens": sum(candidates.values()) // BYTES_PER_TOKEN}


def evaluate(con, gold_file: Path, k: int, client: S2Client | None) -> dict:
    data, gold = _gold(gold_file)
    grep = grep_candidates(con, data["queries"])
    found = find_candidates(con, data["queries"], k)
    result = {"topic": data["topic"], "gold": len(gold), "grep": _stats(grep, gold), "find": _stats(found, gold)}
    if client is not None:
        both = set(found) | _cited_pids(con, client, set(found) & gold)
        result["find+cites"] = {"recall": recall(both, gold), "candidates": len(both)}
    return result


def format_table(results: list[dict]) -> str:
    lines = ["| topic | gold | grep recall | grep cands | grep tokens | find recall | find cands | find tokens "
             "| +cites recall | +cites cands |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        c = r.get("find+cites", {})
        lines.append(
            f"| {r['topic']} | {r['gold']} | {r['grep']['recall']:.2f} | {r['grep']['candidates']} | "
            f"{r['grep']['tokens']} | {r['find']['recall']:.2f} | {r['find']['candidates']} | "
            f"{r['find']['tokens']} | {c.get('recall', float('nan')):.2f} | {c.get('candidates', '-')} |")
    return "\n".join(lines)


def draft_gold(con, client: S2Client, topic: str, survey_id: str) -> dict:
    async def fetch():
        async with httpx.AsyncClient(timeout=120) as http:
            return await client.get_batch(http, [survey_id], fields="title,references.corpusId,references.title")

    survey = asyncio.run(fetch())[0]
    if not survey:
        raise SystemExit(f"Semantic Scholar has no record for {survey_id}")
    refs = [r for r in survey.get("references") or [] if r and r.get("corpusId")]
    ids = sorted({r["corpusId"] for r in refs})
    gold = []
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for row in con.execute(f"SELECT pid, title, conf_id FROM papers WHERE corpus_id IN "
                               f"({', '.join('?' * len(chunk))})", chunk):
            gold.append({"pid": row["pid"], "title": row["title"], "conf_id": row["conf_id"]})
    gold.sort(key=lambda g: g["pid"])
    return {"topic": topic, "survey": {"id": survey_id, "title": survey.get("title")}, "criteria": [],
            "queries": [], "references_total": len(refs), "references_in_dataset": len(gold),
            "gold": gold, "excluded": []}


def score_run(con, gold_file: Path, run_dir: Path) -> dict:
    """Recall of a run's high + medium papers, and why each missed gold paper was missed."""
    data, gold = _gold(gold_file)
    judged = {}
    for line in (run_dir / "judged.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] != "pid":
            judged[parts[0].strip()] = parts[1].strip()
    found = {pid for pid, verdict in judged.items() if verdict in FOUND_VERDICTS}
    misses = {"never_candidate": 0, "judged_out": 0, "no_abstract": 0}
    for pid in sorted(gold - found):
        row = con.execute("SELECT abstract, tldr FROM papers WHERE pid = ?", (pid,)).fetchone()
        if row is not None and not row["abstract"] and not row["tldr"]:
            misses["no_abstract"] += 1
        elif pid in judged:
            misses["judged_out"] += 1
        else:
            misses["never_candidate"] += 1
    return {"topic": data["topic"], "gold": len(gold), "found": len(found), "recall": recall(found, gold),
            "misses": misses, "found_not_gold": sorted(found - gold)}


def score_list(con, gold_file: Path, list_file: Path) -> dict:
    """Recall of a list of ids or titles (an older report's references), grounded with lookup."""
    data, gold = _gold(gold_file)
    found, unmatched = set(), 0
    for line in list_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        result = lookup(con, line)
        if result.rows:
            found.update(row["pid"] for row in result.rows)
        else:
            unmatched += 1
    return {"topic": data["topic"], "gold": len(gold), "found": len(found), "recall": recall(found, gold),
            "unmatched": unmatched}


def main(argv: list[str] | None = None) -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(prog="search_eval", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gold_p = sub.add_parser("gold")
    gold_p.add_argument("topic")
    gold_p.add_argument("survey_id", help="A Semantic Scholar id: ARXIV:…, DOI:…, CorpusId:…")
    gold_p.add_argument("--force", action="store_true")
    retrieval_p = sub.add_parser("retrieval")
    retrieval_p.add_argument("--k", type=int, default=50)
    retrieval_p.add_argument("--no-cites", action="store_true")
    score_p = sub.add_parser("score")
    score_p.add_argument("topic")
    group = score_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", type=Path)
    group.add_argument("--list", type=Path)
    args = parser.parse_args(argv)

    con = open_index(DATA_DIR, search_index_path())
    client = S2Client(api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or None)
    if args.command == "gold":
        out = GOLD_DIR / f"{args.topic}.json"
        if out.exists() and not args.force:
            raise SystemExit(f"{out} exists; --force to overwrite")
        draft = draft_gold(con, client, args.topic, args.survey_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{out}: {draft['references_in_dataset']} of {draft['references_total']} references in the dataset")
    elif args.command == "retrieval":
        files = sorted(GOLD_DIR.glob("*.json"))
        results = [evaluate(con, f, args.k, None if args.no_cites else client) for f in files
                   if json.loads(f.read_text(encoding="utf-8")).get("queries")]
        print(format_table(results))
    else:
        gold = GOLD_DIR / f"{args.topic}.json"
        score = score_run(con, gold, args.run) if args.run else score_list(con, gold, args.list)
        json.dump(score, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
