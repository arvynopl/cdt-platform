"use client";

/**
 * StockCard — one collapsible stock row in the trading interface: a header
 * button (price + round change) that expands to reveal the no-lookahead
 * candlestick chart and the order ticket. Kept presentational; all state and
 * the order mutation live in the parent page.
 */

import Candlestick from "@/components/Candlestick";
import OrderTicket from "@/components/simulasi/OrderTicket";
import {
  formatPct,
  formatRupiah,
  type Order,
  type StockMeta,
  type WindowRow,
} from "@/lib/api";

export default function StockCard(props: {
  meta: StockMeta | undefined;
  fallbackId: string;
  price: number;
  change: number;
  held: number;
  order: Order | undefined;
  isOpen: boolean;
  onToggle: () => void;
  preHistory: Partial<WindowRow>[];
  windowData: WindowRow[];
  revealedRounds: number;
  spendableCash: number;
  onSetOrder: (
    order: { action: "buy" | "sell"; quantity: number } | null,
  ) => void;
}) {
  const { meta, price, change, held, order, isOpen } = props;

  return (
    <div className="rounded-xl border border-edge bg-card">
      <button
        onClick={props.onToggle}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-2 p-3 text-left"
      >
        <div>
          <p className="text-sm font-semibold">
            {meta?.ticker ?? props.fallbackId}
            {meta?.volatility_class === "high" && (
              <span className="ml-1.5 rounded bg-amber-100 dark:bg-amber-950/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:text-amber-300">
                volatil tinggi
              </span>
            )}
          </p>
          <p className="text-xs text-muted">{meta?.name}</p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold">{formatRupiah(price)}</p>
          <p
            className={`text-xs ${
              change >= 0 ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"
            }`}
          >
            {change >= 0 ? "▲" : "▼"} {formatPct(Math.abs(change), 2)}
          </p>
        </div>
      </button>
      {(held > 0 || order) && (
        <div className="flex items-center gap-2 px-3 pb-2 text-xs text-muted">
          {held > 0 && <span>Dimiliki: {held} lembar</span>}
          {order && (
            <span className="rounded bg-brand-soft px-1.5 py-0.5 font-medium text-brand">
              {order.action === "buy" ? "Beli" : "Jual"} {order.quantity}{" "}
              menunggu eksekusi
            </span>
          )}
        </div>
      )}
      {isOpen && (
        <div className="border-t border-edge p-3">
          <div data-tour="chart">
            <Candlestick
              preHistory={props.preHistory}
              window={props.windowData}
              revealedRounds={props.revealedRounds}
              height={260}
            />
          </div>
          <div data-tour="ticket">
            <OrderTicket
              price={price}
              heldQty={held}
              spendableCash={
                props.spendableCash +
                (order?.action === "buy" ? order.quantity * price : 0)
              }
              existing={order ?? null}
              onSet={props.onSetOrder}
            />
          </div>
        </div>
      )}
    </div>
  );
}
