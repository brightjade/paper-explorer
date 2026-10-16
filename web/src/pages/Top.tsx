import { useSearchParams } from "react-router-dom";
import { useTop } from "../hooks/useTop";
import { PaperRow } from "../components/PaperRow";
import { RELATIVE_TOOLTIP } from "../format";
import type { TopSort } from "../types";
import "./Top.css";

const SORTS: { id: TopSort; label: string }[] = [
  { id: "relative", label: "Age-adjusted" },
  { id: "citations", label: "Citations" },
];

export function Top() {
  const { data, error } = useTop();
  const [params, setParams] = useSearchParams();

  if (error) return <div className="loading">Error: {error}</div>;
  if (!data) return <div className="loading">Loading top papers...</div>;

  // Unknown or stale query values (?year=2019, ?cat=se) fall back to the defaults.
  const yearParam = params.get("year") ?? "all";
  const year = data.years.includes(yearParam) ? yearParam : "all";
  const catParam = params.get("cat") ?? "all";
  const cat = (data.categories as string[]).includes(catParam) ? catParam : "all";
  const sort: TopSort = params.get("sort") === "citations" ? "citations" : "relative";

  const update = (key: string, value: string, fallback: string) => {
    const next = new URLSearchParams(params);
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const ids = data.lists[year]?.[cat]?.[sort] ?? [];

  return (
    <div className="top-page">
      <h2 className="page-title">Top 100</h2>
      <p className="page-subtitle">
        The most cited papers across every conference here.{" "}
        <span className="top-help" title={RELATIVE_TOOLTIP}>
          Age-adjusted
        </span>{" "}
        compares each paper with papers first made public in the same quarter, so new papers rank
        fairly against old ones.
      </p>

      <div className="top-controls">
        <div className="top-chip-row" role="group" aria-label="Year">
          {["all", ...data.years].map((y) => (
            <button
              key={y}
              className={`top-chip ${y === year ? "active" : ""}`}
              onClick={() => update("year", y, "all")}
            >
              {y === "all" ? "All years" : y}
            </button>
          ))}
        </div>
        <div className="top-chip-row" role="group" aria-label="Field">
          {["all", ...data.categories].map((c) => (
            <button
              key={c}
              className={`top-chip ${c === cat ? "active" : ""}`}
              onClick={() => update("cat", c, "all")}
            >
              {c === "all" ? "All fields" : c}
            </button>
          ))}
        </div>
        <div className="top-chip-row" role="group" aria-label="Sort">
          {SORTS.map((s) => (
            <button
              key={s.id}
              className={`top-chip ${s.id === sort ? "active" : ""}`}
              onClick={() => update("sort", s.id, "relative")}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="top-table-header">
        <span className="col-rank">#</span>
        <span>Paper</span>
        <span className="col-badges">Venue · Type</span>
        <span className="col-citations">Citations</span>
      </div>

      <div className="top-list">
        {ids.map((index, i) => {
          const paper = data.papers[index];
          return (
            <PaperRow
              key={index}
              paper={paper}
              rank={i + 1}
              conference={{ id: paper.conference_id, venue: paper.venue, year: paper.year }}
              emphasis={sort}
            />
          );
        })}
        {ids.length === 0 && (
          <div className="loading">No papers with citation data for this selection.</div>
        )}
      </div>
    </div>
  );
}
