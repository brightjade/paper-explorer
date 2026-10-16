import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useManifest } from "../hooks/useManifest";
import type { ConferenceMeta } from "../types";
import "./Home.css";

type Category = "ML" | "NLP" | "CV" | "Robotics" | "SE" | "Others";

const VENUE_CATEGORIES: Record<string, Category> = {
  ICLR: "ML",
  NeurIPS: "ML",
  ICML: "ML",
  AAAI: "ML",
  IJCAI: "ML",
  COLM: "NLP",
  EMNLP: "NLP",
  ACL: "NLP",
  NAACL: "NLP",
  EACL: "NLP",
  COLING: "NLP",
  CVPR: "CV",
  ICCV: "CV",
  ECCV: "CV",
  WACV: "CV",
  ICRA: "Robotics",
  IROS: "Robotics",
  RSS: "Robotics",
  CoRL: "Robotics",
  ICSE: "SE",
  FSE: "SE",
  ASE: "SE",
  ISSTA: "SE",
};

const ALL_CATEGORIES: Category[] = ["ML", "NLP", "CV", "Robotics", "SE", "Others"];

function getCategory(venue: string): Category {
  return VENUE_CATEGORIES[venue] ?? "Others";
}

export function Home() {
  const { data: manifest, error } = useManifest();
  const [activeCategories, setActiveCategories] = useState<Set<Category>>(
    new Set(ALL_CATEGORIES)
  );

  const toggleCategory = (cat: Category) => {
    setActiveCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        if (next.size > 1) next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  };

  const filtered = useMemo(() => {
    if (!manifest) return [];
    return manifest.filter((c) => activeCategories.has(getCategory(c.venue)));
  }, [manifest, activeCategories]);

  const table = useMemo(() => {
    const years = [...new Set(filtered.map((c) => c.year))].sort((a, b) => b - a);
    const cells = new Map<string, ConferenceMeta>();
    for (const c of filtered) cells.set(`${c.venue}|${c.year}`, c);
    const order = Object.keys(VENUE_CATEGORIES);
    const rank = (v: string) => (order.includes(v) ? order.indexOf(v) : order.length);
    const groups = ALL_CATEGORIES.map((cat) => {
      const venues = [...new Set(filtered.filter((c) => getCategory(c.venue) === cat).map((c) => c.venue))]
        .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
      return [cat, venues] as const;
    }).filter(([, venues]) => venues.length > 0);
    return { years, cells, groups };
  }, [filtered]);

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
        {ALL_CATEGORIES.map((cat) => (
          <button
            key={cat}
            className={`category-btn ${activeCategories.has(cat) ? "active" : ""}`}
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
