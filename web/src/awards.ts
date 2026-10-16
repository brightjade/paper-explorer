import type { AwardKind, Paper } from "./types";

export interface AwardChip {
  label: string;
  kind: AwardKind;
  count: number;
}

const ORDER: AwardKind[] = ["award", "honorable", "candidate", "artifact", "test_of_time"];

/** One chip per award label on these papers, in kind order, each counting its papers. */
export function awardChips(papers: Paper[]): AwardChip[] {
  const byLabel = new Map<string, AwardChip>();
  for (const paper of papers) {
    for (const award of paper.awards ?? []) {
      const chip = byLabel.get(award.label) ?? { label: award.label, kind: award.kind, count: 0 };
      chip.count += 1;
      byLabel.set(award.label, chip);
    }
  }
  return [...byLabel.values()].sort(
    (a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind) || a.label.localeCompare(b.label),
  );
}
