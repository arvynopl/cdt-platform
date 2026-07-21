"use client";

/**
 * InstrumentRow — one compact row in the watchlist. Selecting a row drives the
 * chart and order ticket beside it, the way a trading terminal works, instead
 * of expanding a card in place.
 *
 * Price and change use tabular digits so the column stays aligned, and the
 * change is one of the few places gain/loss colour is allowed.
 */

import Badge from "@/components/ui/Badge";
import {
  formatPct,
  formatRupiah,
  type Order,
  type StockMeta,
} from "@/lib/api";

export default function InstrumentRow(props: {
  meta: StockMeta | undefined;
  fallbackId: string;
  price: number;
  change: number;
  held: number;
  order: Order | undefined;
  selected: boolean;
  onSelect: () => void;
}) {
  const { meta, price, change, held, order, selected } = props;
  const up = change >= 0;

  return (
    <button
      onClick={props.onSelect}
      aria-pressed={selected}
      className={`flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left
                  transition-colors ${
                    selected
                      ? "bg-brand-soft"
                      : "hover:bg-panel"
                  }`}
    >
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-sm font-semibold text-strong">
            {meta?.ticker ?? props.fallbackId}
          </span>
          {meta?.volatility_class === "high" && (
            <Badge tone="warn">volatil</Badge>
          )}
        </span>
        <span className="mt-0.5 block truncate text-xs text-muted">
          {meta?.name}
        </span>
        {(held > 0 || order) && (
          <span className="mt-1 flex flex-wrap items-center gap-1">
            {held > 0 && (
              <Badge>
                <span className="tnum">{held}</span>&nbsp;lembar
              </Badge>
            )}
            {order && (
              <Badge tone="brand">
                {order.action === "buy" ? "Beli" : "Jual"}&nbsp;
                <span className="tnum">{order.quantity}</span>
              </Badge>
            )}
          </span>
        )}
      </span>

      <span className="flex-none text-right">
        <span className="tnum block text-sm font-semibold text-strong">
          {formatRupiah(price)}
        </span>
        <span
          className={`tnum block text-xs font-medium ${up ? "text-gain" : "text-loss"}`}
        >
          {up ? "▲" : "▼"} {formatPct(Math.abs(change), 2)}
        </span>
      </span>
    </button>
  );
}
