/**
 * Stat — a labelled figure. Numbers use tabular digits so columns line up,
 * and `tone` is the ONLY place gain/loss colour enters the UI.
 */

import type { ReactNode } from "react";

export default function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  align = "left",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "gain" | "loss";
  align?: "left" | "right" | "center";
}) {
  const toneCls =
    tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : "text-strong";
  const alignCls =
    align === "right" ? "text-right" : align === "center" ? "text-center" : "";

  return (
    <div className={alignCls}>
      <div className="text-[11px] uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className={`tnum mt-0.5 text-base font-semibold ${toneCls}`}>
        {value}
      </div>
      {hint && <div className="tnum mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}
