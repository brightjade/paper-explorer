import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useManifest } from "../hooks/useManifest";
import { CATEGORIES, type Category } from "../categories";
import type { ConferenceMeta } from "../types";
import "./Home.css";

export function Home() {
  const { data: manifest, error } = useManifest();
  // Categories switched off. Tracking the hidden ones (not the shown ones) keeps
  // categories that have no conference out of the bookkeeping.
  const [hidden, setHidden] = useState<Set<Category>>(new Set());

  const present = useMemo(
    () => CATEGORIES.filter((cat) => manifest?.some((c) => c.category === cat)),
    [manifest]
  );

  const toggleCategory = (cat: Category) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else if (present.filter((c) => !next.has(c)).length > 1) {
        // never hide the last visible category
        next.add(cat);
      }
      return next;
    });
  };

  const filtered = useMemo(() => {
    if (!manifest) return [];
    return manifest.filter((c) => !hidden.has(c.category));
  }, [manifest, hidden]);

  const table = useMemo(() => {
    const years = [...new Set(filtered.map((c) => c.year))].sort((a, b) => b - a);
    const cells = new Map<string, ConferenceMeta>();
    for (const c of filtered) cells.set(`${c.venue}|${c.year}`, c);
    // Within a category, the venues with the most papers across all years come
    // first; categories keep the build's display order.
    const totals = new Map<string, number>();
    for (const c of filtered) totals.set(c.venue, (totals.get(c.venue) ?? 0) + c.paper_count);
    const groups = present
      .filter((cat) => !hidden.has(cat))
      .map((cat) => {
        const venues = [...new Set(filtered.filter((c) => c.category === cat).map((c) => c.venue))]
          .sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0) || a.localeCompare(b));
        return [cat, venues] as const;
      })
      .filter(([, venues]) => venues.length > 0);
    return { years, cells, groups };
  }, [filtered, present, hidden]);

  if (error) return <div className="loading">Error: {error}</div>;
  if (!manifest) return <div className="loading">Loading conferences...</div>;

  return (
    <div className="home">
      <h2 className="page-title">Conferences</h2>
      <p className="page-subtitle">
        {filtered.reduce((sum, c) => sum + c.paper_count, 0).toLocaleString()} papers
        across {filtered.length} conferences
      </p>
      <div className="category-filters">
        {present.map((cat) => (
          <button
            key={cat}
            className={`category-btn ${hidden.has(cat) ? "" : "active"}`}
            onClick={() => toggleCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>
      <div className="venue-table-wrap">
        <table className="venue-table">
          <thead>
            <tr>
              <th className="venue-col" scope="col">Conference</th>
              {table.years.map((y) => (
                <th key={y} scope="col">{y}</th>
              ))}
            </tr>
          </thead>
          {table.groups.map(([cat, venues]) => (
            <tbody key={cat}>
              <tr className="category-row">
                <th className="venue-col" scope="rowgroup">{cat}</th>
                <td colSpan={table.years.length} />
              </tr>
              {venues.map((venue) => (
                <tr key={venue}>
                  <th className="venue-col" scope="row">{venue}</th>
                  {table.years.map((y) => {
                    const conf = table.cells.get(`${venue}|${y}`);
                    return (
                      <td key={y}>
                        {conf && (
                          <Link
                            to={`/conference/${conf.id}`}
                            title={`${venue} ${y}: ${conf.paper_count.toLocaleString()} papers`}
                          >
                            {formatCount(conf.paper_count)}
                          </Link>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}

function formatCount(n: number): string {
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(1)}k`;
}
