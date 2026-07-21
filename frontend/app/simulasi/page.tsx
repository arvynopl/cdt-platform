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
import CoachTour from "@/components/CoachTour";
import PracticeMode, { TOUR_STEPS } from "@/components/PracticeMode";
import AnalysisPending from "@/components/simulasi/AnalysisPending";
import ConfirmRoundDialog from "@/components/simulasi/ConfirmRoundDialog";
import HelpMenu from "@/components/simulasi/HelpMenu";
import PortfolioSummary from "@/components/simulasi/PortfolioSummary";
import StockCard from "@/components/simulasi/StockCard";
import {
  api,
  ApiError,
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
          <div
            role="alert"
            className="rounded-lg bg-red-50 dark:bg-red-950/40 px-4 py-3 text-sm text-red-700 dark:text-red-300"
          >
            {error}
          </div>
        ) : (
          <div
            role="status"
            className="flex items-center gap-3 text-sm text-muted"
          >
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
            Menyiapkan sesi Anda…
          </div>
        )}
      </main>
    );
  }

  if (phase === "analyzing" || phase === "analysis_error") {
    return (
      <AnalysisPending
        failed={phase === "analysis_error"}
        roundsTotal={state.rounds_total}
        sessionIdShort={state.session_id.slice(0, 8)}
        onRetry={retryAnalysis}
      />
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

      <HelpMenu
        open={helpOpen}
        onToggle={() => setHelpOpen((v) => !v)}
        onReplayTour={() => {
          setHelpOpen(false);
          setTourOpen(true);
        }}
        onReplayPractice={() => {
          setHelpOpen(false);
          setPracticeReplay(true);
        }}
      />

      <PortfolioSummary
        currentRound={currentRound}
        roundsTotal={state.rounds_total}
        resumed={state.resumed}
        cash={state.portfolio.cash}
        totalValue={state.portfolio.total_value}
        returnPct={returnPct}
      />

      {(error || roundErrors.length > 0) && (
        <div
          role="alert"
          className="space-y-1 rounded-lg bg-amber-50 dark:bg-amber-950/40 px-4 py-3 text-sm text-amber-800 dark:text-amber-300"
        >
          {error && <p>{error}</p>}
          {roundErrors.map((e, i) => (
            <p key={i}>
              {e}{" "}
              <span className="text-amber-600 dark:text-amber-400">
                (order tersebut dicatat sebagai tahan)
              </span>
            </p>
          ))}
        </div>
      )}

      {/* Stock list — keyed by round so every ticket remounts clean */}
      <section key={currentRound} data-tour="stocks" className="grid gap-2 sm:grid-cols-2">
        {state.stock_ids.map((sid) => {
          const price = prices[sid];
          const change = ((price - prevPrices[sid]) / prevPrices[sid]) * 100;
          return (
            <StockCard
              key={sid}
              meta={metaOf(sid)}
              fallbackId={sid}
              price={price}
              change={change}
              held={heldQty(sid)}
              order={pending[sid]}
              isOpen={selected === sid}
              onToggle={() => setSelected(selected === sid ? null : sid)}
              preHistory={state.pre_window_history[sid] ?? []}
              windowData={state.window[sid]}
              revealedRounds={currentRound}
              spendableCash={spendableCash}
              onSetOrder={(o) =>
                setPending((p) =>
                  o === null
                    ? Object.fromEntries(
                        Object.entries(p).filter(([k]) => k !== sid),
                      )
                    : { ...p, [sid]: { ...o, stock_id: sid } },
                )
              }
            />
          );
        })}
      </section>

      {/* F12: pending tray */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-edge bg-card/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <p className="text-sm text-bodytext">
            {pendingList.length > 0 ? (
              <>
                <b>{pendingList.length}</b> order menunggu ·{" "}
                <span className="text-muted">
                  {autoHoldCount} saham lainnya ditahan
                </span>
              </>
            ) : (
              <span className="text-muted">
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

      {confirmOpen && (
        <ConfirmRoundDialog
          currentRound={currentRound}
          pendingList={pendingList}
          autoHoldCount={autoHoldCount}
          metaOf={metaOf}
          prices={prices}
          busy={busy}
          onClose={() => setConfirmOpen(false)}
          onConfirm={executeRound}
        />
      )}
    </main>
  );
}
