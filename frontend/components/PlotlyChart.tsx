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
      await Plotly.newPlot(
        el,
        data,
        {
          height,
          margin: { l: 40, r: 16, t: 24, b: 32 },
          font: { size: 11 },
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
