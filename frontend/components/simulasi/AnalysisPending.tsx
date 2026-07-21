"use client";

/**
 * AnalysisPending — the post-session screen shown while the background bias
 * pipeline runs ("analyzing"), or when it failed ("analysis_error") with a
 * retry action. Both states announce themselves to screen readers.
 */

export default function AnalysisPending(props: {
  failed: boolean;
  roundsTotal: number;
  sessionIdShort: string;
  onRetry: () => void;
}) {
  return (
    <main className="mx-auto max-w-md space-y-4 pt-6 text-center">
      <h2 className="text-lg font-semibold">Sesi Selesai 🎯</h2>
      {!props.failed ? (
        <div role="status" aria-live="polite" className="space-y-4">
          <p className="text-sm leading-relaxed text-bodytext">
            Seluruh {props.roundsTotal} putaran sudah Anda selesaikan. Tunggu
            sebentar, sistem sedang membaca pola keputusan Anda.
          </p>
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
        </div>
      ) : (
        <div role="alert" className="space-y-4">
          <p className="text-sm leading-relaxed text-bodytext">
            Keputusan Anda pada seluruh putaran sudah tersimpan dengan aman.
            Hanya tahap analisisnya yang sempat gagal, jadi cukup jalankan ulang.
          </p>
          <button
            onClick={props.onRetry}
            className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white"
          >
            Jalankan Analisis Ulang
          </button>
          <p className="text-xs text-muted">
            Bila masalah berlanjut, hubungi tim kami dengan kode sesi{" "}
            <code>{props.sessionIdShort}</code>.
          </p>
        </div>
      )}
    </main>
  );
}
