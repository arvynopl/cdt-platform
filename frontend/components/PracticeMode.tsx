"use client";

/**
 * PracticeMode — three guided practice rounds before the first real session.
 *
 * Entirely client-side: uses a fictional stock with scripted prices, so no
 * decision here is recorded or analysed. Each step validates the expected
 * action before unlocking the next one, and progress persists in
 * localStorage so an interrupted tutorial resumes where it stopped.
 *
 * Step 1 — place a buy order.
 * Step 2 — execute the round, then read the portfolio change.
 * Step 3 — sell the position and see the realised profit.
 */

import { useEffect, useMemo, useState } from "react";
import Candlestick from "@/components/Candlestick";
import CoachTour, { type TourStep } from "@/components/CoachTour";
import { formatPct, formatRupiah, type WindowRow } from "@/lib/api";

const PROGRESS_KEY = "cdt_practice_v1"; // "1" | "2" | "3" | "done"
const TOUR_KEY = "cdt_tour_v2";

const CAPITAL = 10_000_000;
const STOCK = { ticker: "CNTH", name: "PT Contoh Sejahtera (saham latihan)" };

// Scripted closes: round 1 buy at 1.000 → round 2 rises → round 3 sell at 1.150.
const PRICES = [1000, 1080, 1150];

const PRE_HISTORY: Partial<WindowRow>[] = [
  { date: "Hari -5", open: 940, high: 970, low: 930, close: 960, ma_5: 950, ma_20: 945 },
  { date: "Hari -4", open: 960, high: 990, low: 950, close: 985, ma_5: 958, ma_20: 948 },
  { date: "Hari -3", open: 985, high: 1000, low: 970, close: 975, ma_5: 965, ma_20: 951 },
  { date: "Hari -2", open: 975, high: 1010, low: 970, close: 1005, ma_5: 976, ma_20: 955 },
  { date: "Hari -1", open: 1005, high: 1015, low: 985, close: 995, ma_5: 984, ma_20: 958 },
];

const WINDOW: WindowRow[] = PRICES.map((close, i) => ({
  id: -(i + 1),
  date: `Hari ${i + 1}`,
  open: close - 15,
  high: close + 20,
  low: close - 30,
  close,
  volume: 1_000_000,
  ma_5: close - 10,
  ma_20: close - 35,
  rsi_14: null,
  trend: null,
  daily_return: null,
}));

export const TOUR_STEPS: TourStep[] = [
  {
    target: "portfolio",
    title: "Ringkasan portofolio",
    body:
      "Di sini Anda memantau sisa kas, nilai total investasi, dan imbal hasil. " +
      "Angka-angka ini diperbarui setiap kali satu putaran selesai dijalankan.",
  },
  {
    target: "stocks",
    title: "Kartu saham",
    body:
      "Setiap kartu menampilkan harga hari itu beserta perubahannya. Sentuh " +
      "kartu untuk membuka grafik harga dan formulir order.",
  },
  {
    target: "chart",
    title: "Grafik harga",
    body:
      "Grafik lilin memperlihatkan riwayat harga sampai hari yang sedang " +
      "berjalan. Garis MA5 dan MA20 membantu membaca arah pergerakan. Harga " +
      "hari-hari berikutnya baru terbuka setelah putarannya tiba.",
  },
  {
    target: "ticket",
    title: "Formulir order",
    body:
      "Pilih Beli atau Jual, lalu isi jumlah lembar. Perkiraan biaya dan sisa " +
      "kas dihitung otomatis saat Anda mengetik, jadi tidak perlu menghitung " +
      "sendiri.",
  },
  {
    target: "execute",
    title: "Eksekusi putaran",
    body:
      "Satu tombol ini menjalankan seluruh order Anda sekaligus dan memajukan " +
      "simulasi ke hari berikutnya. Saham yang tidak diberi order otomatis " +
      "tercatat sebagai “tahan”, dan itu juga keputusan yang sah.",
  },
];

