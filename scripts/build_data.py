"""Build static JSON data files from JSONL paper outputs for the web app."""

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scripts.ngrams import build_ngram_data

VENUE_NAMES = {
    "iclr": "ICLR",
    "neurips": "NeurIPS",
    "icml": "ICML",
    "colm": "COLM",
    "emnlp": "EMNLP",
    "acl": "ACL",
    "naacl": "NAACL",
    "aaai": "AAAI",
    "usenix_security": "USENIX Security",
    "icse": "ICSE",
    "fse": "FSE",
    "ase": "ASE",
    "issta": "ISSTA",
    "cvpr": "CVPR",
    "iccv": "ICCV",
    "eccv": "ECCV",
    "wacv": "WACV",
    "icra": "ICRA",
    "iros": "IROS",
    "rss": "RSS",
    "ijcai": "IJCAI",
    "corl": "CoRL",
    "eacl": "EACL",
    "coling": "COLING",
}


def parse_conference_id(conf_id: str) -> tuple[str, int]:
    """Extract venue display name and year from conference ID like 'iclr_2025'."""
    year = int(conf_id.rsplit("_", 1)[1])
    prefix = conf_id.rsplit("_", 1)[0]
    venue = VENUE_NAMES.get(prefix, prefix.upper())
    return venue, year


def load_papers(conf_dir: Path) -> list[dict]:
    """Load papers from a conference directory, preferring enriched data."""
    enriched = conf_dir / "papers_enriched.jsonl"
    plain = conf_dir / "papers.jsonl"
    source = enriched if enriched.exists() else plain
    if not source.exists():
        return []
    papers = []
    with open(source) as f:
        for line in f:
            line = line.strip()
            if line:
                papers.append(json.loads(line))
    return papers


def build_manifest_entry(conf_id: str, papers: list[dict]) -> dict:
    """Build a manifest entry for one conference."""
    venue, year = parse_conference_id(conf_id)
    has_citations = any("citation_count" in p for p in papers)
    tracks = sorted({p.get("selection", "") for p in papers} - {""})

    top_papers = []
    total_citations = 0
    if has_citations:
        sorted_papers = sorted(
            [p for p in papers if "citation_count" in p],
            key=lambda p: p["citation_count"],
            reverse=True,
        )
        total_citations = sum(p["citation_count"] for p in sorted_papers)
        top_papers = [
            {"title": p["title"], "citation_count": p["citation_count"]}
            for p in sorted_papers[:3]
        ]

    return {
        "id": conf_id,
        "venue": venue,
        "year": year,
        "paper_count": len(papers),
        "has_citations": has_citations,
        "total_citations": total_citations,
        "tracks": tracks,
        "top_papers": top_papers,
    }


def build_author_index(all_papers: dict[str, list[dict]]) -> list[dict]:
    """Build author index across all conferences."""
    author_data: dict[str, dict] = defaultdict(
        lambda: {"conferences": set(), "paper_count": 0, "total_citations": 0}
    )
    for conf_id, papers in all_papers.items():
        for paper in papers:
            for author in paper.get("authors", []):
                entry = author_data[author]
                entry["conferences"].add(conf_id)
                entry["paper_count"] += 1
                entry["total_citations"] += paper.get("citation_count", 0)

    return sorted(
        [
            {
                "name": name,
                "conferences": sorted(data["conferences"]),
                "paper_count": data["paper_count"],
                "total_citations": data["total_citations"],
            }
            for name, data in author_data.items()
        ],
        key=lambda a: a["total_citations"],
        reverse=True,
    )


