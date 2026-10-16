import { useMemo, useState } from "react";
import { useManifest } from "../hooks/useManifest";
import { ConferenceCard } from "../components/ConferenceCard";
import { CATEGORIES, type Category } from "../categories";
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

  if (error) return <div className="loading">Error: {error}</div>;
  if (!manifest) return <div className="loading">Loading conferences...</div>;

  const byYear = new Map<number, typeof filtered>();
  for (const conf of filtered) {
    if (!byYear.has(conf.year)) byYear.set(conf.year, []);
    byYear.get(conf.year)!.push(conf);
  }
  const years = [...byYear.keys()].sort((a, b) => b - a);

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
      {years.map((year) => (
        <section key={year} className="year-section">
          <h3 className="year-heading">{year}</h3>
          <div className="conference-grid">
            {byYear.get(year)!.map((conf) => (
              <ConferenceCard key={conf.id} conf={conf} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
