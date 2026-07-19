"use client";

/**
 * Dasbor Peneliti — the key-gated cohort inspection view. Replaces the thesis
 * build's hidden Streamlit `?view=researcher` / `?admin=` pages with a proper
 * page that talks to /api/researcher/* and /api/admin/summary.
 *
 * Access is by request header, not the session cookie:
 *   - X-Researcher-Key (required) → cohort data.
 *   - X-Admin-Token   (optional) → ops summary.
 * Both are entered once and kept in tab memory (sessionStorage), so a reload
 * doesn't re-prompt but closing the tab clears them.
 *
 * Sections: cohort KPIs, per-session bias progression, bias-intensity
 * distribution, ops summary (admin), model validation, and CSV exports of the
 * five research datasets.
 */

import { useEffect, useMemo, useState } from "react";
import PlotlyChart from "@/components/PlotlyChart";
import {
  ApiError,
  api,
  formatPct,
  keyedDownload,
  type AdminSummary,
  type CohortSummary,
  type MlPerformance,
  type ProgressionResponse,
  type ProgressionRow,
} from "@/lib/api";

const RKEY = "cdt_researcher_key";
const AKEY = "cdt_admin_token";

interface Keys {
  researcher: string;
  admin: string;
}

const BIAS_META = {
  ocs: { label: "Keyakinan Berlebih (OCS)", color: "#2563EB" },
  dei: { label: "Efek Disposisi |DEI|", color: "#9A5B00" },
  lai: { label: "Menghindari Kerugian (LAI)", color: "#B3261E" },
} as const;
const BIAS_ORDER = ["ocs", "dei", "lai"] as const;

const dec = (x: number, d = 2): string => x.toFixed(d).replace(".", ",");
const mean = (xs: number[]): number =>
  xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;

function errMsg(err: unknown): string {
  if (err instanceof ApiError)
    return err.detail || `Terjadi kesalahan (HTTP ${err.status}).`;
  return "Tidak dapat terhubung ke server. Coba lagi.";
}

// ---------------------------------------------------------------------------
// Top-level: gate vs dashboard
// ---------------------------------------------------------------------------

export default function PenelitiPage() {
  const [keys, setKeys] = useState<Keys | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const researcher = sessionStorage.getItem(RKEY) ?? "";
    const admin = sessionStorage.getItem(AKEY) ?? "";
    if (researcher) setKeys({ researcher, admin });
    setReady(true);
  }, []);

  function unlock(k: Keys) {
    sessionStorage.setItem(RKEY, k.researcher);
    if (k.admin) sessionStorage.setItem(AKEY, k.admin);
    else sessionStorage.removeItem(AKEY);
    setKeys(k);
  }

  function lock() {
    sessionStorage.removeItem(RKEY);
    sessionStorage.removeItem(AKEY);
    setKeys(null);
  }

  if (!ready) return null;
  if (!keys) return <Gate onUnlock={unlock} />;
  return <Dashboard keys={keys} onLock={lock} />;
}

// ---------------------------------------------------------------------------
// Gate
// ---------------------------------------------------------------------------

