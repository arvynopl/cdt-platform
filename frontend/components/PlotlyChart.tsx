"use client";

/**
 * Generic Plotly wrapper: client-only dynamic import, responsive, no mode
 * bar. Candlestick.tsx stays specialized; this covers radar/line/scatter
 * charts on the profile page.
 */

import { useEffect, useRef } from "react";

interface Props {
  data: unknown[];
  layout?: Record<string, unknown>;
  height?: number;
  ariaLabel?: string;
}

export default function PlotlyChart({ data, layout, height = 320, ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;

    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      // Theme-aware: transparent backgrounds so the chart sits on the card,
      // and a light tick/legend colour in dark mode so labels stay legible.
      const dark = document.documentElement.classList.contains("dark");
      await Plotly.newPlot(
        el,
        data,
        {
          height,
          margin: { l: 40, r: 16, t: 24, b: 32 },
          font: { size: 11, color: dark ? "#cbd5e1" : "#334155" },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          ...layout,
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
  }, [data, layout, height]);

  return <div ref={ref} className="w-full" role="img" aria-label={ariaLabel} />;
}