def build_trends(all_papers: dict[str, list[dict]]) -> dict:
    """Build comprehensive trend data: overview, topics, impact, composition."""
    venue_counts_by_year: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    citation_counts_by_year: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    citation_lists_by_year: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    influential_by_year: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    track_breakdown_by_year: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    top_papers_by_year: dict[str, list[dict]] = defaultdict(list)

    for conf_id, papers in all_papers.items():
        venue, year = parse_conference_id(conf_id)
        year_str = str(year)
        venue_counts_by_year[year_str][venue] += len(papers)

        for paper in papers:
            cite = paper.get("citation_count", 0)
            citation_counts_by_year[year_str][venue] += cite
            if paper.get("citation_count") is not None:
                citation_lists_by_year[year_str][venue].append(cite)
            influential_by_year[year_str][venue] += paper.get("influential_citation_count") or 0

            selection = paper.get("selection", "")
            if selection:
                track_breakdown_by_year[year_str][venue][selection] += 1

            if paper.get("citation_count") is not None:
                top_papers_by_year[year_str].append({
                    "title": paper["title"],
                    "venue": venue,
                    "citation_count": paper["citation_count"],
                    "influential_citation_count": paper.get("influential_citation_count") or 0,
                    "conference_id": conf_id,
                })

    years_sorted = sorted(venue_counts_by_year.keys())

    # --- Overview ---
    growth_pct_by_year = {}
    for i in range(1, len(years_sorted)):
        prev_year, curr_year = years_sorted[i - 1], years_sorted[i]
        growth = {}
        for venue, count in venue_counts_by_year[curr_year].items():
            prev_count = venue_counts_by_year[prev_year].get(venue)
            if prev_count and prev_count > 0:
                growth[venue] = round((count - prev_count) / prev_count * 100, 1)
        if growth:
            growth_pct_by_year[curr_year] = growth

    overview = {
        "venue_counts_by_year": {y: dict(v) for y, v in venue_counts_by_year.items()},
        "citation_counts_by_year": {y: dict(v) for y, v in citation_counts_by_year.items()},
        "growth_pct_by_year": growth_pct_by_year,
    }

    # --- Topics ---
    topics = build_ngram_data(all_papers, parse_conference_id)

    # --- Impact ---
    citation_stats_by_year = {}
    avg_citations_by_year = {}
    influential_ratio_by_year = {}

    for year_str in years_sorted:
        stats = {}
        avg = {}
        ratios = {}
        for venue, cites in citation_lists_by_year[year_str].items():
            if len(cites) < 2:
                continue
            cites_sorted = sorted(cites)
            q = statistics.quantiles(cites_sorted, n=4)
            q1, median, q3 = q[0], q[1], q[2]
            iqr = q3 - q1
            upper_fence = q3 + 1.5 * iqr
            outliers = [c for c in cites_sorted if c > upper_fence][:20]
            stats[venue] = {
                "min": cites_sorted[0],
                "q1": q1,
                "median": median,
                "q3": q3,
                "max": cites_sorted[-1],
                "outliers": outliers,
            }
            avg[venue] = median

        for venue in citation_counts_by_year[year_str]:
            total = citation_counts_by_year[year_str][venue]
            inf = influential_by_year[year_str].get(venue, 0)
            if total > 0:
                ratios[venue] = round(inf / total, 4)

        if stats:
            citation_stats_by_year[year_str] = stats
        if avg:
            avg_citations_by_year[year_str] = avg
        if ratios:
            influential_ratio_by_year[year_str] = ratios

    # Sort top papers per year, take top 20
    top_papers_final = {}
    for year_str, papers_list in top_papers_by_year.items():
        papers_list.sort(key=lambda p: p["citation_count"], reverse=True)
        top_papers_final[year_str] = papers_list[:20]

    impact = {
        "citation_stats_by_year": citation_stats_by_year,
        "avg_citations_by_year": avg_citations_by_year,
        "top_papers_by_year": top_papers_final,
        "influential_ratio_by_year": influential_ratio_by_year,
    }

    # --- Composition ---
    venue_counts_all_years: dict[str, dict[str, int]] = defaultdict(dict)
    for year_str, venues in venue_counts_by_year.items():
        for venue, count in venues.items():
            venue_counts_all_years[venue][year_str] = count

    composition = {
        "track_breakdown_by_year": {
            y: {v: dict(c) for v, c in venues.items()}
            for y, venues in track_breakdown_by_year.items()
        },
        "venue_counts_all_years": dict(venue_counts_all_years),
        "growth_rates_by_year": growth_pct_by_year,
    }

    return {
        "overview": overview,
        "topics": topics,
        "impact": impact,
        "composition": composition,
    }


def read_citation_updated(data_dir: Path) -> str | None:
    """Read the citation update date from data/citation_updated.txt."""
    path = data_dir / "citation_updated.txt"
    if path.exists():
        return path.read_text().strip()
    return None


def build_all(data_dir: Path, out_dir: Path) -> None:
    """Build all static JSON files from JSONL data."""
    out_dir.mkdir(parents=True, exist_ok=True)

    all_papers: dict[str, list[dict]] = {}
    conferences: list[dict] = []

    for conf_dir in sorted(data_dir.iterdir()):
        if not conf_dir.is_dir():
            continue
        conf_id = conf_dir.name
        papers = load_papers(conf_dir)
        if not papers:
            continue
        all_papers[conf_id] = papers
        conferences.append(build_manifest_entry(conf_id, papers))

        # Write per-conference JSON file
        with open(out_dir / f"{conf_id}.json", "w") as f:
            json.dump(papers, f, ensure_ascii=False)

    # Sort conferences by year desc, then venue name
    conferences.sort(key=lambda m: (-m["year"], m["venue"]))

    manifest = {"conferences": conferences}
    citation_updated = read_citation_updated(data_dir)
    if citation_updated:
        manifest["citation_updated"] = citation_updated

    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(out_dir / "authors.json", "w") as f:
        json.dump(build_author_index(all_papers), f, ensure_ascii=False)

    with open(out_dir / "trends.json", "w") as f:
        json.dump(build_trends(all_papers), f, ensure_ascii=False, indent=2)

    print(f"Built {len(conferences)} conferences -> {out_dir}")


if __name__ == "__main__":
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("web/public/data")
    build_all(data_dir, out_dir)
