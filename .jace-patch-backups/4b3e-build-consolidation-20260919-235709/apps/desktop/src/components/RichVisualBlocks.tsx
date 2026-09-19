import { useMemo, useState } from "react";

export interface ChartSeries {
  name: string;
  values: number[];
}

export interface ChartSpec {
  type?: "bar" | "line";
  title?: string;
  labels: string[];
  series: ChartSeries[];
}

interface ArtifactSpec {
  title: string;
  type?: string;
  description?: string;
  filename?: string;
  url?: string;
  content?: string;
}

const CHART_WIDTH = 720;
const CHART_HEIGHT = 290;
const CHART_LEFT = 54;
const CHART_RIGHT = 22;
const CHART_TOP = 28;
const CHART_BOTTOM = 54;

function safeNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const normalized = trimmed
    .replace(/[£$€¥,%]/g, "")
    .replace(/,/g, "")
    .trim();

  if (!normalized) return null;

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function compactNumber(value: number) {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  if (absolute >= 100) return value.toFixed(0);
  if (absolute >= 10) return value.toFixed(1).replace(/\.0$/, "");
  return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function normalizeChartSpec(value: unknown): ChartSpec | null {
  if (!value || typeof value !== "object") return null;

  const raw = value as Record<string, unknown>;
  const labels = Array.isArray(raw.labels)
    ? raw.labels.map((item) => String(item))
    : [];

  if (labels.length === 0) return null;

  const requestedType = raw.type === "line" ? "line" : "bar";
  const title = typeof raw.title === "string" ? raw.title : undefined;

  if (Array.isArray(raw.series)) {
    const series = raw.series
      .map((item, index): ChartSeries | null => {
        if (!item || typeof item !== "object") return null;
        const entry = item as Record<string, unknown>;
        if (!Array.isArray(entry.values)) return null;

        const values = entry.values.map((candidate) => Number(candidate));
        if (
          values.length !== labels.length ||
          values.some((candidate) => !Number.isFinite(candidate))
        ) {
          return null;
        }

        return {
          name:
            typeof entry.name === "string"
              ? entry.name
              : `Series ${index + 1}`,
          values,
        };
      })
      .filter((item): item is ChartSeries => item !== null);

    if (series.length > 0) {
      return {
        type: requestedType,
        title,
        labels,
        series,
      };
    }
  }

  if (Array.isArray(raw.values)) {
    const values = raw.values.map((candidate) => Number(candidate));
    if (
      values.length === labels.length &&
      values.every((candidate) => Number.isFinite(candidate))
    ) {
      return {
        type: requestedType,
        title,
        labels,
        series: [
          {
            name:
              typeof raw.name === "string"
                ? raw.name
                : title || "Values",
            values,
          },
        ],
      };
    }
  }

  return null;
}

export function chartSpecFromTable(
  header: string[],
  rows: string[][],
): ChartSpec | null {
  if (header.length < 2 || rows.length < 2) return null;

  const labels = rows.map((row) => row[0]?.trim() ?? "");
  if (labels.some((label) => !label)) return null;

  const series: ChartSeries[] = [];

  for (let column = 1; column < header.length; column += 1) {
    const values = rows.map((row) => safeNumber(row[column] ?? ""));
    if (values.some((value) => value == null)) continue;

    series.push({
      name: header[column]?.trim() || `Series ${column}`,
      values: values as number[],
    });
  }

  if (series.length === 0) return null;

  return {
    type: "bar",
    labels,
    series: series.slice(0, 5),
  };
}

function chartBounds(spec: ChartSpec) {
  const values = spec.series.flatMap((series) => series.values);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const span = maximum - minimum || 1;

  return {
    minimum,
    maximum,
    span,
  };
}

function seriesClass(index: number) {
  return `rich-chart-series rich-chart-series-${index % 5}`;
}

function RichChartSvg({
  spec,
  type,
}: {
  spec: ChartSpec;
  type: "bar" | "line";
}) {
  const { minimum, maximum, span } = chartBounds(spec);
  const plotWidth = CHART_WIDTH - CHART_LEFT - CHART_RIGHT;
  const plotHeight = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM;
  const categoryWidth = plotWidth / Math.max(spec.labels.length, 1);

  function xFor(index: number) {
    return CHART_LEFT + categoryWidth * index + categoryWidth / 2;
  }

  function yFor(value: number) {
    return CHART_TOP + ((maximum - value) / span) * plotHeight;
  }

  const zeroY = yFor(0);
  const ticks = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const value = maximum - span * ratio;
    return {
      value,
      y: CHART_TOP + plotHeight * ratio,
    };
  });

  return (
    <svg
      className="rich-chart-svg"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={spec.title || "Data chart"}
    >
      {ticks.map((tick) => (
        <g key={tick.y}>
          <line
            className="rich-chart-grid"
            x1={CHART_LEFT}
            x2={CHART_WIDTH - CHART_RIGHT}
            y1={tick.y}
            y2={tick.y}
          />
          <text
            className="rich-chart-axis-label"
            x={CHART_LEFT - 9}
            y={tick.y + 4}
            textAnchor="end"
          >
            {compactNumber(tick.value)}
          </text>
        </g>
      ))}

      <line
        className="rich-chart-axis"
        x1={CHART_LEFT}
        x2={CHART_WIDTH - CHART_RIGHT}
        y1={zeroY}
        y2={zeroY}
      />

      {type === "bar" &&
        spec.series.map((series, seriesIndex) => {
          const available = categoryWidth * 0.72;
          const barWidth = Math.max(
            4,
            available / Math.max(spec.series.length, 1),
          );

          return series.values.map((value, valueIndex) => {
            const valueY = yFor(value);
            const x =
              xFor(valueIndex) -
              available / 2 +
              seriesIndex * barWidth;
            const y = Math.min(valueY, zeroY);
            const height = Math.max(1, Math.abs(zeroY - valueY));

            return (
              <rect
                key={`${series.name}-${valueIndex}`}
                className={seriesClass(seriesIndex)}
                x={x}
                y={y}
                width={Math.max(2, barWidth - 3)}
                height={height}
                rx={3}
              >
                <title>
                  {series.name}: {value}
                </title>
              </rect>
            );
          });
        })}

      {type === "line" &&
        spec.series.map((series, seriesIndex) => {
          const points = series.values
            .map((value, valueIndex) => `${xFor(valueIndex)},${yFor(value)}`)
            .join(" ");

          return (
            <g key={series.name}>
              <polyline
                className={`${seriesClass(seriesIndex)} rich-chart-line`}
                points={points}
              />
              {series.values.map((value, valueIndex) => (
                <circle
                  key={`${series.name}-${valueIndex}`}
                  className={seriesClass(seriesIndex)}
                  cx={xFor(valueIndex)}
                  cy={yFor(value)}
                  r={4}
                >
                  <title>
                    {series.name}: {value}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}

      {spec.labels.map((label, index) => (
        <text
          className="rich-chart-x-label"
          key={`${label}-${index}`}
          x={xFor(index)}
          y={CHART_HEIGHT - 22}
          textAnchor="middle"
        >
          {label.length > 14 ? `${label.slice(0, 12)}…` : label}
        </text>
      ))}
    </svg>
  );
}

export function RichChart({
  spec,
  initialType,
}: {
  spec: ChartSpec;
  initialType?: "bar" | "line";
}) {
  const [type, setType] = useState<"bar" | "line">(
    initialType || spec.type || "bar",
  );

  return (
    <div className="rich-chart-card">
      <div className="rich-chart-header">
        <div>
          <span>Chart</span>
          {spec.title && <strong>{spec.title}</strong>}
        </div>
        <div className="rich-chart-switcher" aria-label="Chart type">
          <button
            type="button"
            className={type === "bar" ? "active" : ""}
            onClick={() => setType("bar")}
          >
            Bars
          </button>
          <button
            type="button"
            className={type === "line" ? "active" : ""}
            onClick={() => setType("line")}
          >
            Line
          </button>
        </div>
      </div>

      <div className="rich-chart-canvas">
        <RichChartSvg spec={spec} type={type} />
      </div>

      {spec.series.length > 1 && (
        <div className="rich-chart-legend">
          {spec.series.map((series, index) => (
            <span key={series.name}>
              <i className={seriesClass(index)} />
              {series.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function RichChartBlock({ code }: { code: string }) {
  const parsed = useMemo(() => {
    try {
      return normalizeChartSpec(JSON.parse(code));
    } catch {
      return null;
    }
  }, [code]);

  if (!parsed) {
    return (
      <div className="rich-artifact-error">
        <strong>Chart data could not be rendered</strong>
        <span>
          Use JSON with labels plus either values or a series array.
        </span>
      </div>
    );
  }

  return <RichChart spec={parsed} />;
}

export function RichTableBlock({
  header,
  rows,
  renderCell,
}: {
  header: string[];
  rows: string[][];
  renderCell: (value: string, key: string) => React.ReactNode;
}) {
  const chart = useMemo(
    () => chartSpecFromTable(header, rows),
    [header, rows],
  );
  const [mode, setMode] = useState<"table" | "chart">("table");

  return (
    <div className="rich-table-card">
      {chart && (
        <div className="rich-table-toolbar">
          <span>Data view</span>
          <div>
            <button
              type="button"
              className={mode === "table" ? "active" : ""}
              onClick={() => setMode("table")}
            >
              Table
            </button>
            <button
              type="button"
              className={mode === "chart" ? "active" : ""}
              onClick={() => setMode("chart")}
            >
              Chart
            </button>
          </div>
        </div>
      )}

      {mode === "chart" && chart ? (
        <RichChart spec={chart} />
      ) : (
        <div className="rich-table-wrap">
          <table className="rich-table">
            <thead>
              <tr>
                {header.map((cell, index) => (
                  <th key={`head-${index}`}>
                    {renderCell(cell, `head-${index}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`row-${rowIndex}-${cellIndex}`}>
                      {renderCell(
                        cell,
                        `row-${rowIndex}-${cellIndex}`,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function safeArtifactUrl(value: unknown) {
  if (typeof value !== "string") return null;

  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol)
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

export function RichArtifactBlock({ code }: { code: string }) {
  const artifact = useMemo<ArtifactSpec | null>(() => {
    try {
      const parsed = JSON.parse(code) as Record<string, unknown>;
      if (!parsed || typeof parsed !== "object") return null;
      if (typeof parsed.title !== "string" || !parsed.title.trim()) return null;

      return {
        title: parsed.title,
        type:
          typeof parsed.type === "string"
            ? parsed.type
            : "artifact",
        description:
          typeof parsed.description === "string"
            ? parsed.description
            : undefined,
        filename:
          typeof parsed.filename === "string"
            ? parsed.filename
            : undefined,
        url: safeArtifactUrl(parsed.url) ?? undefined,
        content:
          typeof parsed.content === "string"
            ? parsed.content
            : undefined,
      };
    } catch {
      return null;
    }
  }, [code]);

  if (!artifact) {
    return (
      <div className="rich-artifact-error">
        <strong>Artifact data could not be rendered</strong>
        <span>
          Artifact blocks must be valid JSON and include a title.
        </span>
      </div>
    );
  }

  return (
    <article className="rich-artifact-card">
      <div className="rich-artifact-icon" aria-hidden="true">
        ◫
      </div>

      <div className="rich-artifact-copy">
        <span className="rich-artifact-type">
          {artifact.type || "artifact"}
        </span>
        <strong>{artifact.title}</strong>

        {artifact.description && (
          <p>{artifact.description}</p>
        )}

        {artifact.filename && (
          <code>{artifact.filename}</code>
        )}

        {artifact.content && (
          <details className="rich-artifact-preview">
            <summary>Preview</summary>
            <pre>{artifact.content}</pre>
          </details>
        )}
      </div>

      {artifact.url && (
        <a
          className="rich-artifact-open"
          href={artifact.url}
          target="_blank"
          rel="noreferrer"
        >
          Open ↗
        </a>
      )}
    </article>
  );
}
