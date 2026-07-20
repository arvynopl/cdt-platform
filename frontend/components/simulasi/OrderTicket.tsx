"use client";

/**
 * OrderTicket — F11 order entry with a live cost/proceeds preview.
 *
 * Previews cost and post-execution cash as the user types, accounts for cash
 * already committed to other pending buys (via `spendableCash`), and blocks
 * unaffordable buys / oversized sells before they reach the server.
 */

import { useState } from "react";
import { formatRupiah, type Order } from "@/lib/api";

export default function OrderTicket(props: {
  price: number;
  heldQty: number;
  /** Cash available to THIS ticket (other pending buys already deducted). */
  spendableCash: number;
  existing: Order | null;
  onSet: (order: { action: "buy" | "sell"; quantity: number } | null) => void;
}) {
  const [action, setAction] = useState<"buy" | "sell">(
    props.existing?.action ?? "buy",
  );
  const [qty, setQty] = useState<number>(props.existing?.quantity ?? 0);

  const cost = qty * props.price;
  const buyExceeds = action === "buy" && cost > props.spendableCash;
  const sellExceeds = action === "sell" && qty > props.heldQty;
  const invalid = qty <= 0 || buyExceeds || sellExceeds;

  const maxBuy = Math.floor(props.spendableCash / props.price);

  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <div className="flex gap-2">
        {(["buy", "sell"] as const).map((a) => (
          <button
            key={a}
            onClick={() => setAction(a)}
            aria-pressed={action === a}
            className={`flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              action === a
                ? a === "buy"
                  ? "bg-emerald-600 text-white"
                  : "bg-red-600 text-white"
                : "border border-slate-300 text-slate-600"
            }`}
          >
            {a === "buy" ? "Beli" : "Jual"}
          </button>
        ))}
      </div>

      <label className="mt-2 block text-xs font-medium text-slate-600">
        Jumlah lembar
        <input
          type="number"
          min={0}
          value={qty || ""}
          onChange={(e) => setQty(Math.max(0, Number(e.target.value)))}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder={
            action === "buy" ? `maks. ${maxBuy}` : `dimiliki ${props.heldQty}`
          }
        />
      </label>

      {/* F11: live preview, no manual arithmetic needed */}
      <dl className="mt-2 space-y-0.5 text-xs text-slate-600">
        <div className="flex justify-between">
          <dt>
            {action === "buy" ? "Perkiraan biaya" : "Perkiraan hasil jual"}
          </dt>
          <dd className="font-semibold">{formatRupiah(cost)}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Kas setelah eksekusi</dt>
          <dd className={`font-semibold ${buyExceeds ? "text-red-700" : ""}`}>
            {formatRupiah(
              action === "buy"
                ? props.spendableCash - cost
                : props.spendableCash + cost,
            )}
          </dd>
        </div>
      </dl>

      {buyExceeds && (
        <p className="mt-1 text-xs text-red-700">
          Kas Anda tidak cukup untuk jumlah ini; maksimal {maxBuy} lembar.
        </p>
      )}
      {sellExceeds && (
        <p className="mt-1 text-xs text-red-700">
          Jumlahnya melebihi {props.heldQty} lembar yang Anda miliki.
        </p>
      )}

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => props.onSet({ action, quantity: qty })}
          disabled={invalid}
          className="flex-1 rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
        >
          {props.existing ? "Perbarui Order" : "Tambahkan ke Order"}
        </button>
        {props.existing && (
          <button
            onClick={() => props.onSet(null)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600"
          >
            Batalkan
          </button>
        )}
      </div>
    </div>
  );
}
