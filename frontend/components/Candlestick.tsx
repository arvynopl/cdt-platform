"use client";

/**
 * Candlestick chart for one stock: pre-window history plus ONLY the rounds
 * revealed so far — the raw window data holds all 14 rounds, so slicing here
 * is what prevents look-ahead into future prices.
 */

import { useEffect, useRef } from "react";
import type { WindowRow } from "@/lib/api";

interface Props {
  preHistory: Partial<WindowRow>[];
  window: WindowRow[];
  /** 1-based current round; rounds AFTER this stay hidden. */
  revealedRounds: number;
  height?: number;
}

export default function Candlestick({
  preHistory,
  window: win,
  revealedRounds,
  height = 300,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;

    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;

      const revealed = win.slice(0, revealedRounds);
      const rows = [...preHistory, ...revealed] as WindowRow[];
      const x = rows.map((r) => r.date);

      const data: unknown[] = [
        {
          type: "candlestick",
          x,
          open: rows.map((r) => r.open),
          high: rows.map((r) => r.high),
          low: rows.map((r) => r.low),
          close: rows.map((r) => r.close),
          increasing: { line: { color: "#0F7B4D" } },
          decreasing: { line: { color: "#B3261E" } },
          name: "Harga",
        },
        {
          type: "scatter",
          mode: "lines",
          x,
          y: rows.map((r) => r.ma_5 ?? null),
          line: { color: "#2563EB", width: 1.2 },
          name: "MA5",
        },
        {
          type: "scatter",
          mode: "lines",
          x,
          y: rows.map((r) => r.ma_20 ?? null),
          line: { color: "#9A5B00", width: 1.2, dash: "dot" },
          name: "MA20",
        },
      ];

      const dark = document.documentElement.classList.contains("dark");
      const grid = dark ? "rgba(148,163,184,0.18)" : "rgba(100,116,139,0.15)";
      await Plotly.newPlot(
        el,
        data,
        {
          height,
          margin: { l: 48, r: 8, t: 8, b: 24 },
          showlegend: true,
          legend: { orientation: "h", y: 1.08 },
          xaxis: {
            rangeslider: { visible: false },
            type: "category",
            nticks: 8,
            gridcolor: grid,
          },
          yaxis: { fixedrange: true, tickformat: ",d", gridcolor: grid },
          dragmode: false,
          font: { size: 10, color: dark ? "#cbd5e1" : "#334155" },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
        },
        { displayModeBar: false, responsive: true },
      );
    })();

    return () => {
      cancelled = true;
      if (el) {
        import("plotly.js-dist-min").then((m) => m.default.purge(el));
      }
    };
  }, [preHistory, win, revealedRounds, height]);

  return <div ref={ref} className="w-full" />;
}
