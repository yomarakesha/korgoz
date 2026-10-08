import { useEffect, useRef, useState } from "react";

import { bucketHour } from "../format";
import type { FlowBucket } from "../types";

const HEIGHT = 220;
const PAD = { top: 12, right: 8, bottom: 28, left: 36 };
const SERIES = [
  { key: "entered", label: "Вошли", className: "series-1" },
  { key: "left", label: "Вышли", className: "series-2" },
] as const;

/** Rounded-up axis maximum and ~4 integer ticks. */
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? rough;
  const ticks: number[] = [];
  for (let value = 0; value < max + step; value += Math.max(1, Math.round(step))) ticks.push(value);
  return ticks;
}

function label(bucket: FlowBucket): string {
  const day = bucket.hour.slice(8, 10) + "." + bucket.hour.slice(5, 7);
  return `${day} ${String(bucketHour(bucket.hour)).padStart(2, "0")}:00`;
}

/** Width of an element, following resizes (fallback for jsdom, which has no layout). */
function useWidth(fallback: number) {
  const ref = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Entries and exits per hour: grouped bars, hover tooltip, legend and a table view. */
export function FlowChart({ buckets, timezone }: { buckets: FlowBucket[]; timezone: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const [box, boxWidth] = useWidth(720);

  // Fill the card; scroll horizontally only when bars would get thinner than ~3 px.
  const width = Math.max(boxWidth, buckets.length * 3 + PAD.left + PAD.right);
  const ticks = niceTicks(Math.max(0, ...buckets.map((b) => Math.max(b.entered, b.left))));
  const top = ticks[ticks.length - 1] ?? 1;
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(buckets.length, 1);
  const barW = Math.max(1, Math.min(14, (slot - 4) / 2));
  const y = (value: number) => PAD.top + plotH - (value / top) * plotH;
  const labelEvery = Math.ceil(buckets.length / 12);
  const active = hover === null ? undefined : buckets[hover];

  return (
    <figure className="chart" ref={box}>
      <div className="chart-head">
        <div className="legend">
          {SERIES.map((s) => (
            <span key={s.key} className="legend-item">
              <span className={`swatch ${s.className}`} aria-hidden="true" /> {s.label}
            </span>
          ))}
          <span className="muted">часовой пояс: {timezone}</span>
        </div>
        <button type="button" className="link-button" onClick={() => setAsTable(!asTable)}>
          {asTable ? "График" : "Таблица"}
        </button>
      </div>

      {asTable ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Час</th>
                <th className="num">Вошли</th>
                <th className="num">Вышли</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.hour}>
                  <td>{label(b)}</td>
                  <td className="num">{b.entered}</td>
                  <td className="num">{b.left}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-scroll">
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label="Входы и выходы по часам"
            onMouseLeave={() => setHover(null)}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line className="grid" x1={PAD.left} x2={width - PAD.right} y1={y(tick)} y2={y(tick)} />
                <text className="axis" x={PAD.left - 6} y={y(tick) + 4} textAnchor="end">
                  {tick}
                </text>
              </g>
            ))}
            {buckets.map((b, i) => {
              const x0 = PAD.left + i * slot + (slot - 2 * barW - 2) / 2;
              return (
                <g key={b.hour}>
                  {SERIES.map((s, k) => {
                    const value = b[s.key];
                    const h = (value / top) * plotH;
                    return value > 0 ? (
                      <rect
                        key={s.key}
                        className={s.className}
                        x={x0 + k * (barW + 2)}
                        y={PAD.top + plotH - h}
                        width={barW}
                        height={h}
                        rx={Math.min(4, barW / 2)}
                      />
                    ) : null;
                  })}
                  {i % labelEvery === 0 && (
                    <text className="axis" x={PAD.left + i * slot + slot / 2} y={HEIGHT - 8} textAnchor="middle">
                      {String(bucketHour(b.hour)).padStart(2, "0")}
                    </text>
                  )}
                  {/* Hit target: the whole column, bigger than the bars. */}
                  <rect
                    data-testid="hit"
                    className={hover === i ? "hit hit-active" : "hit"}
                    x={PAD.left + i * slot}
                    y={PAD.top}
                    width={slot}
                    height={plotH}
                    onMouseEnter={() => setHover(i)}
                  />
                </g>
              );
            })}
            <line className="baseline" x1={PAD.left} x2={width - PAD.right} y1={y(0)} y2={y(0)} />
          </svg>
          {active && hover !== null && (
            <div
              className="tooltip"
              role="status"
              style={{ left: Math.min(PAD.left + hover * slot + slot, width - 150) }}
            >
              <strong>{label(active)}</strong>
              <div>Вошли: {active.entered}</div>
              <div>Вышли: {active.left}</div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
