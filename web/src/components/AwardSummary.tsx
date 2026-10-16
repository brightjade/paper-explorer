import type { AwardChip } from "../awards";
import type { TestOfTimeEntry } from "../types";
import { TrophyIcon } from "./AwardMarker";
import "./AwardSummary.css";

export function AwardSummary({
  chips,
  testOfTime,
  active,
  onSelect,
}: {
  chips: AwardChip[];
  testOfTime?: TestOfTimeEntry[];
  active: string | null;
  onSelect: (label: string | null) => void;
}) {
  if (chips.length === 0 && !testOfTime?.length) return null;
  return (
    <div className="award-summary">
      <span className="award-summary-icon">
        <TrophyIcon />
      </span>
      {chips.map((chip) => (
        <button
          key={chip.label}
          type="button"
          className={`award-chip award-${chip.kind}${active === chip.label ? " active" : ""}`}
          aria-pressed={active === chip.label}
          onClick={() => onSelect(active === chip.label ? null : chip.label)}
        >
          {chip.label}
          <span className="award-chip-count">{chip.count}</span>
        </button>
      ))}
      {testOfTime?.map((t) => (
        <span key={`${t.label}-${t.title}`} className="award-tot">
          {t.label}:{" "}
          {t.url ? (
            <a href={t.url} target="_blank" rel="noopener noreferrer">
              {t.title} ↗
            </a>
          ) : (
            t.title
          )}
        </span>
      ))}
    </div>
  );
}
