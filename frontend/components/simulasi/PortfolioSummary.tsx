"use client";

/**
 * PortfolioSummary — the round-progress bar and the cash / total-value /
 * return figures shown above the stock list.
 */

import { formatPct, formatRupiah } from "@/lib/api";

export default function PortfolioSummary(props: {
  currentRound: number;
  roundsTotal: number;
  resumed: boolean;
  cash: number;
  totalValue: number;
  returnPct: number;
}) {
  return (
    <section
      data-tour="portfolio"
      className="rounded-xl border border-edge bg-card p-4"
    >
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-semibold">
          Putaran {props.currentRound} dari {props.roundsTotal}
        </span>
        <span className="text-muted">
          {props.resumed ? "melanjutkan sesi sebelumnya" : "sesi baru"}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-panel">
        <div
          className="h-full rounded-full bg-brand transition-all"
          style={{
            width: `${((props.currentRound - 1) / props.roundsTotal) * 100}%`,
          }}
        />
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div>
          <dt className="text-xs text-muted">Kas</dt>
          <dd className="text-sm font-semibold">{formatRupiah(props.cash)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Nilai Total</dt>
          <dd className="text-sm font-semibold">
            {formatRupiah(props.totalValue)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Imbal Hasil</dt>
          <dd
            className={`text-sm font-semibold ${
              props.returnPct >= 0 ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"
            }`}
          >
            {formatPct(props.returnPct)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