interface PracticeState {
  step: 1 | 2 | 3;
  shares: number;
  cash: number;
  buyPrice: number | null;
  executed1: boolean;
}

interface PracticeProps {
  onComplete: () => void;
  /**
   * Replay mode: entered voluntarily from the help menu. Starts at step 1,
   * never writes progress keys (a mid-replay exit must not re-lock the
   * first-session gate), and shows an exit action throughout.
   */
  replay?: boolean;
  onExit?: () => void;
}

export default function PracticeMode({ onComplete, replay = false, onExit }: PracticeProps) {
  const [tourOpen, setTourOpen] = useState(false);
  const [s, setS] = useState<PracticeState>(() => ({
    step: 1,
    shares: 0,
    cash: CAPITAL,
    buyPrice: null,
    executed1: false,
  }));
  const [qty, setQty] = useState(0);
  const [pendingBuy, setPendingBuy] = useState(0);
  const [pendingSell, setPendingSell] = useState(0);
  const [flash, setFlash] = useState<string | null>(null);
  const [profit, setProfit] = useState<number | null>(null);

  // Resume from saved progress (first run only; replay always starts clean).
  useEffect(() => {
    if (replay) return;
    const saved = localStorage.getItem(PROGRESS_KEY);
    if (saved === "2") setS((p) => ({ ...p, step: 2, shares: 100, cash: CAPITAL - 100 * PRICES[0], buyPrice: PRICES[0] }));
    if (saved === "3") setS((p) => ({ ...p, step: 3, shares: 100, cash: CAPITAL - 100 * PRICES[0], buyPrice: PRICES[0], executed1: true }));
    if (!localStorage.getItem(TOUR_KEY)) setTourOpen(true);
  }, [replay]);

  const round = s.step;
  const price = PRICES[round - 1];
  const totalValue = s.cash + s.shares * price;

  const narration = useMemo(() => {
    if (round === 1 && pendingBuy === 0) {
      return {
        title: "Latihan 1 dari 3: pasang order beli",
        body:
          "Mari mulai dari langkah paling dasar. Buka kartu saham latihan di " +
          "bawah, pilih Beli, isi jumlah lembar (misalnya 100), lalu tekan " +
          "“Tambahkan ke Order”.",
      };
    }
    if (round === 1) {
      return {
        title: "Order beli sudah siap",
        body:
          "Bagus. Order Anda belum dijalankan; ia menunggu di daftar order. " +
          "Sekarang tekan “Eksekusi Putaran” untuk menjalankannya.",
      };
    }
    if (round === 2 && !s.executed1) {
      return {
        title: "Latihan 2 dari 3: amati perubahan portofolio",
        body:
          `Order beli Anda terlaksana di harga ${formatRupiah(PRICES[0])}. ` +
          "Perhatikan ringkasan portofolio: kas berkurang, dan nilainya kini " +
          "mengikuti pergerakan harga. Hari ini harganya naik. Jalankan satu " +
          "putaran lagi tanpa order untuk melihat efek menahan posisi.",
      };
    }
    if (round === 3 && pendingSell === 0) {
      return {
        title: "Latihan 3 dari 3: jual dan amankan hasil",
        body:
          "Harga naik lagi. Saatnya menutup posisi: buka kartu saham, pilih " +
          "Jual, isi seluruh lembar yang Anda miliki, tambahkan ke order, lalu " +
          "eksekusi.",
      };
    }
    return {
      title: "Order jual sudah siap",
      body: "Tekan “Eksekusi Putaran” untuk menjual dan menyelesaikan latihan.",
    };
  }, [round, pendingBuy, pendingSell, s.executed1]);

  function saveProgress(step: string) {
    if (!replay) localStorage.setItem(PROGRESS_KEY, step);
  }

  function execute() {
    if (round === 1) {
      if (pendingBuy <= 0) {
        setFlash("Pasang order beli terlebih dahulu, ya.");
        return;
      }
      setS({
        step: 2,
        shares: pendingBuy,
        cash: s.cash - pendingBuy * price,
        buyPrice: price,
        executed1: false,
      });
      setPendingBuy(0);
      setQty(0);
      setFlash(null);
      saveProgress("2");
    } else if (round === 2) {
      setS({ ...s, step: 3, executed1: true });
      setFlash(null);
      saveProgress("3");
    } else {
      if (pendingSell < s.shares) {
        setFlash("Jual seluruh lembar yang Anda miliki untuk menyelesaikan latihan.");
        return;
      }
      const proceeds = s.shares * price;
      saveProgress("done");
      setFlash(null);
      setProfit(proceeds - (s.buyPrice ?? 0) * s.shares);
      setS({ ...s, cash: s.cash + proceeds, shares: 0 });
    }
  }

  const canSubmitTicket =
    round === 1
      ? qty > 0 && qty * price <= s.cash
      : round === 3 && qty > 0 && qty <= s.shares;

  if (profit !== null) {
    return (
      <main className="mx-auto max-w-md space-y-4 pt-8 text-center">
        <div className="text-4xl">🎓</div>
        <h2 className="text-lg font-semibold">Latihan selesai!</h2>
        <p className="text-sm leading-relaxed text-slate-600">
          Anda menutup posisi latihan dengan hasil{" "}
          <b className="text-emerald-700">{formatRupiah(profit)}</b>. Seluruh
          alur sudah Anda kuasai: memasang order, mengeksekusi putaran, dan
          membaca dampaknya pada portofolio.
        </p>
        <p className="text-sm leading-relaxed text-slate-600">
          {replay
            ? "Ingatan sudah segar kembali. Silakan lanjutkan sesi Anda."
            : "Sekarang saatnya yang sebenarnya: 14 putaran dengan 12 saham IDX dan data historis asli. Selamat berlatih mengenali gaya Anda sendiri."}
        </p>
        <button
          onClick={onComplete}
          className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white"
        >
          {replay ? "Kembali ke Simulasi →" : "Masuk ke Simulasi →"}
        </button>
      </main>
    );
  }

  return (
    <main className="space-y-4 pb-28">
      {tourOpen && (
        <CoachTour
          steps={TOUR_STEPS}
          onFinish={() => {
            localStorage.setItem(TOUR_KEY, "1");
            setTourOpen(false);
          }}
          onSkip={() => {
            localStorage.setItem(TOUR_KEY, "1");
            setTourOpen(false);
          }}
        />
      )}

      <div className="rounded-xl border border-brand/30 bg-brand-soft px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand">
            Mode Latihan{replay ? " (pengulangan)" : ""}
          </p>
          {replay && onExit && (
            <button
              onClick={onExit}
              className="text-xs font-medium text-slate-500 underline-offset-2 hover:underline"
            >
              Kembali ke simulasi
            </button>
          )}
        </div>
        <h2 className="mt-0.5 text-sm font-semibold">{narration.title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-700">
          {narration.body}
        </p>
        <p className="mt-1.5 text-xs text-slate-500">
          Keputusan pada mode latihan tidak direkam dan tidak memengaruhi
          analisis Anda.
        </p>
      </div>

      {flash && (
        <p className="rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {flash}
        </p>
      )}

      {/* Portfolio summary */}
      <section
        data-tour="portfolio"
        className="rounded-xl border border-slate-200 bg-white p-4"
      >
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-semibold">Latihan {round} dari 3</span>
          <span className="text-slate-500">saham fiktif, harga terskrip</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-brand transition-all"
            style={{ width: `${((round - 1) / 3) * 100}%` }}
          />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
          <div>
            <dt className="text-xs text-slate-500">Kas</dt>
            <dd className="text-sm font-semibold">{formatRupiah(s.cash)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Nilai Total</dt>
            <dd className="text-sm font-semibold">{formatRupiah(totalValue)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Imbal Hasil</dt>
            <dd
              className={`text-sm font-semibold ${
                totalValue >= CAPITAL ? "text-emerald-700" : "text-red-700"
              }`}
            >
              {formatPct(((totalValue - CAPITAL) / CAPITAL) * 100)}
            </dd>
          </div>
        </dl>
      </section>

      {/* The one practice stock */}
      <section data-tour="stocks" className="rounded-xl border border-slate-200 bg-white">
        <div className="flex w-full items-center justify-between gap-2 p-3 text-left">
          <div>
            <p className="text-sm font-semibold">{STOCK.ticker}</p>
            <p className="text-xs text-slate-500">{STOCK.name}</p>
          </div>
          <div className="text-right">
            <p className="text-sm font-semibold">{formatRupiah(price)}</p>
            {round > 1 && (
              <p className="text-xs text-emerald-700">
                ▲ {formatPct(((price - PRICES[round - 2]) / PRICES[round - 2]) * 100, 2)}
              </p>
            )}
          </div>
        </div>
        {s.shares > 0 && (
          <p className="px-3 pb-1 text-xs text-slate-500">
            Dimiliki: {s.shares} lembar
          </p>
        )}
        {(pendingBuy > 0 || pendingSell > 0) && (
          <p className="px-3 pb-1">
            <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand">
              {pendingBuy > 0 ? `Beli ${pendingBuy}` : `Jual ${pendingSell}`} menunggu eksekusi
            </span>
          </p>
        )}

        <div className="border-t border-slate-100 p-3">
          <div data-tour="chart">
            <Candlestick
              preHistory={PRE_HISTORY}
              window={WINDOW}
              revealedRounds={round}
              height={220}
            />
          </div>

          {/* Simplified ticket: the action is fixed by the current lesson */}
          <div data-tour="ticket" className="mt-3 rounded-lg bg-slate-50 p-3">
            <p className="text-xs font-medium text-slate-600">
              {round === 3 ? "Jual" : "Beli"} {STOCK.ticker}
            </p>
            <label className="mt-1.5 block text-xs font-medium text-slate-600">
              Jumlah lembar
              <input
                type="number"
                min={0}
                value={qty || ""}
                onChange={(e) => setQty(Math.max(0, Number(e.target.value)))}
                disabled={round === 2}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
                placeholder={
                  round === 3
                    ? `dimiliki ${s.shares}`
                    : round === 2
                      ? "hari ini cukup amati saja"
                      : `maks. ${Math.floor(s.cash / price)}`
                }
              />
            </label>
            <dl className="mt-2 space-y-0.5 text-xs text-slate-600">
              <div className="flex justify-between">
                <dt>{round === 3 ? "Perkiraan hasil jual" : "Perkiraan biaya"}</dt>
                <dd className="font-semibold">{formatRupiah(qty * price)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Kas setelah eksekusi</dt>
                <dd className="font-semibold">
                  {formatRupiah(round === 3 ? s.cash + qty * price : s.cash - qty * price)}
                </dd>
              </div>
            </dl>
            <button
              onClick={() => {
                if (round === 3) setPendingSell(qty);
                else setPendingBuy(qty);
              }}
              disabled={!canSubmitTicket}
              className="mt-3 w-full rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
            >
              Tambahkan ke Order
            </button>
          </div>
        </div>
      </section>

      {/* Execute bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <p className="text-sm text-slate-600">
            {pendingBuy > 0 || pendingSell > 0 ? (
              <>
                <b>1</b> order menunggu eksekusi
              </>
            ) : (
              "Belum ada order"
            )}
          </p>
          <button
            data-tour="execute"
            onClick={execute}
            className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Eksekusi Putaran →
          </button>
        </div>
      </div>
    </main>
  );
}
