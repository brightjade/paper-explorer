import { useState } from "react";
import { Link } from "react-router-dom";
import type { Paper } from "../types";
import { TrackBadge } from "./TrackBadge";
import { AwardList, AwardMarker } from "./AwardMarker";
import { VENUE_COLORS } from "../pages/trends/constants";
import { INFLUENTIAL_TOOLTIP, RELATIVE_TOOLTIP, formatRelative } from "../format";
import "./PaperRow.css";

interface PaperRowProps {
  paper: Paper;
  rank: number;
  /** Shown as a venue chip linking to the conference (Top 100 rows). */
  conference?: { id: string; venue: string; year: number };
  /** Which number the list is sorted by, drawn larger. */
  emphasis?: "citations" | "relative";
}

export function PaperRow({ paper, rank, conference, emphasis = "citations" }: PaperRowProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`paper-row ${expanded ? "expanded" : ""}`}>
      <div className="paper-row-main" onClick={() => setExpanded(!expanded)}>
        <span className="paper-rank">{rank}</span>
        <div className="paper-info">
          <div className="paper-title">
            {paper.title}
            <AwardMarker awards={paper.awards} />
          </div>
          <div className="paper-authors">
            {(paper.authors ?? []).map((a, i) => (
              <span key={i}>
                {i > 0 && ", "}
                <Link
                  to={`/author/${encodeURIComponent(a)}`}
                  className="author-link"
                  onClick={(e) => e.stopPropagation()}
                >
                  {a}
                </Link>
              </span>
            ))}
          </div>
        </div>
        <div className="paper-badges">
          {conference && (
            <Link
              to={`/conference/${conference.id}`}
              className="venue-chip"
              style={{ "--venue-color": VENUE_COLORS[conference.venue] ?? "#6b7280" } as React.CSSProperties}
              onClick={(e) => e.stopPropagation()}
            >
              {conference.venue} {conference.year}
            </Link>
          )}
          <TrackBadge track={paper.selection} />
        </div>
        <div className="paper-citations-col">
          <span className={`paper-citations ${emphasis === "relative" ? "deemphasized" : ""}`}>
            {paper.citation_count != null
              ? paper.citation_count.toLocaleString()
              : "\u2014"}
          </span>
          {paper.relative_citations != null && (
            <span
              className={`paper-relative ${emphasis === "relative" ? "emphasized" : ""}`}
              title={RELATIVE_TOOLTIP}
            >
              {formatRelative(paper.relative_citations)}
            </span>
          )}
          {paper.influential_citation_count != null && paper.influential_citation_count > 0 && (
            <span className="paper-influential" title={INFLUENTIAL_TOOLTIP}>
              {paper.influential_citation_count} influential
            </span>
          )}
        </div>
      </div>
      {expanded && (
        <div className="paper-details">
          {paper.awards && paper.awards.length > 0 && <AwardList awards={paper.awards} />}
          {paper.tldr && (
            <p className="paper-tldr">{paper.tldr}</p>
          )}
          {paper.abstract && <p className="paper-abstract">{paper.abstract}</p>}

          <div className="paper-meta-row">
            {paper.publication_date && (
              <span className="paper-meta-item">Published: {paper.publication_date}</span>
            )}
            {paper.reference_count != null && (
              <span className="paper-meta-item">{paper.reference_count} references</span>
            )}
          </div>

          {((paper.keywords && paper.keywords.length > 0) || (paper.fields_of_study && paper.fields_of_study.length > 0)) && (
            <div className="paper-keywords">
              {paper.fields_of_study?.map((f, i) => (
                <span key={`fos-${i}`} className="field-tag">
                  {f}
                </span>
              ))}
              {paper.keywords?.map((kw, i) => (
                <span key={i} className="keyword-tag">
                  {kw}
                </span>
              ))}
            </div>
          )}

          <div className="paper-links">
            {paper.link && (
              <a href={paper.link} target="_blank" rel="noopener noreferrer">
                PDF &rarr;
              </a>
            )}
            {paper.open_access_pdf && paper.open_access_pdf !== paper.link && (
              <a href={paper.open_access_pdf} target="_blank" rel="noopener noreferrer">
                Open Access PDF &rarr;
              </a>
            )}
            {paper.forum_id && (
              <a
                href={`https://openreview.net/forum?id=${paper.forum_id}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                OpenReview &rarr;
              </a>
            )}
            {paper.external_ids?.ArXiv && (
              <a
                href={`https://arxiv.org/abs/${paper.external_ids.ArXiv}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                arXiv &rarr;
              </a>
            )}
            {paper.external_ids?.DOI && (
              <a
                href={`https://doi.org/${paper.external_ids.DOI}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                DOI &rarr;
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
