// Display order of the category chips. Matches CATEGORIES in
// scripts/build_data.py, which assigns each conference its category.
export const CATEGORIES = [
  "ML",
  "NLP",
  "CV",
  "Robotics",
  "SE",
  "Security",
  "Others",
] as const;

export type Category = (typeof CATEGORIES)[number];
