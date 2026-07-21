"use client";

/**
 * Profil Kognitif — the user's Cognitive Digital Twin, rendered from
 * GET /api/me/profile:
 *
 *  - summary stats (sessions, stability index, risk-preference label),
 *  - dual radar: last session vs personal average, with the scientific
 *    severe-threshold ring and the personal watchpoint ring (mean + 1 SD
 *    of the user's own history; falls back to the scientific ring until
 *    three sessions exist),
 *  - per-session bias metric lines,
 *  - EMA-updated CDT trajectory from the longitudinal snapshots,
 *  - session history table with client-side CSV download (NFR07).
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import PlotlyChart from "@/components/PlotlyChart";
import Term from "@/components/Term";
import { Skeleton, SkeletonChart } from "@/components/Skeleton";
import {
  api,
  ApiError,
  formatPct,
  type HistoryResponse,
  type ProfileResponse,
} from "@/lib/api";

const BIAS_AXIS = [
  "Efek Disposisi",
  "Keyakinan Berlebih",
  "Menghindari Kerugian",
];

const BIAS_NAMES: Record<string, string> = {
  overconfidence: "Keyakinan Berlebih (Overconfidence)",
  disposition: "Efek Disposisi (Disposition Effect)",
  loss_aversion: "Menghindari Kerugian (Loss Aversion)",
};

export default function ProfilPage() {
  const router = useRouter();
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ProfileResponse>("/api/me/profile")
      .then(setData)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/");
        else setError("Profil belum dapat dimuat. Coba muat ulang halaman ini.");
      });
  }, [router]);

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 dark:bg-red-950/40 px-4 py-3 text-sm text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-5" role="status" aria-label="Memuat profil">
        <div className="grid grid-cols-3 gap-2 rounded-xl border border-edge bg-card p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="space-y-2 text-center">
              <Skeleton className="mx-auto h-3 w-16" />
              <Skeleton className="mx-auto h-5 w-10" />
            </div>
          ))}
        </div>
        <SkeletonChart height={360} />
        <SkeletonChart height={340} />
      </div>
    );
  }

  if (!data.profile || data.metrics.length === 0) {
    return (
      <main className="mx-auto max-w-md space-y-4 pt-10 text-center">
        <div className="text-4xl">🧠</div>
        <h2 className="text-lg font-semibold">Profil Anda belum terbentuk</h2>
        <p className="text-sm leading-relaxed text-bodytext">
          Profil kognitif tersusun dari keputusan Anda selama simulasi.
          Selesaikan sesi pertama, dan halaman ini akan mulai bercerita.
        </p>
        <button
          onClick={() => router.push("/simulasi")}
          className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white"
        >
          Mulai Sesi Pertama →
        </button>
      </main>
    );
  }

  return <ProfileContent data={data} />;
}

function ProfileContent({ data }: { data: ProfileResponse }) {
  const router = useRouter();
  const profile = data.profile!;
  const metrics = data.metrics;
  const latest = metrics[metrics.length - 1];

  const rp = profile.risk_preference;
  const rpLabel = rp >= 0.6 ? "Agresif" : rp >= 0.3 ? "Moderat" : "Konservatif";

  // -- radar ---------------------------------------------------------------
  const radar = useMemo(() => {
    const close = <T,>(v: T[]): T[] => [...v, v[0]];
    const axes = close([...BIAS_AXIS]);

    const current = [latest.dei, latest.ocs, latest.lai_norm];
    const n = metrics.length;
    const avg = [
      metrics.reduce((s, m) => s + m.dei, 0) / n,
      metrics.reduce((s, m) => s + m.ocs, 0) / n,
      metrics.reduce((s, m) => s + m.lai_norm, 0) / n,
    ];
    const sci = data.thresholds.scientific;
    const sciRing = [sci.dei, sci.ocs, sci.lai];
    const personal = data.thresholds.personal;
    const persRing = personal
      ? [personal.values.dei, personal.values.ocs, personal.values.lai]
      : sciRing;

    return [
      {
        type: "scatterpolar", r: close(sciRing), theta: axes,
        name: "Ambang waspada ilmiah", mode: "lines",
        line: { color: "#B3261E", width: 1.5 },
      },
      {
        type: "scatterpolar", r: close(persRing), theta: axes,
        name: personal?.is_fallback
          ? "Ambang pribadi (sementara = ilmiah)"
          : "Ambang waspada pribadi",
        mode: "lines", line: { color: "#2563EB", width: 1.5, dash: "dot" },
      },
      {
        type: "scatterpolar", r: close(avg), theta: axes,
        name: "Rata-rata Anda", fill: "toself",
        fillcolor: "rgba(154, 91, 0, 0.08)",
        line: { color: "#9A5B00", width: 1.5 },
      },
      {
        type: "scatterpolar", r: close(current), theta: axes,
        name: "Sesi terakhir", fill: "toself",
        fillcolor: "rgba(37, 99, 235, 0.15)",
        line: { color: "#2563EB", width: 2 },
      },
    ];
  }, [data, latest, metrics]);

  // -- line charts ---------------------------------------------------------
  const sessions = metrics.map((m) => `Sesi ${m.session_num}`);
  const metricLines = [
    { y: metrics.map((m) => m.ocs), name: "Keyakinan Berlebih (OCS)", color: "#2563EB" },
    { y: metrics.map((m) => m.dei), name: "Efek Disposisi |DEI|", color: "#9A5B00" },
    { y: metrics.map((m) => m.lai_norm), name: "Menghindari Kerugian (LAI)", color: "#B3261E" },
  ].map((t) => ({
    type: "scatter", mode: "lines+markers", x: sessions, y: t.y,
    name: t.name, line: { color: t.color, width: 2 }, marker: { size: 7 },
  }));

  const snaps = data.cdt_snapshots;
  const snapX = snaps.map((s) => `Sesi ${s.session_number}`);
  const trajectoryLines = [
    { y: snaps.map((s) => s.cdt_overconfidence), name: "Keyakinan Berlebih", color: "#2563EB" },
    { y: snaps.map((s) => s.cdt_disposition), name: "Efek Disposisi", color: "#9A5B00" },
    { y: snaps.map((s) => s.cdt_loss_aversion), name: "Menghindari Kerugian", color: "#B3261E" },
  ].map((t) => ({
    type: "scatter", mode: "lines+markers", x: snapX, y: t.y,
    name: t.name, line: { color: t.color, width: 2 }, marker: { size: 7 },
  }));

  // -- insight -------------------------------------------------------------
  const bv = profile.bias_intensity_vector;
  const maxKey = (Object.keys(bv) as (keyof typeof bv)[]).reduce((a, b) =>
    bv[a] >= bv[b] ? a : b,
  );
  const maxVal = bv[maxKey];

  return (
    <main className="animate-fade-in space-y-5 pb-10">
      <div>
        <h2 className="text-lg font-semibold">Profil Kognitif Anda</h2>
        <p className="mt-1 text-sm text-muted">
          Gambaran pola pengambilan keputusan Anda yang diperbarui setelah
          setiap sesi. Semakin sering berlatih, semakin jernih potretnya.
        </p>
      </div>

      {/* Summary stats */}
      <section className="grid grid-cols-3 gap-2 rounded-xl border border-edge bg-card p-4 text-center">
        <div>
          <p className="text-xs text-muted">Total Sesi</p>
          <p className="text-base font-semibold">{profile.session_count}</p>
        </div>
        <div>
          <p className="text-xs text-muted">
            <Term id="stability">Konsistensi Pola</Term>
          </p>
          <p className="text-base font-semibold">
            {formatPct(profile.stability_index * 100, 0)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Preferensi Risiko</p>
          <p className="text-base font-semibold">{rpLabel}</p>
        </div>
      </section>

      {/* Value-aware interpretation of the summary numbers (openable). */}
      <details className="group rounded-xl border border-edge bg-card px-4 py-3">
        <summary className="cursor-pointer list-none text-sm font-medium text-strong marker:hidden">
          <span className="text-brand group-open:hidden">＋ </span>
          <span className="hidden text-brand group-open:inline">－ </span>
          Apa arti angka ini?
        </summary>
        <div className="mt-2 space-y-2 text-sm leading-relaxed text-bodytext">
          <p>
            <b>Konsistensi Pola {formatPct(profile.stability_index * 100, 0)}</b>{" "}
            —{" "}
            {profile.stability_index >= 0.7
              ? "pola keputusan Anda relatif menetap antar sesi, jadi profil di bawah bisa Anda percaya lebih kuat."
              : profile.stability_index >= 0.4
                ? "pola Anda sudah mulai terbentuk tetapi masih bergerak; beberapa sesi lagi akan memperjelasnya."
                : "pola Anda masih berubah-ubah — hal yang wajar pada sesi-sesi awal ketika datanya belum banyak."}
          </p>
          <p>
            <b>Preferensi Risiko: {rpLabel}</b> —{" "}
            {rp >= 0.6
              ? "berdasarkan keputusan Anda selama simulasi, Anda cenderung bersedia menanggung fluktuasi besar demi potensi imbal hasil lebih tinggi."
              : rp >= 0.3
                ? "berdasarkan keputusan Anda selama simulasi, Anda cenderung menyeimbangkan potensi imbal hasil dengan kestabilan modal."
                : "berdasarkan keputusan Anda selama simulasi, Anda cenderung memprioritaskan menjaga modal di atas mengejar imbal hasil tinggi."}
          </p>
        </div>
      </details>

      {/* Insight */}
      <section
        className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
          maxVal < 0.15
            ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-900 dark:text-emerald-200"
            : maxVal < 0.4
              ? "bg-brand-soft text-strong"
              : "bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200"
        }`}
      >
        {maxVal < 0.15 ? (
          <>
            Sejauh ini pola keputusan Anda tergolong sehat; tidak ada bias yang
            menonjol. Pertahankan cara Anda menimbang setiap keputusan.
          </>
        ) : maxVal < 0.4 ? (
          <>
            Kecenderungan yang paling terlihat saat ini adalah{" "}
            <b>{BIAS_NAMES[maxKey]}</b> dengan intensitas{" "}
            {maxVal.toFixed(2).replace(".", ",")}. Masih tergolong ringan,
            tetapi layak Anda pantau pada sesi-sesi berikutnya.
          </>
        ) : (
          <>
            <b>{BIAS_NAMES[maxKey]}</b> tampil cukup kuat pada profil Anda
            (intensitas {maxVal.toFixed(2).replace(".", ",")}). Cobalah baca
            kembali rekomendasi pada halaman hasil sesi terakhir, lalu uji pada
            sesi berikutnya.
          </>
        )}
      </section>

      {/* Cross-bias interaction (rendered only when ≥3 sessions produced scores) */}
      <InteractionSection scores={profile.interaction_scores} />

      {/* Radar */}
      <section className="rounded-xl border border-edge bg-card p-4">
        <h3 className="mb-1 text-sm font-semibold">Peta Bias Anda</h3>
        <PlotlyChart
          data={radar}
          height={360}
          ariaLabel="Radar profil bias"
          layout={{
            polar: { radialaxis: { range: [0, 1], tickfont: { size: 9 } } },
            legend: { orientation: "h", y: -0.12 },
          }}
        />
        <p className="mt-1 text-xs leading-relaxed text-muted">
          Biru pekat menunjukkan sesi terakhir, cokelat rata-rata seluruh sesi
          Anda. Garis merah adalah ambang waspada dari literatur, sedangkan
          garis biru putus-putus adalah ambang pribadi Anda (rata-rata riwayat
          ditambah satu simpangan baku
          {data.thresholds.personal?.is_fallback
            ? "; masih memakai ambang ilmiah sampai Anda menyelesaikan tiga sesi"
            : ""}
          ).
        </p>
      </section>

      {/* Per-session metrics */}
      {metrics.length >= 2 && (
        <section className="rounded-xl border border-edge bg-card p-4">
          <h3 className="mb-1 text-sm font-semibold">Metrik per Sesi</h3>
          <PlotlyChart
            data={metricLines}
            height={340}
            ariaLabel="Grafik metrik bias per sesi"
            layout={{
              margin: { l: 56, r: 20, t: 24, b: 64 },
              yaxis: { range: [0, 1], title: { text: "Intensitas (0–1)", font: { size: 10 } } },
              legend: { orientation: "h", y: -0.28 },
            }}
          />
        </section>
      )}

      {/* CDT trajectory */}
      {snaps.length >= 2 && (
        <section className="rounded-xl border border-edge bg-card p-4">
          <h3 className="mb-1 text-sm font-semibold">
            Perjalanan Profil Anda
          </h3>
          <p className="mb-2 text-xs text-muted">
            Berbeda dengan grafik per sesi di atas, garis ini adalah profil
            yang terakumulasi: setiap sesi baru menggesernya sedikit demi
            sedikit, sehingga arahnya mencerminkan kebiasaan, bukan kebetulan
            satu sesi.
          </p>
          <PlotlyChart
            data={trajectoryLines}
            height={340}
            ariaLabel="Grafik perjalanan profil CDT"
            layout={{
              margin: { l: 48, r: 20, t: 24, b: 64 },
              yaxis: { range: [0, 1] },
              legend: { orientation: "h", y: -0.28 },
            }}
          />
        </section>
      )}

      <HistoryTable />

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() =>
            router.push(`/hasil?sid=${latest.session_id}&review=1`)
          }
          className="flex-1 rounded-lg border border-edge2 px-4 py-2.5
                     text-sm font-medium text-strong hover:bg-panel"
        >
          Lihat Hasil Sesi Terakhir
        </button>
        <button
          onClick={() => router.push("/simulasi")}
          className="flex-1 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white"
        >
          Mulai Sesi Baru →
        </button>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Cross-bias interaction readout
//
// Renders the already-computed CognitiveProfile.interaction_scores (pairwise
// Pearson r between OCS, |DEI|, normalised LAI over the recent-session window).
// Read-only presentation of an existing metric — no new computation, so it does
// not touch the parity-frozen pipeline. The backend returns scores only after
// three sessions (and null per-pair when a series has no variance), so this
// section self-hides until there is something meaningful to show.
// The 0.65 "erat" cutoff mirrors the backend's _INTERACTION_THRESHOLD (Cohen 1988).
// ---------------------------------------------------------------------------

const INTERACTION_PAIRS: {
  key: string;
  label: string;
  strong: (positive: boolean) => string;
}[] = [
  {
    key: "ocs_dei",
    label: "Keyakinan Berlebih ↔ Efek Disposisi",
    strong: (pos) =>
      pos
        ? "Saat Anda banyak bertransaksi, kecenderungan menjual saham yang untung terlalu cepat ikut menguat. Coba beri ruang lebih bagi posisi yang sedang menguntungkan."
        : "Menariknya, saat transaksi Anda meningkat, Anda justru lebih sabar menahan posisi yang untung — sebuah tanda kehati-hatian.",
  },
  {
    key: "ocs_lai",
    label: "Keyakinan Berlebih ↔ Menghindari Kerugian",
    strong: (pos) =>
      pos
        ? "Makin sering Anda bertransaksi, makin lama pula Anda menahan posisi yang rugi. Kombinasi ini dapat menggerus modal; pertimbangkan batas kerugian yang jelas."
        : "Saat aktif bertransaksi, Anda justru lebih disiplin memotong kerugian — kebiasaan yang sehat.",
  },
  {
    key: "dei_lai",
    label: "Efek Disposisi ↔ Menghindari Kerugian",
    strong: (pos) =>
      pos
        ? "Dua pola saling memperkuat: menjual yang untung terlalu cepat sekaligus menahan yang rugi terlalu lama. Dampaknya ke portofolio lebih besar daripada masing-masing sendiri."
        : "Kedua kebiasaan ini cenderung saling mengimbangi, bukan muncul bersamaan.",
  },
];

function InteractionSection({
  scores,
}: {
  scores: Record<string, number | null> | null;
}) {
  // Nothing to show until the backend has produced scores (≥3 sessions) and at
  // least one pair has a defined correlation.
  if (!scores || INTERACTION_PAIRS.every((p) => scores[p.key] == null)) return null;

  const strengthLabel = (r: number) =>
    Math.abs(r) >= 0.65 ? "erat" : Math.abs(r) >= 0.3 ? "sedang" : "lemah";
  const fmt = (r: number) => {
    const s = r.toFixed(2).replace(".", ",");
    return r > 0 ? `+${s}` : s;
  };

  return (
    <section className="rounded-xl border border-edge bg-card p-4">
      <h3 className="mb-1 text-sm font-semibold">
        <Term id="interaction">Keterkaitan Antar-Bias</Term>
      </h3>
      <p className="mb-3 text-xs leading-relaxed text-muted">
        Selain seberapa kuat tiap bias, penting melihat apakah beberapa bias
        cenderung muncul bersamaan. Angka berikut mengukur keterkaitan pola Anda
        selama beberapa sesi terakhir (−1 sampai +1; makin jauh dari nol, makin
        erat kaitannya).
      </p>
      <ul className="space-y-2.5">
        {INTERACTION_PAIRS.map((p) => {
          const r = scores[p.key];
          const isStrong = r != null && Math.abs(r) >= 0.65;
          return (
            <li
              key={p.key}
              className={`rounded-lg px-3 py-2 text-sm ${
                isStrong ? "bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200" : "bg-panel text-strong"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{p.label}</span>
                <span className="whitespace-nowrap font-mono text-xs">
                  {r == null ? "—" : `${fmt(r)} (${strengthLabel(r)})`}
                </span>
              </div>
              {isStrong && (
                <p className="mt-1 text-xs leading-relaxed">{p.strong(r! > 0)}</p>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Keterkaitan mulai dihitung setelah tiga sesi. Tanda “—” berarti ragam
        data pada sesi-sesi tersebut belum cukup untuk menyimpulkan keterkaitan.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// History table + CSV download (NFR07)
// ---------------------------------------------------------------------------

function HistoryTable() {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);

  useEffect(() => {
    api
      .get<HistoryResponse>("/api/me/history")
      .then((r) => setRows(r.rows))
      .catch(() => setRows([]));
  }, []);

  if (!rows || rows.length === 0) return null;

  const headers = Object.keys(rows[0]);

  function downloadCsv() {
    const esc = (v: unknown) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [
      headers.join(","),
      ...rows!.map((r) => headers.map((h) => esc(r[h])).join(",")),
    ].join("\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "riwayat_sesi_cdt.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <section className="rounded-xl border border-edge bg-card p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Riwayat Sesi</h3>
        <button
          onClick={downloadCsv}
          className="rounded-lg border border-edge2 px-3 py-1.5 text-xs
                     font-medium text-bodytext hover:bg-panel"
        >
          Unduh CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead>
            <tr className="border-b border-edge text-muted">
              {headers.map((h) => (
                <th key={h} className="py-1.5 pr-3 font-medium">
                  {h}
                </th>
              ))}
              <th className="py-1.5 font-medium">Hasil</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-edge">
                {headers.map((h) => (
                  <td key={h} className="py-1.5 pr-3">
                    {r[h] == null ? "—" : String(r[h])}
                  </td>
                ))}
                <td className="py-1.5 whitespace-nowrap">
                  {r.session_id ? (
                    <Link
                      href={`/hasil?sid=${String(r.session_id)}&review=1`}
                      className="font-medium text-brand hover:underline"
                    >
                      Lihat →
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
