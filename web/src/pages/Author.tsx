import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useAuthors } from "../hooks/useAuthors";
import { useManifest } from "../hooks/useManifest";
import { TrackBadge } from "../components/TrackBadge";
import type { Paper } from "../types";
import { RELATIVE_TOOLTIP, formatRelative } from "../format";
import "./Author.css";

export function Author() {
  const { name } = useParams<{ name: string }>();
  const decodedName = name ? decodeURIComponent(name) : "";
  const { data: authors, error } = useAuthors();
  const { data: manifest } = useManifest();

  const author = authors?.find((a) => a.name === decodedName);

  const [papersByConf, setPapersByConf] = useState<Record<string, Paper[]>>({});
  const [loadingConfs, setLoadingConfs] = useState(false);

  const BASE = import.meta.env.BASE_URL;

  useEffect(() => {
    if (!author) return;
    setLoadingConfs(true);
    Promise.all(
      author.conferences.map((confId) =>
        fetch(`${BASE}data/${confId}.json`)
          .then((r) => r.json())
          .then((papers: Paper[]) => [confId, papers] as const)
      )
    ).then((results) => {
      const map: Record<string, Paper[]> = {};
      for (const [confId, papers] of results) {
        map[confId] = papers.filter((p) =>
          p.authors.some((a) => a === decodedName)
        );
      }
      setPapersByConf(map);
      setLoadingConfs(false);
    });
  }, [author, decodedName, BASE]);

  const confIds = useMemo(() => {
    if (!author || !manifest) return [];
    return author.conferences
      .map((id) => {
        const m = manifest.find((c) => c.id === id);
        return { id, venue: m?.venue ?? id, year: m?.year ?? 0 };
      })
      .sort((a, b) => b.year - a.year || a.venue.localeCompare(b.venue));
  }, [author, manifest]);

  if (error) return <div className="loading">Error: {error}</div>;
  if (!authors) return <div className="loading">Loading...</div>;
  if (!author) return <div className="loading">Author not found: {decodedName}</div>;

  return (
    <div className="author-page">
      <h2 className="page-title">{decodedName}</h2>
      <div className="author-stats">
        <div className="author-stat">
          <span className="stat-value">{author.paper_count}</span>
          <span className="stat-label">papers</span>
        </div>
        <div className="author-stat">
          <span className="stat-value">{author.total_citations.toLocaleString()}</span>
          <span className="stat-label">citations</span>
        </div>
        <div className="author-stat">
          <span className="stat-value">{author.conferences.length}</span>
          <span className="stat-label">venues</span>
        </div>
      </div>

      {loadingConfs && <div className="loading">Loading papers...</div>}

      {confIds.map(({ id, venue, year }) => {
        const papers = papersByConf[id];
        if (!papers || papers.length === 0) return null;
        return (
          <section key={id} className="author-conf-section">
            <h3 className="author-conf-heading">
              {venue} {year}
            </h3>
            <div className="author-papers">
              {papers.map((p) => (
                <div key={p.title} className="author-paper-row">
                  <div className="author-paper-title">
                    {p.link ? (
                      <a href={p.link} target="_blank" rel="noopener noreferrer">
                        {p.title}
                      </a>
                    ) : (
                      p.title
                    )}
                  </div>
                  <TrackBadge track={p.selection} />
                  <span className="author-paper-citations">
                    {p.citation_count != null
                      ? p.citation_count.toLocaleString()
                      : "\u2014"}
                    {p.relative_citations != null && (
                      <span className="author-paper-relative" title={RELATIVE_TOOLTIP}>
                        {formatRelative(p.relative_citations)}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
