import "./MetricsLegend.css";

interface MetricsLegendProps {
  /** Whether the page's rows show influential citations. */
  influential?: boolean;
}

/** What the numbers in a paper row mean; collapsed until the reader asks. */
export function MetricsLegend({ influential = true }: MetricsLegendProps) {
  return (
    <details className="metrics-legend">
      <summary>What do these numbers mean?</summary>
      <dl>
        <dt className="legend-citations">1,234</dt>
        <dd>Citations, from Semantic Scholar, refreshed every month.</dd>
        <dt className="legend-relative">2.4× avg</dt>
        <dd>
          Age-adjusted citations: 2.4 times the average paper in this dataset first made public in
          the same quarter. Older papers have had longer to collect citations, so this compares each
          paper with papers of its own age. Most papers sit below 1×, because a few highly cited ones
          pull the average up.
        </dd>
        {influential && (
          <>
            <dt className="legend-influential">12 influential</dt>
            <dd>
              Citations where the citing paper builds substantially on this one, as judged by{" "}
              <a
                href="https://www.semanticscholar.org/faq#influential-citations"
                target="_blank"
                rel="noopener noreferrer"
              >
                Semantic Scholar
              </a>
              .
            </dd>
          </>
        )}
      </dl>
    </details>
  );
}
