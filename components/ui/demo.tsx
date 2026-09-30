"use client";

import React from "react";
import { PairedBars, type PairedBarGroup } from "@/components/ui/paired-bars";

export const benchmarkGroups: PairedBarGroup[] = [
  {
    label: "Coding",
    subtitle: "SWE-agent bug-fixing, 20 repos",
    sample: "40 transcripts",
    turnsRetired: 161,
    payloadsCompacted: 668,
    color: "#2563eb",
    a: {
      label: "Token reduction",
      value: 66.5,
      valueLabel: "66.5%",
    },
    b: {
      label: "Precision",
      value: 100,
      valueLabel: "100% n=36, CI 90–100%",
    },
  },
  {
    label: "Airline support",
    subtitle: "APIGen-MT-5k, reservation tool use",
    sample: "60 conversations",
    turnsRetired: 9,
    payloadsCompacted: 138,
    color: "#059669",
    a: {
      label: "Token reduction",
      value: 59.0,
      valueLabel: "59.0%",
    },
    b: {
      label: "Precision",
      value: 100,
      valueLabel: "100% n=72, CI 95–100%",
    },
  },
  {
    label: "Retail support",
    subtitle: "APIGen-MT-5k, order and exchange tool use",
    sample: "80 conversations",
    turnsRetired: 2,
    payloadsCompacted: 275,
    color: "#d97706",
    a: {
      label: "Token reduction",
      value: 62.5,
      valueLabel: "62.5%",
    },
    b: {
      label: "Precision",
      value: 100,
      valueLabel: "100% n=47, CI 92–100%",
    },
  },
];

export function PairedBarsDemo() {
  return (
    <div className="w-full max-w-4xl mx-auto p-6 rounded-2xl bg-[var(--vz-card-bg,#ffffff)] shadow-sm border border-[var(--vz-grid,#e2e8f0)]">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--vz-grid,#e2e8f0)] pb-4">
        <div>
          <span className="text-[11px] font-mono font-semibold uppercase tracking-wider text-[var(--vz-muted,#64748b)]">
            Empirical Benchmarks
          </span>
          <h2 className="text-xl font-bold tracking-tight text-[var(--vz-ink,#090d16)]">
            Token Reduction vs. Precision Rate
          </h2>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-xs bg-[var(--accent,#2563eb)]" />
            <span className="text-[var(--vz-ink,#090d16)] font-medium">Token reduction</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-xs bg-[var(--accent,#2563eb)] opacity-55" />
            <span className="text-[var(--vz-muted,#64748b)]">Compiler precision</span>
          </div>
        </div>
      </div>

      <PairedBars
        barLabel="Benchmark Metric (0—100%)"
        unit="%"
        max={100}
        ticks={[0, 25, 50, 75, 100]}
        groups={benchmarkGroups}
      />

      <div className="mt-4 pt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-[var(--vz-muted,#64748b)] border-t border-[var(--vz-grid,#e2e8f0)] font-mono">
        <span>Total: 180 trajectories across 3 domains</span>
        <span>Turns retired: 172 · Payloads compacted: 1,081</span>
      </div>
    </div>
  );
}

export default PairedBarsDemo;
