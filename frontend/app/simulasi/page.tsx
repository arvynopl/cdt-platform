"use client";

/**
 * Simulasi — the 14-round trading interface (Fase 2.2/2.3).
 *
 * UAT fixes designed in (audit F11–F13):
 *  - F11: the order ticket previews cost/proceeds and post-execution cash
 *    live, accounts for other pending buys, and blocks unaffordable orders
 *    before they reach the server.
 *  - F12: orders collect in a pending tray; one "Eksekusi Putaran" action
 *    opens an explicit confirmation dialog that also names how many stocks
 *    will auto-hold.
 *  - F13 (interactive): first-time users go through PracticeMode — a
 *    component spotlight tour plus three validated practice rounds on a
 *    fictional stock — before their first real session. Returning users
 *    (existing completed sessions) skip it automatically. The tour can be
 *    replayed on the real interface via the help button.
 *
 * Transient interaction state (expanded card, draft quantities, pending
 * orders) is fully reset after every executed round; only portfolio and
 * round state carry over. The chart only ever renders revealed rounds.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Candlestick from "@/components/Candlestick";
import CoachTour from "@/components/CoachTour";
import PracticeMode, { TOUR_STEPS } from "@/components/PracticeMode";
import {
  api,
  ApiError,
  formatPct,
  formatRupiah,
  type AnalysisStatus,
  type Me,
  type Order,
  type RoundResult,
  type SessionState,
} from "@/lib/api";

type Phase = "loading" | "practice" | "trading" | "analyzing" | "analysis_error";

const PRACTICE_KEY = "cdt_practice_v1";

export default function SimulasiPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [state, setState] = useState<SessionState | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [roundErrors, setRoundErrors] = useState<string[]>([]);
  const [pending, setPending] = useState<Record<string, Order>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [practiceReplay, setPracticeReplay] = useState(false);
  const [busy, setBusy] = useState(false);
  const roundStartRef = useRef<number>(Date.now());

  const startSession = useCallback(async () => {
    try {
      const s = await api.post<SessionState>("/api/sessions");
      setState(s);
      if (s.rounds_complete) {
        setPhase("analyzing");
      } else {
        setPhase("trading");
        roundStartRef.current = Date.now();
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : "Tidak dapat terhubung ke server.",
      );
    }
  }, []);

  // -- bootstrap: auth check → practice gate → session ----------------------
  useEffect(() => {
    (async () => {
      let user: Me;
      try {
        user = await api.get<Me>("/api/auth/me");
      } catch {
        router.replace("/");
        return;
      }
      setMe(user);

      if (localStorage.getItem(PRACTICE_KEY) === "done") {
        await startSession();
        return;
      }
      // Returning users with a completed session skip practice automatically.
      try {
        const profile = await api.get<{ profile: { session_count: number } | null }>(
          "/api/me/profile",
        );
        if ((profile.profile?.session_count ?? 0) > 0) {
          localStorage.setItem(PRACTICE_KEY, "done");
          await startSession();
          return;
        }
      } catch {
        /* profile fetch failing should not block the gate decision */
      }
      setPhase("practice");
    })();
  }, [router, startSession]);

  // -- analysis poll --------------------------------------------------------
  useEffect(() => {
    if (phase !== "analyzing" || !state) return;
    let stop = false;
    (async () => {
      for (let i = 0; i < 120 && !stop; i++) {
        try {
          const a = await api.get<AnalysisStatus>(
            `/api/sessions/${state.session_id}/analysis`,
          );
          if (a.status === "completed") {
            router.push(`/hasil?sid=${state.session_id}`);
            return;
          }
          if (a.status === "error") {
            setPhase("analysis_error");
            return;
          }
        } catch {
          /* transient — keep polling */
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
      if (!stop) setPhase("analysis_error");
    })();
    return () => {
      stop = true;
    };
  }, [phase, state, router]);

  const currentRound = state?.current_round ?? 1;
  const prices = useMemo(() => {
    if (!state) return {} as Record<string, number>;
    const idx = Math.min(currentRound, state.rounds_total) - 1;
    return Object.fromEntries(
      state.stock_ids.map((sid) => [sid, state.window[sid][idx].close]),
    );
  }, [state, currentRound]);

  const prevPrices = useMemo(() => {
    if (!state) return {} as Record<string, number>;
    const idx = Math.min(currentRound, state.rounds_total) - 1;
    return Object.fromEntries(
      state.stock_ids.map((sid) => {
        const win = state.window[sid];
        const prev =
          idx > 0
            ? win[idx - 1].close
            : (state.pre_window_history[sid]?.at(-1)?.close ?? win[0].close);
        return [sid, prev];
      }),
    );
  }, [state, currentRound]);

  // F11: cash after all pending BUY orders (sale proceeds credit only on
  // execution, so they are conservatively excluded from spendable preview).
  const pendingBuyCost = useMemo(
    () =>
      Object.values(pending)
        .filter((o) => o.action === "buy")
        .reduce((sum, o) => sum + o.quantity * (prices[o.stock_id] ?? 0), 0),
    [pending, prices],
  );
  const spendableCash = (state?.portfolio.cash ?? 0) - pendingBuyCost;

  const heldQty = useCallback(
    (sid: string) =>
      state?.portfolio.holdings.find((h) => h.stock_id === sid)?.quantity ?? 0,
    [state],
  );

  // -- round submission (F12 confirm → execute) ----------------------------
  async function executeRound() {
    if (!state) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<RoundResult>(
        `/api/sessions/${state.session_id}/rounds/${currentRound}`,
        {
          orders: Object.values(pending),
          response_time_ms: Math.min(
            Date.now() - roundStartRef.current,
            3_600_000,
          ),
        },
      );
      setRoundErrors(result.errors);
      // Full transient-state reset: pending tray, expanded card, dialog.
      // The stock-list `key` below remounts every ticket, clearing inputs.
      setPending({});
      setSelected(null);
      setConfirmOpen(false);
      setState({
        ...state,
        current_round: result.next_round,
        rounds_complete: result.rounds_complete,
        portfolio: result.portfolio,
      });
      roundStartRef.current = Date.now();
      window.scrollTo({ top: 0, behavior: "smooth" });
      if (result.rounds_complete) setPhase("analyzing");
    } catch (err) {
      setConfirmOpen(false);
      setError(
        err instanceof ApiError
          ? err.detail
          : "Keputusan putaran ini belum tersimpan. Silakan coba lagi.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function retryAnalysis() {
    if (!state) return;
    setPhase("analyzing");
    try {
      await api.post(`/api/sessions/${state.session_id}/analysis/retry`);
    } catch {
      setPhase("analysis_error");
    }
  }

  // -- render ---------------------------------------------------------------
  if (phase === "practice") {
    return (
      <PracticeMode
        onComplete={() => {
          localStorage.setItem(PRACTICE_KEY, "done");
          setPhase("loading");
          startSession();
        }}
      />
    );
  }

  // Voluntary replay from the help menu: rendered instead of the trading UI,
  // but the session state stays mounted, so leaving practice returns the
  // user to exactly the round they were on.
  if (practiceReplay) {
    return (
      <PracticeMode
        replay
        onComplete={() => setPracticeReplay(false)}
        onExit={() => setPracticeReplay(false)}
      />
    );
  }

  if (!me || !state) {
    return (
      <main>
        {error ? (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : (
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
            Menyiapkan sesi Anda…
          </div>
        )}
      </main>
    );
  }

  if (phase === "analyzing" || phase === "analysis_error") {
    return (
      <main className="mx-auto max-w-md space-y-4 pt-6 text-center">
        <h2 className="text-lg font-semibold">Sesi Selesai 🎯</h2>
        {phase === "analyzing" ? (
          <>
            <p className="text-sm leading-relaxed text-slate-600">
              Seluruh {state.rounds_total} putaran sudah Anda selesaikan.
              Tunggu sebentar, sistem sedang membaca pola keputusan Anda.
            </p>
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
          </>
        ) : (
          <>
            <p className="text-sm leading-relaxed text-slate-600">
              Keputusan Anda pada seluruh putaran sudah tersimpan dengan aman.
              Hanya tahap analisisnya yang sempat gagal, jadi cukup jalankan
              ulang.
            </p>
            <button
              onClick={retryAnalysis}
              className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white"
            >
              Jalankan Analisis Ulang
            </button>
            <p className="text-xs text-slate-400">
              Bila masalah berlanjut, hubungi tim kami dengan kode sesi{" "}
              <code>{state.session_id.slice(0, 8)}</code>.
            </p>
          </>
        )}
      </main>
    );
  }

  const pendingList = Object.values(pending);
  const autoHoldCount = state.stock_ids.length - pendingList.length;
  const metaOf = (sid: string) => state.stocks.find((s) => s.stock_id === sid);
  const returnPct =
    ((state.portfolio.total_value - 10_000_000) / 10_000_000) * 100;

  return (
    <main className="space-y-4 pb-28">
      {tourOpen && (
        <CoachTour
          steps={TOUR_STEPS}
          onBeforeStep={(target) => {
            if (target === "chart" || target === "ticket") {
              setSelected(state.stock_ids[0]);
            }
          }}
          onFinish={() => setTourOpen(false)}
          onSkip={() => setTourOpen(false)}
        />
      )}

      <div className="fixed bottom-20 right-4 z-40 flex flex-col items-end gap-2">
        {helpOpen && (
          <div className="w-56 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
            <button
              onClick={() => {
                setHelpOpen(false);
                setTourOpen(true);
              }}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-soft"
            >
              Putar ulang panduan halaman
              <span className="block text-xs text-slate-500">
                Tur singkat mengenal setiap bagian layar
              </span>
            </button>
            <button
              onClick={() => {
                setHelpOpen(false);
                setPracticeReplay(true);
              }}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-soft"
            >
              Ulangi mode latihan
              <span className="block text-xs text-slate-500">
                Tiga putaran percobaan; sesi Anda tetap aman
              </span>
            </button>
          </div>
        )}
        <button
          onClick={() => setHelpOpen((v) => !v)}
          aria-label="Bantuan"
          aria-expanded={helpOpen}
          className="h-10 w-10 rounded-full border border-slate-300 bg-white
                     text-lg font-semibold text-brand shadow-md hover:bg-brand-soft"
        >
          ?
        </button>
      </div>

      {/* Progress + portfolio summary */}
      <section
        data-tour="portfolio"
        className="rounded-xl border border-slate-200 bg-white p-4"
      >
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-semibold">
            Putaran {currentRound} dari {state.rounds_total}
          </span>
          <span className="text-slate-500">
            {state.resumed ? "melanjutkan sesi sebelumnya" : "sesi baru"}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-brand transition-all"
            style={{
              width: `${((currentRound - 1) / state.rounds_total) * 100}%`,
            }}
          />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
          <div>
            <dt className="text-xs text-slate-500">Kas</dt>
            <dd className="text-sm font-semibold">
              {formatRupiah(state.portfolio.cash)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Nilai Total</dt>
            <dd className="text-sm font-semibold">
              {formatRupiah(state.portfolio.total_value)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Imbal Hasil</dt>
            <dd
              className={`text-sm font-semibold ${
                returnPct >= 0 ? "text-emerald-700" : "text-red-700"
              }`}
            >
              {formatPct(returnPct)}
            </dd>
          </div>
        </dl>
      </section>

      {(error || roundErrors.length > 0) && (
        <div className="space-y-1 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {error && <p>{error}</p>}
          {roundErrors.map((e, i) => (
            <p key={i}>
              {e}{" "}
              <span className="text-amber-600">
                (order tersebut dicatat sebagai tahan)
              </span>
            </p>
          ))}
        </div>
      )}

      {/* Stock list — keyed by round so every ticket remounts clean */}
      <section key={currentRound} data-tour="stocks" className="grid gap-2 sm:grid-cols-2">
        {state.stock_ids.map((sid) => {
          const meta = metaOf(sid);
          const price = prices[sid];
          const change = ((price - prevPrices[sid]) / prevPrices[sid]) * 100;
          const held = heldQty(sid);
          const order = pending[sid];
          const isOpen = selected === sid;
          return (
            <div key={sid} className="rounded-xl border border-slate-200 bg-white">
              <button
                onClick={() => setSelected(isOpen ? null : sid)}
                aria-expanded={isOpen}
                className="flex w-full items-center justify-between gap-2 p-3 text-left"
              >
                <div>
                  <p className="text-sm font-semibold">
                    {meta?.ticker ?? sid}
                    {meta?.volatility_class === "high" && (
                      <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                        volatil tinggi
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">{meta?.name}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold">{formatRupiah(price)}</p>
                  <p
                    className={`text-xs ${
                      change >= 0 ? "text-emerald-700" : "text-red-700"
                    }`}
                  >
                    {change >= 0 ? "▲" : "▼"} {formatPct(Math.abs(change), 2)}
                  </p>
                </div>
              </button>
              {(held > 0 || order) && (
                <div className="flex items-center gap-2 px-3 pb-2 text-xs text-slate-500">
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
                <div className="border-t border-slate-100 p-3">
                  <div data-tour="chart">
                    <Candlestick
                      preHistory={state.pre_window_history[sid] ?? []}
                      window={state.window[sid]}
                      revealedRounds={currentRound}
                      height={260}
                    />
                  </div>
                  <div data-tour="ticket">
                    <OrderTicket
                      price={price}
                      heldQty={held}
                      spendableCash={
                        spendableCash +
                        (order?.action === "buy" ? order.quantity * price : 0)
                      }
                      existing={order ?? null}
                      onSet={(o) =>
                        setPending((p) =>
                          o === null
                            ? Object.fromEntries(
                                Object.entries(p).filter(([k]) => k !== sid),
                              )
                            : { ...p, [sid]: { ...o, stock_id: sid } },
                        )
                      }
                    />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* F12: pending tray */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <p className="text-sm text-slate-600">
            {pendingList.length > 0 ? (
              <>
                <b>{pendingList.length}</b> order menunggu ·{" "}
                <span className="text-slate-400">
                  {autoHoldCount} saham lainnya ditahan
                </span>
              </>
            ) : (
              <span className="text-slate-400">
                Belum ada order; seluruh saham akan ditahan
              </span>
            )}
          </p>
          <button
            data-tour="execute"
            onClick={() => setConfirmOpen(true)}
            disabled={busy}
            className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Eksekusi Putaran {currentRound} →
          </button>
        </div>
      </div>

      {/* F12: explicit confirmation dialog */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="text-base font-semibold">
              Konfirmasi Putaran {currentRound}
            </h3>
            {pendingList.length > 0 ? (
              <ul className="mt-3 space-y-1.5 text-sm">
                {pendingList.map((o) => (
                  <li key={o.stock_id} className="flex justify-between">
                    <span>
                      {o.action === "buy" ? "🟢 Beli" : "🔴 Jual"}{" "}
                      <b>{metaOf(o.stock_id)?.ticker ?? o.stock_id}</b> ×{" "}
                      {o.quantity}
                    </span>
                    <span className="text-slate-500">
                      {formatRupiah(o.quantity * (prices[o.stock_id] ?? 0))}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm leading-relaxed text-slate-600">
                Tidak ada order pada putaran ini, jadi seluruh saham akan
                dicatat sebagai <b>tahan</b>. Tidak masalah; menahan juga
                keputusan investasi yang sah dan ikut dianalisis.
              </p>
            )}
            {pendingList.length > 0 && autoHoldCount > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                {autoHoldCount} saham lainnya otomatis dicatat sebagai tahan.
              </p>
            )}
            <div className="mt-5 flex gap-3">
              <button
                onClick={() => setConfirmOpen(false)}
                className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-sm"
              >
                Periksa Lagi
              </button>
              <button
                onClick={executeRound}
                disabled={busy}
                className="flex-1 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Ya, Jalankan"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// F11: order ticket with live cost preview
// ---------------------------------------------------------------------------

function OrderTicket(props: {
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
