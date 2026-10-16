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

// Display order of the venues within each category on the home page: the order
// the field usually names them in. A venue not listed here follows the listed
// ones, alphabetically.
export const VENUE_ORDER: readonly string[] = [
  "NeurIPS", "ICML", "ICLR", "TMLR", "AAAI", "IJCAI",
  "ACL", "EMNLP", "NAACL", "COLM", "EACL", "COLING",
  "CVPR", "ICCV", "ECCV", "WACV",
  "RSS", "CoRL", "ICRA", "IROS",
  "ICSE", "FSE", "ASE", "ISSTA",
  "USENIX Security",
];
