export const RELATIVE_TOOLTIP =
  "Age-adjusted: citations relative to the average paper in this dataset first made public in the same quarter.";

export const INFLUENTIAL_TOOLTIP =
  "Citations where the citing paper builds substantially on this one, per Semantic Scholar.";

/** 281× avg from 10 up, 2.4× avg below. */
export function formatRelative(value: number): string {
  return value >= 10 ? `${Math.round(value)}× avg` : `${value.toFixed(1)}× avg`;
}
