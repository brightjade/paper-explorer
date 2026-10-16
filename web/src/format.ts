export const RELATIVE_TOOLTIP =
  "Citations relative to the average paper in this dataset first made public in the same quarter.";

/** ×281 from 10 up, ×2.4 below. */
export function formatRelative(value: number): string {
  return value >= 10 ? `×${Math.round(value)}` : `×${value.toFixed(1)}`;
}
