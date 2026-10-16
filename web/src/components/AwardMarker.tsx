import type { PaperAward } from "../types";
import "./AwardMarker.css";

export function TrophyIcon() {
  return (
    <svg className="award-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M4 2h8v3a4 4 0 0 1-8 0V2z" fill="currentColor" />
      <path
        d="M4 3.5H2.5v1A2.5 2.5 0 0 0 4.6 7M12 3.5h1.5v1A2.5 2.5 0 0 1 11.4 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <rect x="7.25" y="9" width="1.5" height="3" fill="currentColor" />
      <rect x="5" y="12" width="6" height="2" rx="0.5" fill="currentColor" />
    </svg>
  );
}

/** A row's highest award (build_data orders a paper's awards by kind) and how many more it holds. */
export function AwardMarker({ awards }: { awards?: PaperAward[] }) {
  if (!awards || awards.length === 0) return null;
  const [top, ...rest] = awards;
  return (
    <span
      className={`award-marker award-${top.kind}`}
      title={awards.map((a) => a.label).join(" · ")}
    >
      <TrophyIcon />
      {top.label}
      {rest.length > 0 && <span className="award-more">+{rest.length}</span>}
    </span>
  );
}

/** Every award a paper holds, for its expanded details. */
export function AwardList({ awards }: { awards: PaperAward[] }) {
  return (
    <div className="award-list">
      {awards.map((a) => (
        <span key={a.label} className={`award-marker award-${a.kind}`}>
          <TrophyIcon />
          {a.label}
        </span>
      ))}
    </div>
  );
}
