"use client";

/**
 * PortfolioSummary — the round-progress bar and the cash / total-value /
 * return figures. Laid out like a trading terminal's account strip: figures
 * right-aligned with tabular digits, and the return is the only element
 * allowed to carry gain/loss colour.
 */

import Stat from "@/components/ui/Stat";
import { formatPct, formatRupiah } from "@/lib/api";

export default function PortfolioSummary(props: {
  currentRound: number;
  roundsTotal: number;
  resumed: boolean;
  cash: number;
  totalValue: number;
  returnPct: number;
}) {
  const pct = ((props.currentRound - 1) / props.roundsTotal) * 100;

  return (
    <section
      data-tour="portfolio"
      className="rounded-xl border border-edge bg-card"
    >
      <div className="flex items-center justify-between gap-3 px-4 pt-3">
        <span className="text-sm font-semibold text-strong">
          Putaran <span className="tnum">{props.currentRound}</span> dari{" "}
          <span className="tnum">{props.roundsTotal}</span>
        </span>
        <span className="text-xs text-muted">
          {props.resumed ? "Melanjutkan sesi sebelumnya" : "Sesi baru"}
        </span>
      </div>

      <div className="px-4 pt-2">
        <div
          className="h-1 overflow-hidden rounded-full bg-panel"
          role="progressbar"
          aria-valuenow={props.currentRound - 1}
          aria-valuemin={0}
          aria-valuemax={props.roundsTotal}
          aria-label="Kemajuan sesi"
        >
          <div
            className="h-full rounded-full bg-brand transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 border-t border-edge px-4 py-3 mt-3">
        <Stat label="Kas" value={formatRupiah(props.cash)} />
        <Stat label="Nilai Total" value={formatRupiah(props.totalValue)} />
        <Stat
          label="Imbal Hasil"
          value={formatPct(props.returnPct)}
          tone={props.returnPct >= 0 ? "gain" : "loss"}
          align="right"
        />
      </div>
    </section>
  );
}