function Gate({ onUnlock }: { onUnlock: (k: Keys) => void }) {
  const [researcher, setResearcher] = useState("");
  const [admin, setAdmin] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const r = researcher.trim();
    if (!r) return;
    onUnlock({ researcher: r, admin: admin.trim() });
  }

  return (
    <main className="mx-auto max-w-md space-y-4 pt-6">
      <div>
        <h2 className="text-lg font-semibold">Dasbor Peneliti</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">
          Halaman ini menampilkan data kohort dan hanya untuk peneliti.
          Masukkan kunci akses untuk melanjutkan. Kunci disimpan sebatas di tab
          ini dan hilang saat tab ditutup.
        </p>
      </div>
      <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
        <div>
          <label htmlFor="rkey" className="block text-sm font-medium text-slate-700">
            Kunci Peneliti
          </label>
          <input
            id="rkey"
            type="password"
            autoComplete="off"
            value={researcher}
            onChange={(e) => setResearcher(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                       focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label htmlFor="akey" className="block text-sm font-medium text-slate-700">
            Token Admin <span className="font-normal text-slate-400">(opsional)</span>
          </label>
          <input
            id="akey"
            type="password"
            autoComplete="off"
            value={admin}
            onChange={(e) => setAdmin(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                       focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <p className="mt-1 text-xs text-slate-400">
            Diperlukan hanya untuk ringkasan operasional. Biarkan kosong jika
            Anda tidak memilikinya.
          </p>
        </div>
        <button
          type="submit"
          disabled={!researcher.trim()}
          className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white
                     disabled:cursor-not-allowed disabled:opacity-50"
        >
          Buka Dasbor
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

function Dashboard({ keys, onLock }: { keys: Keys; onLock: () => void }) {
  const [summary, setSummary] = useState<CohortSummary | null>(null);
  const [prog, setProg] = useState<ProgressionRow[] | null>(null);
  const [ml, setMl] = useState<MlPerformance | null>(null);
  const [admin, setAdmin] = useState<AdminSummary | null>(null);
  const [adminErr, setAdminErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    const rh = { "x-researcher-key": keys.researcher };
    setLoading(true);
    setError(null);

    Promise.all([
      api.get<CohortSummary>("/api/researcher/summary?participants_only=true", rh),
      api.get<ProgressionResponse>("/api/researcher/progression", rh),
      api.get<MlPerformance>("/api/researcher/ml-performance", rh),
    ])
      .then(([s, p, m]) => {
        if (!live) return;
        setSummary(s);
        setProg(p.progression);
        setMl(m);
      })
      .catch((err) => live && setError(errMsg(err)))
      .finally(() => live && setLoading(false));

    if (keys.admin) {
      setAdmin(null);
      setAdminErr(null);
      api
        .get<AdminSummary>("/api/admin/summary", { "x-admin-token": keys.admin })
        .then((a) => live && setAdmin(a))
        .catch((err) => live && setAdminErr(errMsg(err)));
    }

    return () => {
      live = false;
    };
  }, [keys]);

  const byBias = useMemo(() => {
    const g: Record<"dei" | "ocs" | "lai", ProgressionRow[]> = { dei: [], ocs: [], lai: [] };
    (prog ?? []).forEach((r) => g[r.bias].push(r));
    (["dei", "ocs", "lai"] as const).forEach((b) =>
      g[b].sort((a, z) => a.session_number - z.session_number),
    );
    return g;
  }, [prog]);

  const hasSessions = (prog ?? []).some((r) => r.n > 0);

  const progLines = useMemo(
    () =>
      BIAS_ORDER.map((b) => ({
        type: "scatter",
        mode: "lines+markers",
        x: byBias[b].map((r) => `Sesi ${r.session_number}`),
        y: byBias[b].map((r) => mean(r.values)),
        name: BIAS_META[b].label,
        line: { color: BIAS_META[b].color, width: 2 },
        marker: { size: 7 },
      })),
    [byBias],
  );

  const distTraces = useMemo(
    () =>
      BIAS_ORDER.map((b) => ({
        type: "histogram",
        x: byBias[b].flatMap((r) => r.values),
        name: BIAS_META[b].label,
        opacity: 0.55,
        marker: { color: BIAS_META[b].color },
        xbins: { start: 0, end: 1.0001, size: 0.1 },
      })),
    [byBias],
  );

  return (
    <main className="space-y-6 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Dasbor Peneliti</h2>
          <p className="mt-1 text-sm text-slate-500">
            Ringkasan kohort partisipan. Angka KPI dan ekspor dibatasi pada
            partisipan sah (akun uji dan non-partisipan dikecualikan).
          </p>
        </div>
        <button
          onClick={onLock}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium
                     text-slate-600 hover:bg-slate-100"
        >
          Kunci ulang
        </button>
      </div>

      {error && (
        <div className="space-y-3 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
          <p>{error}</p>
          <button
            onClick={onLock}
            className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium
                       text-red-700 hover:bg-red-100"
          >
            Ganti kunci
          </button>
        </div>
      )}

      {loading && !error && (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
          Memuat data kohort…
        </div>
      )}

      {summary && !error && (
        <>
          {/* Cohort KPIs */}
          <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Total Partisipan" value={summary.total_users} />
            <Stat label="Sesi Selesai" value={summary.total_sessions} />
            <Stat label="Partisipan ≥3 Sesi" value={summary.users_with_min_3_sessions} />
            <Stat
              label="Tingkat Penyelesaian"
              value={formatPct(summary.completion_rate * 100, 1)}
              sub="≥3 sesi / total"
            />
            <Stat label="Rata-rata |DEI|" value={dec(summary.mean_dei)} sub={`SD ${dec(summary.sd_dei)}`} />
            <Stat label="Rata-rata OCS" value={dec(summary.mean_ocs)} sub={`SD ${dec(summary.sd_ocs)}`} />
            <Stat label="Rata-rata LAI" value={dec(summary.mean_lai)} sub={`SD ${dec(summary.sd_lai)}`} />
            <Stat
              label="Konsistensi Pola"
              value={formatPct(summary.mean_stability_index * 100, 0)}
            />
          </section>
          <p className="text-xs text-slate-400">
            {summary.users_with_consent} menyetujui keikutsertaan ·{" "}
            {summary.users_with_survey} mengisi survei awal ·{" "}
            {summary.excluded_non_participants} akun non-partisipan dikecualikan.
          </p>

          {/* Progression + distribution */}
          {hasSessions ? (
            <>
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="mb-1 text-sm font-semibold">Progres Bias per Sesi</h3>
                <p className="mb-2 text-xs text-slate-500">
                  Rata-rata intensitas tiap bias pada urutan sesi ke-n
                  lintas partisipan. Berguna melihat apakah bias mereda seiring
                  latihan.
                </p>
                <PlotlyChart
                  data={progLines}
                  height={300}
                  ariaLabel="Grafik progres bias kohort per sesi"
                  layout={{
                    yaxis: { range: [0, 1], title: { text: "Intensitas (0–1)", font: { size: 10 } } },
                    legend: { orientation: "h", y: -0.2 },
                  }}
                />
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="mb-1 text-sm font-semibold">Distribusi Intensitas Bias</h3>
                <p className="mb-2 text-xs text-slate-500">
                  Sebaran intensitas seluruh sesi tercatat, dikelompokkan per
                  0,1. Puncak di kiri berarti mayoritas sesi berbias rendah.
                </p>
                <PlotlyChart
                  data={distTraces}
                  height={300}
                  ariaLabel="Histogram distribusi intensitas bias"
                  layout={{
                    barmode: "overlay",
                    xaxis: { range: [0, 1], title: { text: "Intensitas (0–1)", font: { size: 10 } } },
                    yaxis: { title: { text: "Jumlah sesi", font: { size: 10 } } },
                    legend: { orientation: "h", y: -0.2 },
                  }}
                />
              </section>
            </>
          ) : (
            <section className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
              Belum ada sesi selesai pada kohort. Grafik akan muncul setelah
              partisipan menyelesaikan sesi pertama.
            </section>
          )}

          {/* Admin ops summary */}
          {keys.admin && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">Ringkasan Operasional</h3>
              {adminErr ? (
                <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  {adminErr}
                </div>
              ) : admin ? (
                <AdminCards admin={admin} />
              ) : (
                <p className="text-sm text-slate-400">Memuat ringkasan operasional…</p>
              )}
            </section>
          )}

          {/* Model validation */}
          <MlSection ml={ml} />

          {/* Dataset exports */}
          <Downloads researcherKey={keys.researcher} />
        </>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

function AdminCards({ admin }: { admin: AdminSummary }) {
  const sus = admin.avg_sus_score;
  const susTone =
    sus == null
      ? "border-slate-200"
      : sus >= 68
        ? "border-emerald-300 bg-emerald-50"
        : "border-amber-300 bg-amber-50";
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className={`rounded-xl border p-4 ${susTone}`}>
          <p className="text-xs text-slate-500">Rata-rata SUS</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {sus == null ? "—" : dec(sus, 1)}
          </p>
          <p className="mt-0.5 text-xs text-slate-400">Target ≥68 · skripsi 64,0</p>
        </div>
        <Stat label="Umpan Balik UAT" value={admin.total_uat_feedback} />
        <Stat
          label="Galat Sesi"
          value={admin.total_session_errors}
          sub={`${dec(admin.error_rate_per_session * 100, 1)}% per sesi`}
        />
        <Stat label="Baris Metrik Bias" value={admin.total_bias_metrics} />
      </div>
      <div className="mt-2 rounded-xl border border-slate-200 bg-white p-4">
        <p className="mb-2 text-xs font-medium text-slate-500">Sesi menurut status</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(admin.sessions_by_status).length === 0 ? (
            <span className="text-xs text-slate-400">Belum ada sesi.</span>
          ) : (
            Object.entries(admin.sessions_by_status).map(([status, count]) => (
              <span
                key={status}
                className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
              >
                {status}: <b className="tabular-nums">{count}</b>
              </span>
            ))
          )}
        </div>
      </div>
    </>
  );
}

function MlSection({ ml }: { ml: MlPerformance | null }) {
  if (!ml) return null;
  if (!ml.available) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="mb-1 text-sm font-semibold">Validasi Model</h3>
        <p className="text-sm text-slate-500">
          Belum ada laporan validasi model. Jalankan skrip validasi ML untuk
          mengisinya, lalu muat ulang halaman ini.
        </p>
      </section>
    );
  }
  const summaryEntries = Object.entries(ml.summary ?? {}).filter(
    ([k]) => k !== "generated_at",
  );
  const report = ml.classification_report ?? [];
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold">Validasi Model</h3>
      {ml.generated_at && (
        <p className="mb-2 text-xs text-slate-400">Dibuat {ml.generated_at}</p>
      )}
      {summaryEntries.length > 0 && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {summaryEntries.map(([k, v]) => (
            <div key={k} className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-xs text-slate-500">{k}</p>
              <p className="text-sm font-semibold tabular-nums">{String(v)}</p>
            </div>
          ))}
        </div>
      )}
      {report.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                {Object.keys(report[0]).map((h) => (
                  <th key={h} className="py-1.5 pr-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.map((row, i) => (
                <tr key={i} className="border-b border-slate-100">
                  {Object.keys(report[0]).map((h) => (
                    <td key={h} className="py-1.5 pr-3 tabular-nums">
                      {row[h] === "" || row[h] == null ? "—" : row[h]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const DATASETS = [
  { slug: "users", label: "Data partisipan", file: "cohort_users" },
  { slug: "sessions", label: "Semua sesi", file: "all_sessions" },
  { slug: "cdt-snapshots", label: "Snapshot CDT longitudinal", file: "cdt_snapshots" },
  { slug: "uat-feedback", label: "Umpan balik UAT (SUS)", file: "uat_feedback" },
  { slug: "post-session-surveys", label: "Survei pascasesi", file: "post_session_surveys" },
] as const;

function Downloads({ researcherKey }: { researcherKey: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function download(slug: string, file: string) {
    setBusy(slug);
    setErr(null);
    try {
      await keyedDownload(
        `/api/researcher/export/${slug}?format=csv&participants_only=true`,
        { "x-researcher-key": researcherKey },
        `${file}.csv`,
      );
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold">Ekspor Dataset</h3>
      <p className="mb-3 text-xs text-slate-500">
        Unduh CSV (partisipan sah). Cocok diolah lanjut di Python atau
        spreadsheet.
      </p>
      <div className="flex flex-wrap gap-2">
        {DATASETS.map((d) => (
          <button
            key={d.slug}
            onClick={() => download(d.slug, d.file)}
            disabled={busy !== null}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium
                       text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            {busy === d.slug ? "Menyiapkan…" : `⤓ ${d.label}`}
          </button>
        ))}
      </div>
      {err && <p className="mt-2 text-xs text-red-600">{err}</p>}
    </section>
  );
}
