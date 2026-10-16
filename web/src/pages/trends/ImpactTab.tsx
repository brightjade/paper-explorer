import { useMemo, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { TrendsData, CitationStats } from "../../types";
import { VENUE_COLORS, formatNumber } from "./constants";

interface ImpactTabProps {
  trends: TrendsData;
  selectedYear: string;
  years: string[];
}

function BoxPlotChart({
  stats,
}: {
  stats: Record<string, CitationStats>;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });

  const venues = useMemo(
    () =>
      Object.entries(stats)
        .sort((a, b) => b[1].median - a[1].median)
        .map(([v]) => v),
    [stats]
  );

  if (venues.length === 0) return null;

  const chartWidth = Math.max(600, venues.length * 60);
  const chartHeight = 350;
  const marginLeft = 50;
  const marginRight = 20;
  const marginTop = 20;
  const marginBottom = 60;
  const plotWidth = chartWidth - marginLeft - marginRight;
  const plotHeight = chartHeight - marginTop - marginBottom;

  // Scale Y-axis to upper fences so outliers don't flatten the boxes
  const maxVal = Math.max(
    ...venues.map((v) => {
      const s = stats[v];
      const iqr = s.q3 - s.q1;
      return s.q3 + 1.5 * iqr;
    })
  );
  const yMax = maxVal * 1.1; // 10% padding
  const scale = (val: number) =>
    plotHeight - (Math.min(val, yMax) / yMax) * plotHeight + marginTop;
  const barWidth = Math.min(40, plotWidth / venues.length - 8);

  // Y-axis ticks
  const tickCount = 5;
  const tickStep = yMax / tickCount;
  const ticks = Array.from({ length: tickCount + 1 }, (_, i) =>
    Math.round(i * tickStep)
  );

  return (
    <div
      className="box-plot-container"
      style={{ position: "relative" }}
      onMouseMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        setMouse({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      }}
    >
      <svg width={chartWidth} height={chartHeight}>
        {/* Y-axis */}
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={marginLeft}
              y1={scale(tick)}
              x2={chartWidth - marginRight}
              y2={scale(tick)}
              stroke="var(--border)"
              strokeDasharray="2,2"
            />
            <text
              x={marginLeft - 8}
              y={scale(tick) + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--text-muted)"
            >
              {formatNumber(tick)}
            </text>
          </g>
        ))}

        {/* Box plots */}
        {venues.map((venue, i) => {
          const s = stats[venue];
          const cx = marginLeft + (i + 0.5) * (plotWidth / venues.length);
          const halfBar = barWidth / 2;

          return (
            <g
              key={venue}
              onMouseEnter={() => setHovered(venue)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: "pointer" }}
            >
              {/* Hit area for hover */}
              <rect
                x={cx - halfBar - 4}
                y={marginTop}
                width={barWidth + 8}
                height={plotHeight}
                fill="transparent"
              />
              {/* Whisker line (min to max, excluding outliers above fence) */}
              <line
                x1={cx}
                y1={scale(s.min)}
                x2={cx}
                y2={scale(s.q3 + 1.5 * (s.q3 - s.q1))}
                stroke={VENUE_COLORS[venue] ?? "#888"}
                strokeWidth={1.5}
              />
              {/* Box (q1 to q3) */}
              <rect
                x={cx - halfBar}
                y={scale(s.q3)}
                width={barWidth}
                height={Math.max(1, scale(s.q1) - scale(s.q3))}
                fill={VENUE_COLORS[venue] ?? "#888"}
                opacity={hovered === venue ? 0.5 : 0.3}
                stroke={VENUE_COLORS[venue] ?? "#888"}
                strokeWidth={1.5}
                rx={2}
              />
              {/* Median line */}
              <line
                x1={cx - halfBar}
                y1={scale(s.median)}
                x2={cx + halfBar}
                y2={scale(s.median)}
                stroke={VENUE_COLORS[venue] ?? "#888"}
                strokeWidth={2.5}
              />
              {/* Min whisker cap */}
              <line
                x1={cx - halfBar / 2}
                y1={scale(s.min)}
                x2={cx + halfBar / 2}
                y2={scale(s.min)}
                stroke={VENUE_COLORS[venue] ?? "#888"}
                strokeWidth={1.5}
              />
              {/* Outlier dots */}
              {s.outliers.slice(0, 5).map((o, j) => (
                <circle
                  key={j}
                  cx={cx}
                  cy={scale(o)}
                  r={3}
                  fill={VENUE_COLORS[venue] ?? "#888"}
                  opacity={0.5}
                />
              ))}
              {/* Venue label */}
              <text
                x={cx}
                y={chartHeight - marginBottom + 16}
                textAnchor="end"
                fontSize={11}
                fontWeight={600}
                fill="var(--text-primary)"
                transform={`rotate(-45, ${cx}, ${chartHeight - marginBottom + 16})`}
              >
                {venue}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hovered && (
        <div
          className="box-plot-tooltip"
          style={{
            position: "absolute",
            left: mouse.x + 12,
            top: mouse.y - 120,
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "0.5rem 0.75rem",
            fontSize: "0.8rem",
            lineHeight: 1.6,
            pointerEvents: "none",
            zIndex: 10,
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            whiteSpace: "nowrap",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 2, color: VENUE_COLORS[hovered] ?? "#888" }}>
            {hovered}
          </div>
          <div>Max: {formatNumber(stats[hovered].max)}</div>
          <div>Q3: {formatNumber(stats[hovered].q3)}</div>
          <div>Median: {formatNumber(stats[hovered].median)}</div>
          <div>Q1: {formatNumber(stats[hovered].q1)}</div>
          <div>Min: {formatNumber(stats[hovered].min)}</div>
        </div>
      )}
    </div>
  );
}

