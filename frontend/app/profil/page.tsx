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
import { useRouter } from "next/navigation";
import PlotlyChart from "@/components/PlotlyChart";
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
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        Menyiapkan profil Anda…
      </div>
    );
  }

  if (!data.profile || data.metrics.length === 0) {
    return (
      <main className="mx-auto max-w-md space-y-4 pt-10 text-center">
        <div className="text-4xl">🧠</div>
        <h2 className="text-lg font-semibold">Profil Anda belum terbentuk</h2>
        <p className="text-sm leading-relaxed text-slate-600">
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
    <main className="space-y-5 pb-10">
      <div>
        <h2 className="text-lg font-semibold">Profil Kognitif Anda</h2>
        <p className="mt-1 text-sm text-slate-500">
          Gambaran pola pengambilan keputusan Anda yang diperbarui setelah
          setiap sesi. Semakin sering berlatih, semakin jernih potretnya.
        </p>
      </div>

      {/* Summary stats */}
      <section className="grid grid-cols-3 gap-2 rounded-xl border border-slate-200 bg-white p-4 text-center">
        <div>
          <p className="text-xs text-slate-500">Total Sesi</p>
          <p className="text-base font-semibold">{profile.session_count}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Konsistensi Pola</p>
          <p className="text-base font-semibold">
            {formatPct(profile.stability_index * 100, 0)}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Preferensi Risiko</p>
          <p className="text-base font-semibold">{rpLabel}</p>
        </div>
      </section>

      {/* Insight */}
      <section
        className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
          maxVal < 0.15
            ? "bg-emerald-50 text-emerald-900"
            : maxVal < 0.4
              ? "bg-brand-soft text-slate-700"
              : "bg-amber-50 text-amber-900"
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

      {/* Radar */}
      <section className="rounded-xl border border-slate-200 bg-white p-4">
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
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
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
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold">Metrik per Sesi</h3>
          <PlotlyChart
            data={metricLines}
            height={300}
            ariaLabel="Grafik metrik bias per sesi"
            layout={{
              yaxis: { range: [0, 1], title: { text: "Intensitas (0–1)", font: { size: 10 } } },
              legend: { orientation: "h", y: -0.2 },
            }}
          />
        </section>
      )}

      {/* CDT trajectory */}
      {snaps.length >= 2 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold">
            Perjalanan Profil Anda
          </h3>
          <p className="mb-2 text-xs text-slate-500">
            Berbeda dengan grafik per sesi di atas, garis ini adalah profil
            yang terakumulasi: setiap sesi baru menggesernya sedikit demi
            sedikit, sehingga arahnya mencerminkan kebiasaan, bukan kebetulan
            satu sesi.
          </p>
          <PlotlyChart
            data={trajectoryLines}
            height={300}
            ariaLabel="Grafik perjalanan profil CDT"
            layout={{
              yaxis: { range: [0, 1] },
              legend: { orientation: "h", y: -0.2 },
            }}
          />
        </section>
      )}

      <HistoryTable />

      <div className="flex gap-3">
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
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Riwayat Sesi</h3>
        <button
          onClick={downloadCsv}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs
                     font-medium text-slate-600 hover:bg-slate-100"
        >
          Unduh CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              {headers.map((h) => (
                <th key={h} className="py-1.5 pr-3 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100">
                {headers.map((h) => (
                  <td key={h} className="py-1.5 pr-3">
                    {r[h] == null ? "—" : String(r[h])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
