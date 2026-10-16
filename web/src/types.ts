import type { Category } from "./categories";

export interface Paper {
  title: string;
  authors: string[];
  selection: string;
  keywords?: string[];
  abstract?: string;
  link?: string;
  forum_id?: string;
  citation_count?: number;
  relative_citations?: number;
  influential_citation_count?: number;
  reference_count?: number;
  tldr?: string;
  publication_date?: string;
  fields_of_study?: string[];
  open_access_pdf?: string;
  external_ids?: Record<string, string>;
}

export interface ConferenceMeta {
  id: string;
  venue: string;
  year: number;
  category: Category;
  paper_count: number;
  has_citations: boolean;
  total_citations: number;
  tracks: string[];
  top_papers: {
    title: string;
    citation_count: number;
  }[];
}

export interface AuthorSummary {
  name: string;
  conferences: string[];
  paper_count: number;
  total_citations: number;
}

export interface NgramEntry {
  ngram: string;
  count: number;
}

export interface RisingFallingEntry {
  ngram: string;
  count: number;
  delta: number;
  pct_change: number;
}

export interface CitationStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  outliers: number[];
}

export interface TrendsData {
  overview: {
    venue_counts_by_year: Record<string, Record<string, number>>;
    citation_counts_by_year: Record<string, Record<string, number>>;
    growth_pct_by_year: Record<string, Record<string, number>>;
  };
  topics: {
    top_ngrams_by_year: Record<string, NgramEntry[]>;
    rising_falling_by_year: Record<
      string,
      { rising: RisingFallingEntry[]; falling: RisingFallingEntry[] }
    >;
    ngram_trends: Record<string, Record<string, number>>;
    venue_ngram_matrix_by_year: Record<
      string,
      Record<string, Record<string, number>>
    >;
  };
  impact: {
    citation_stats_by_year: Record<string, Record<string, CitationStats>>;
    avg_citations_by_year: Record<string, Record<string, number>>;
    influential_ratio_by_year: Record<string, Record<string, number>>;
  };
  composition: {
    track_breakdown_by_year: Record<
      string,
      Record<string, Record<string, number>>
    >;
    venue_counts_all_years: Record<string, Record<string, number>>;
    growth_rates_by_year: Record<string, Record<string, number>>;
  };
}

export type TopSort = "relative" | "citations";

/** A paper in top.json's pool: enough to render a PaperRow, plus its venue. */
export interface TopEntry extends Paper {
  venue: string;
  year: number;
  conference_id: string;
  citation_count: number;
  relative_citations: number;
  first_public: string;
}

export interface TopData {
  categories: Category[];
  years: string[];
  papers: TopEntry[];
  /** period ("all" | year) -> category ("all" | Category) -> sort -> indices into papers */
  lists: Record<string, Record<string, Record<TopSort, number[]>>>;
}