export function ImpactTab({ trends, selectedYear }: ImpactTabProps) {
  const impact = trends.impact;

  const citationStats = impact.citation_stats_by_year[selectedYear] ?? {};
  const medianCitations = impact.avg_citations_by_year[selectedYear] ?? {};
  const influentialRatio =
    impact.influential_ratio_by_year[selectedYear] ?? {};

  const medianData = useMemo(
    () =>
      Object.entries(medianCitations)
        .sort((a, b) => b[1] - a[1])
        .map(([venue, value]) => ({ venue, value })),
    [medianCitations]
  );

  const ratioData = useMemo(
    () =>
      Object.entries(influentialRatio)
        .sort((a, b) => b[1] - a[1])
        .map(([venue, value]) => ({ venue, value: +(value * 100).toFixed(2) })),
    [influentialRatio]
  );

  const hasData = Object.keys(citationStats).length > 0;

  if (!hasData) {
    return (
      <div className="trends-placeholder">
        No citation data available for {selectedYear}
      </div>
    );
  }

  return (
    <>
      {/* Box Plots */}
      <div className="trends-section">
        <h3>Citation Distribution by Venue</h3>
        <BoxPlotChart stats={citationStats} />
      </div>

      {/* Median Citations */}
      {medianData.length > 0 && (
        <div className="trends-section">
          <h3>Median Citations per Paper</h3>
          <div className="chart-container">
            <ResponsiveContainer
              width="100%"
              height={Math.max(300, medianData.length * 40)}
            >
              <BarChart
                data={medianData}
                layout="vertical"
                margin={{ left: 10, right: 30 }}
              >
                <XAxis type="number" tickFormatter={formatNumber} />
                <YAxis
                  dataKey="venue"
                  type="category"
                  width={120}
                  tick={{ fontSize: 13, fontWeight: 600 }}
                />
                <Tooltip
                  formatter={(value: any) => [Number(value).toLocaleString(), "Median citations"]}
                  contentStyle={{
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    fontSize: "0.85rem",
                  }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={24}>
                  {medianData.map((entry) => (
                    <Cell
                      key={entry.venue}
                      fill={VENUE_COLORS[entry.venue] ?? "#888"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Influential Citation Ratio */}
      {ratioData.length > 0 && (
        <div className="trends-section">
          <h3>Influential Citation Ratio</h3>
          <p className="section-description">
            An influential citation is one where the cited work significantly impacted the citing paper,
            as determined by{" "}
            <a
              href="https://www.semanticscholar.org/faq#influential-citations"
              target="_blank"
              rel="noopener noreferrer"
            >
              Semantic Scholar's algorithm
            </a>
            . This ratio shows the percentage of each venue's citations that are influential.
          </p>
          <div className="chart-container">
            <ResponsiveContainer
              width="100%"
              height={Math.max(300, ratioData.length * 40)}
            >
              <BarChart
                data={ratioData}
                layout="vertical"
                margin={{ left: 10, right: 30 }}
              >
                <XAxis
                  type="number"
                  tickFormatter={(v: number) => `${v}%`}
                />
                <YAxis
                  dataKey="venue"
                  type="category"
                  width={120}
                  tick={{ fontSize: 13, fontWeight: 600 }}
                />
                <Tooltip
                  formatter={(value: any) => [
                    `${Number(value).toFixed(2)}%`,
                    "Influential ratio",
                  ]}
                  contentStyle={{
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    fontSize: "0.85rem",
                  }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={24}>
                  {ratioData.map((entry) => (
                    <Cell
                      key={entry.venue}
                      fill={VENUE_COLORS[entry.venue] ?? "#888"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </>
  );
}
