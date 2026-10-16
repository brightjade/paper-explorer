import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useConferenceData } from "../hooks/useConferenceData";
import { useManifest } from "../hooks/useManifest";
import { useRevealOnScroll } from "../hooks/useRevealOnScroll";
import { MetricsLegend } from "../components/MetricsLegend";
import { PaperRow } from "../components/PaperRow";
import { SearchInput } from "../components/SearchInput";
import { AwardSummary } from "../components/AwardSummary";
import { awardChips } from "../awards";
import type { Paper } from "../types";
import "./Conference.css";

type SortKey = "citations" | "title";

// Fields scripts/build_data.py adds for the page (see scripts/impact.py). The
// download is dataset content, so they are dropped from it.
const BUILD_FIELDS = ["relative_citations"] as const;

function datasetRecord(paper: Paper): Record<string, unknown> {
  const record: Record<string, unknown> = { ...paper };
  for (const field of BUILD_FIELDS) delete record[field];
  return record;
}

export function Conference() {
  const { id } = useParams<{ id: string }>();
  const { data: papers, error } = useConferenceData(id);
  const { data: manifest } = useManifest();
  const [search, setSearch] = useState("");
  const [trackFilter, setTrackFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<SortKey>("citations");
  const [awardFilter, setAwardFilter] = useState<string | null>(null);
  const [awardFilterFor, setAwardFilterFor] = useState(id);
  // The page stays mounted across /conference/:id routes, and award labels repeat
  // across venues and years: a filter belongs to the conference it was picked on.
  if (id !== awardFilterFor) {
    setAwardFilterFor(id);
    setAwardFilter(null);
  }

  const meta = manifest?.find((c) => c.id === id);
  const chips = useMemo(() => awardChips(papers ?? []), [papers]);
  const downloadJsonl = () => {
    if (!papers || !id) return;
    // Built from the JSON the page already loaded, minus the build-time fields:
    // the same records data/ holds, one per line, without shipping them twice.
    const body = papers.map((p) => JSON.stringify(datasetRecord(p))).join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([body], { type: "application/x-ndjson" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${id}.jsonl`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const filtered = useMemo(() => {
    if (!papers) return [];
    let result = papers;

    if (trackFilter !== "all") {
      result = result.filter((p) => p.selection === trackFilter);
    }

    if (awardFilter) {
      result = result.filter((p) => p.awards?.some((a) => a.label === awardFilter));
    }

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          p.authors.some((a) => a.toLowerCase().includes(q)) ||
          (p.keywords ?? []).some((k) => k.toLowerCase().includes(q))
      );
    }

    result = [...result].sort((a, b) => {
      if (sortBy === "citations") {
        return (b.citation_count ?? -1) - (a.citation_count ?? -1);
      }
      return a.title.localeCompare(b.title);
    });

    return result;
  }, [papers, search, trackFilter, sortBy, awardFilter]);

  // Thousands of rows take seconds to mount; render them in batches as the
  // reader scrolls. Search, filters and the download still cover every paper.
  const listKey = [id, search, trackFilter, sortBy, awardFilter].join("\u0000");
  const { shown, sentinelRef, showMore } = useRevealOnScroll(filtered.length, listKey);

  if (error) return <div className="loading">Error: {error}</div>;
  if (!papers) return <div className="loading">Loading papers...</div>;

  const tracks = [...new Set(papers.map((p) => p.selection))].filter(Boolean).sort();

  return (
    <div className="conference-page">
      <h2 className="page-title">{meta?.venue ?? id} {meta?.year ?? ""}</h2>
      <p className="page-subtitle">
        {papers.length.toLocaleString()} papers
        {filtered.length !== papers.length && ` · ${filtered.length.toLocaleString()} shown`}
        {" · "}
        <button
          type="button"
          className="download-link"
          onClick={downloadJsonl}
          title="Download paper data (.jsonl)"
        >
          <svg className="download-icon" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 12l-4-4h2.5V3h3v5H12L8 12z" />
            <path d="M3 13h10v1H3z" />
          </svg>
          Download
        </button>
      </p>
      <MetricsLegend />

      <AwardSummary
        chips={chips}
        testOfTime={meta?.test_of_time}
        active={awardFilter}
        onSelect={setAwardFilter}
      />

      <div className="conference-controls">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search titles, authors, keywords..."
        />
        <div className="conference-filters">
          <select
            className="track-select"
            value={trackFilter}
            onChange={(e) => setTrackFilter(e.target.value)}
          >
            <option value="all">All types</option>
            {tracks.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <select
            className="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortKey)}
          >
            <option value="citations">Sort by citations</option>
            <option value="title">Sort by title</option>
          </select>
        </div>
      </div>

      <div className="paper-table-header">
        <span className="col-rank">#</span>
        <span className="col-title">Paper</span>
        <span className="col-track">Type</span>
        <span className="col-citations">Citations</span>
      </div>

      <div className="paper-list">
        {filtered.slice(0, shown).map((paper, i) => (
          <PaperRow key={paper.title} paper={paper} rank={i + 1} />
        ))}
        {shown < filtered.length && (
          <div ref={sentinelRef} className="paper-list-more">
            <button type="button" onClick={showMore}>
              Show more ({(filtered.length - shown).toLocaleString()} remaining)
            </button>
          </div>
        )}
        {filtered.length === 0 && (
          <div className="loading">No papers match your search.</div>
        )}
      </div>
    </div>
  );
}
