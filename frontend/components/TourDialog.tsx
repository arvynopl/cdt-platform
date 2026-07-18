"use client";

/**
 * First-visit guided tour (audit F13 — UAT testers reported confusion about
 * the flow, the confirmation model, and auto-hold). Shown automatically once
 * (localStorage flag), reopenable any time via the "?" button.
 */

import { useEffect, useState } from "react";

const STORAGE_KEY = "cdt_tour_done_v1";

const STEPS: { title: string; body: string }[] = [
  {
    title: "Apa tujuan simulasi ini?",
    body:
      "Anda mengelola dana virtual Rp 10.000.000 selama 14 putaran. Setiap " +
      "putaran mewakili satu hari perdagangan dengan data historis nyata " +
      "saham IDX. Tidak ada jawaban benar atau salah — sistem mempelajari " +
      "pola pengambilan keputusan Anda, bukan menilai keuntungan Anda.",
  },
  {
    title: "Cara memasang order",
    body:
      "Pilih saham untuk melihat grafik harganya, lalu isi tiket order: " +
      "Beli atau Jual dan jumlah lembar. Perkiraan biaya dan sisa kas Anda " +
      "dihitung langsung saat Anda mengetik, sehingga tidak perlu " +
      "menghitung manual. Order masuk ke daftar tertunda — belum dieksekusi.",
  },
  {
    title: "Eksekusi & aksi tahan otomatis",
    body:
      "Tekan tombol “Eksekusi Putaran” untuk menjalankan seluruh order " +
      "tertunda sekaligus. Saham yang tidak Anda beri order akan otomatis " +
      "dicatat sebagai “tahan” (hold) — itu juga keputusan yang sah dan " +
      "ikut dianalisis. Setelah eksekusi, simulasi maju ke hari berikutnya.",
  },
  {
    title: "Selesai 14 putaran",
    body:
      "Setelah putaran terakhir, sistem menganalisis seluruh keputusan Anda " +
      "dan menyusun profil bias perilaku beserta umpan balik yang " +
      "dipersonalisasi. Progres tersimpan otomatis — bila terputus, Anda " +
      "dapat melanjutkan dari putaran terakhir.",
  },
];

export default function TourDialog() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!localStorage.getItem(STORAGE_KEY)) setOpen(true);
  }, []);

  function close() {
    localStorage.setItem(STORAGE_KEY, "1");
    setOpen(false);
    setStep(0);
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Bantuan"
        className="fixed bottom-20 right-4 z-40 h-10 w-10 rounded-full border
                   border-slate-300 bg-white text-lg font-semibold text-brand
                   shadow-md hover:bg-brand-soft"
      >
        ?
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand">
              Panduan {step + 1} / {STEPS.length}
            </p>
            <h3 className="mt-1 text-base font-semibold">{STEPS[step].title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              {STEPS[step].body}
            </p>
            <div className="mt-5 flex items-center justify-between gap-3">
              <button
                onClick={close}
                className="text-sm text-slate-400 hover:text-slate-600"
              >
                Lewati
              </button>
              <div className="flex gap-2">
                {step > 0 && (
                  <button
                    onClick={() => setStep(step - 1)}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
                  >
                    ← Kembali
                  </button>
                )}
                {step < STEPS.length - 1 ? (
                  <button
                    onClick={() => setStep(step + 1)}
                    className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white"
                  >
                    Lanjut →
                  </button>
                ) : (
                  <button
                    onClick={close}
                    className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white"
                  >
                    Mulai Simulasi
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
