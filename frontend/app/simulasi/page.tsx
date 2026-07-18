"use client";

/**
 * Simulasi — Fase 2.2 builds the full 14-round trading UI here (candlestick
 * chart, order ticket with live cost preview [F11], pending-order tray with
 * explicit confirmation [F12], practice round [F13]). This stub verifies the
 * auth handoff end-to-end: it proves the session cookie works by calling
 * /api/auth/me and starting/resuming a session.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type Me } from "@/lib/api";

interface SessionState {
  session_id: string;
  resumed: boolean;
  current_round: number;
  rounds_total: number;
  window_start_date: string;
  stock_ids: string[];
}

export default function SimulasiPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => router.replace("/"));
  }, [router]);

  async function startSession() {
    setError(null);
    try {
      setSession(await api.post<SessionState>("/api/sessions"));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : "Gagal terhubung ke server.",
      );
    }
  }

  if (!me) return <p className="text-sm text-slate-500">Memuat…</p>;

  return (
    <main className="space-y-4">
      <h2 className="text-lg font-semibold">Simulasi Investasi</h2>
      <p className="text-sm text-slate-600">
        Masuk sebagai <b>{me.username}</b>.
      </p>

      {error && (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {session ? (
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p>
            Sesi {session.resumed ? "dilanjutkan" : "baru"} — putaran{" "}
            <b>
              {session.current_round}/{session.rounds_total}
            </b>
            , jendela mulai {session.window_start_date},{" "}
            {session.stock_ids.length} saham.
          </p>
          <p className="mt-2 text-slate-500">
            Antarmuka perdagangan lengkap dibangun pada Fase 2.2.
          </p>
        </div>
      ) : (
        <button
          onClick={startSession}
          className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
        >
          Mulai / Lanjutkan Sesi Simulasi
        </button>
      )}
    </main>
  );
}
