"use client";

/**
 * ConfirmRoundDialog — F12 explicit round confirmation. Lists the pending
 * orders (and how many stocks auto-hold), then executes on confirm. An
 * accessible modal: focuses itself on open, closes on Escape or backdrop
 * click, and is labelled for screen readers.
 */

import { useEffect, useRef } from "react";
import { formatRupiah, type Order, type StockMeta } from "@/lib/api";

export default function ConfirmRoundDialog(props: {
  currentRound: number;
  pendingList: Order[];
  autoHoldCount: number;
  metaOf: (sid: string) => StockMeta | undefined;
  prices: Record<string, number>;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // props.onClose is stable enough for this short-lived modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={props.onClose}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="konfirmasi-judul"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl outline-none"
      >
        <h3 id="konfirmasi-judul" className="text-base font-semibold">
          Konfirmasi Putaran {props.currentRound}
        </h3>
        {props.pendingList.length > 0 ? (
          <ul className="mt-3 space-y-1.5 text-sm">
            {props.pendingList.map((o) => (
              <li key={o.stock_id} className="flex justify-between">
                <span>
                  {o.action === "buy" ? "🟢 Beli" : "🔴 Jual"}{" "}
                  <b>{props.metaOf(o.stock_id)?.ticker ?? o.stock_id}</b> ×{" "}
                  {o.quantity}
                </span>
                <span className="text-muted">
                  {formatRupiah(o.quantity * (props.prices[o.stock_id] ?? 0))}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm leading-relaxed text-bodytext">
            Tidak ada order pada putaran ini, jadi seluruh saham akan dicatat
            sebagai <b>tahan</b>. Tidak masalah; menahan juga keputusan investasi
            yang sah dan ikut dianalisis.
          </p>
        )}
        {props.pendingList.length > 0 && props.autoHoldCount > 0 && (
          <p className="mt-2 text-xs text-muted">
            {props.autoHoldCount} saham lainnya otomatis dicatat sebagai tahan.
          </p>
        )}
        <div className="mt-5 flex gap-3">
          <button
            onClick={props.onClose}
            className="flex-1 rounded-lg border border-edge2 px-4 py-2.5 text-sm"
          >
            Periksa Lagi
          </button>
          <button
            onClick={props.onConfirm}
            disabled={props.busy}
            className="flex-1 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {props.busy ? "Menyimpan…" : "Ya, Jalankan"}
          </button>
        </div>
      </div>
    </div>
  );
}
