"use client";

import React from "react";

// --- vizcn palette (lib/palette.ts inlined for 21st.dev; canonical registry: https://vibecoding.tech/vizcn) ---
export const CATEGORICAL = [
  "#4E79A7", // blue
  "#F28E2B", // orange
  "#59A14F", // green
  "#B07AA1", // purple
  "#76B7B2", // teal
  "#E15759", // red
  "#EDC948", // yellow
  "#FF9DA7", // pink
  "#9C755F", // brown
  "#BAB0AC", // grey
] as const;

export function seriesColor(i: number): string {
  return CATEGORICAL[((i % CATEGORICAL.length) + CATEGORICAL.length) % CATEGORICAL.length];
}
// --- end palette ---

/**
 * PairedBars — grouped horizontal bars for two measurements per subject.
 *
 * Answers "how do two measurements of the same subjects compare?" in 2
 * seconds: each subject owns exactly two thin bars on one shared 0..max axis.
 * The primary measure is fully saturated; the secondary uses the same entity
 * hue at 55% opacity. Gridlines and a tick rail keep deltas readable across
 * groups. Plain div rendering with serializable props; no client runtime.
 *
 * Props:
 * - groups: {label, color?, a: {label,value,valueLabel?}, b: {...}}[].
 * - max?: shared axis ceiling; defaults to the largest value.
 * - unit?: suffix appended to raw values.
 * - ticks?: axis/grid values; defaults to four equal intervals.
 * - barLabel?: uppercase header over the bar zone.
 */

const MONO = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";

export type PairedBarMeasure = {
  label: string;
  value: number;
  valueLabel?: string;
};

export type PairedBarGroup = {
  label: string;
  color?: string;
  subtitle?: string;
  sample?: string;
  turnsRetired?: number;
  payloadsCompacted?: number;
  a: PairedBarMeasure;
  b: PairedBarMeasure;
};

function GridLines({ ticks, max }: { ticks: number[]; max: number }) {
  return (
    <div aria-hidden className="absolute inset-0 pointer-events-none">
      {ticks
        .filter((tick) => tick > 0 && tick < max)
        .map((tick) => (
          <span
            key={tick}
            className="absolute inset-y-0 border-l border-[var(--vz-grid,#e3e3e3)]"
            style={{ left: `${(tick / max) * 100}%` }}
          />
        ))}
    </div>
  );
}

export function PairedBars({
  groups,
  max,
  unit = "",
  ticks,
  barLabel = "rate",
}: {
  groups: PairedBarGroup[];
  max?: number;
  unit?: string;
  ticks?: number[];
  barLabel?: string;
}) {
  const dataMax = Math.max(...groups.flatMap((group) => [group.a.value, group.b.value]), 1);
  const axisMax = max && max > 0 ? max : dataMax;
  const axisTicks = ticks ?? [0, axisMax / 4, axisMax / 2, (axisMax * 3) / 4, axisMax];
  const pct = (value: number) => Math.max(0, Math.min(100, (value / axisMax) * 100));
  const formatTick = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1));

  return (
    <div className="overflow-x-auto border-y border-[var(--vz-grid,#e2e8f0)] py-5 text-[var(--vz-ink,#090d16)] [font-variant-numeric:tabular-nums]">
      <div className="min-w-[620px]">
        <div
          className="grid grid-cols-[160px_minmax(260px,1fr)_120px] gap-x-4 border-b border-[var(--vz-grid,#e2e8f0)] pb-2 text-[10px] uppercase tracking-[0.1em] text-[var(--vz-muted,#64748b)]"
          style={{ fontFamily: MONO }}
        >
          <span>measurement</span>
          <span>{barLabel}</span>
          <span className="text-right">value</span>
        </div>

        <div className="divide-y divide-[var(--vz-grid,#e2e8f0)]">
          {groups.map((group, groupIndex) => {
            const color = group.color ?? seriesColor(groupIndex);
            return (
              <section key={`${group.label}-${groupIndex}`} className="py-4 first:pt-4 last:pb-2">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-[13px] font-semibold text-[var(--vz-ink,#090d16)]">
                    <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
                    <span>{group.label}</span>
                    {group.sample && (
                      <span className="ml-1 text-[11px] font-normal text-[var(--vz-muted,#64748b)]">
                        ({group.sample})
                      </span>
                    )}
                  </h3>
                  {group.subtitle && (
                    <span className="text-[11px] text-[var(--vz-muted,#64748b)] font-mono">
                      {group.subtitle}
                    </span>
                  )}
                </div>

                <div className="space-y-2">
                  {[group.a, group.b].map((measure, measureIndex) => {
                    const valueLabel = measure.valueLabel ?? `${measure.value}${unit}`;
                    return (
                      <div
                        key={`${measure.label}-${measureIndex}`}
                        className="grid grid-cols-[160px_minmax(260px,1fr)_120px] items-center gap-x-4"
                      >
                        <p
                          className="truncate text-[11px] text-[var(--vz-muted,#64748b)]"
                          style={{ fontFamily: MONO }}
                        >
                          {measure.label}
                        </p>
                        <div
                          className="relative h-[16px] rounded-sm bg-[var(--vz-track,#f1f5f9)] border-y border-[var(--vz-grid,#e2e8f0)]"
                          title={`${group.label} · ${measure.label} · ${valueLabel}`}
                        >
                          <GridLines ticks={axisTicks} max={axisMax} />
                          <div
                            className="absolute inset-y-[2px] left-0 rounded-xs transition-all duration-300"
                            style={{
                              width: `${pct(measure.value)}%`,
                              backgroundColor: color,
                              opacity: measureIndex === 0 ? 1 : 0.55,
                            }}
                          />
                        </div>
                        <p className="text-right text-[11px] font-semibold text-[var(--vz-ink,#090d16)]" style={{ fontFamily: MONO }}>
                          {valueLabel}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>

        <div
          className="mt-3 grid grid-cols-[160px_minmax(260px,1fr)_120px] gap-x-4 text-[10px] text-[var(--vz-muted,#64748b)]"
          style={{ fontFamily: MONO }}
        >
          <span />
          <div className="flex justify-between">
            {axisTicks.map((tick, index) => (
              <span key={`${tick}-${index}`}>
                {formatTick(tick)}
                {index === axisTicks.length - 1 ? unit : ""}
              </span>
            ))}
          </div>
          <span />
        </div>
      </div>
    </div>
  );
}

export default PairedBars;
