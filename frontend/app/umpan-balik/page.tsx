"use client";

/**
 * Umpan Balik — the SUS usability questionnaire plus three open questions,
 * for UAT participants. Wording of the 10 SUS statements is the validated
 * instrument from the thesis build and must not be reworded. Submissions
 * are append-only; the latest one per user is used for analysis.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

const LIKERT = [1, 2, 3, 4, 5] as const;

// Research instrument — do not reword (matches the thesis-build SUS items).
const SUS_ITEMS: [string, string][] = [
  ["sus_q1", "Saya merasa ingin sering menggunakan sistem ini."],
  ["sus_q2", "Saya merasa sistem ini terlalu rumit untuk digunakan."],
  ["sus_q3", "Saya merasa sistem ini mudah digunakan."],
  ["sus_q4", "Saya merasa membutuhkan bantuan teknis untuk dapat menggunakan sistem ini."],
  ["sus_q5", "Saya merasa berbagai fungsi dalam sistem ini terintegrasi dengan baik."],
  ["sus_q6", "Saya merasa terlalu banyak ketidakkonsistenan dalam sistem ini."],
  ["sus_q7", "Saya rasa kebanyakan orang akan dapat mempelajari sistem ini dengan cepat."],
  ["sus_q8", "Saya merasa sistem ini sangat tidak praktis untuk digunakan."],
  ["sus_q9", "Saya merasa percaya diri saat menggunakan sistem ini."],
  ["sus_q10", "Saya perlu mempelajari banyak hal sebelum dapat menggunakan sistem ini."],
];

const OPEN_ITEMS: { key: "open_confusing" | "open_useful" | "open_suggestion"; label: string; placeholder: string }[] = [
  {
    key: "open_confusing",
    label: "Adakah bagian yang membingungkan?",
    placeholder: "Ceritakan bagian yang sulit dipahami atau membuat ragu…",
  },
  {
    key: "open_useful",
    label: "Bagian mana yang paling membantu?",
    placeholder: "Fitur atau penjelasan yang menurut Anda paling berguna…",
  },
  {
    key: "open_suggestion",
    label: "Ada saran atau ide fitur?",
    placeholder: "Apa yang ingin Anda lihat ditambahkan, diubah, atau dihilangkan…",
  },
];

export default function UmpanBalikPage() {
  const router = useRouter();
  const [sus, setSus] = useState<Record<string, number>>(
    Object.fromEntries(SUS_ITEMS.map(([k]) => [k, 3])),
  );
  const [open, setOpen] = useState<Record<string, string>>({
    open_confusing: "",
    open_useful: "",
    open_suggestion: "",
  });
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.post<{ sus_score: number }>("/api/uat-feedback", {
        ...sus,
        open_confusing: open.open_confusing.trim() || null,
        open_useful: open.open_useful.trim() || null,
        open_suggestion: open.open_suggestion.trim() || null,
      });
      setSent(res.sus_score);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/");
        return;
      }
      setError(
        err instanceof ApiError
          ? err.detail
          : "Tanggapan belum tersimpan. Periksa koneksi Anda, lalu coba lagi.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (sent !== null) {
    return (
      <main className="mx-auto max-w-md space-y-4 pt-10 text-center">
        <div className="text-4xl">🙏</div>
        <h2 className="text-lg font-semibold">Terima kasih!</h2>
        <p className="text-sm leading-relaxed text-bodytext">
          Tanggapan Anda sudah tersimpan dan sangat berarti untuk perbaikan
          sistem. Bila pendapat Anda berubah setelah memakai sistem lebih
          lama, silakan isi ulang kapan saja; tanggapan terbaru yang akan
          dipakai.
        </p>
        <button
          onClick={() => router.push("/simulasi")}
          className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white"
        >
          Kembali ke Simulasi →
        </button>
      </main>
    );
  }

  return (
    <main className="animate-fade-in space-y-5 pb-10">
      <div>
        <h2 className="text-lg font-semibold">Umpan Balik Anda</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          Sepuluh pernyataan singkat ditambah tiga pertanyaan terbuka;
          seluruhnya sekitar tiga menit. Jawaban Anda dipakai murni untuk
          memperbaiki sistem, dan Anda boleh mengisi ulang kapan pun pendapat
          Anda berubah.
        </p>
      </div>

      {error && (
        <p className="rounded-lg bg-red-50 dark:bg-red-950/40 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}

      <form onSubmit={submit} className="space-y-5">
        <section className="space-y-4 rounded-xl border border-edge bg-card p-4">
          <h3 className="text-sm font-semibold">
            Bagian 1: Seberapa nyaman sistem ini digunakan?
          </h3>
          <p className="text-xs text-muted">
            Nilai 1 berarti sangat tidak setuju, nilai 5 berarti sangat setuju.
          </p>
          {SUS_ITEMS.map(([key, label]) => (
            <div key={key} className="text-sm">
              <p className="mb-1.5">{label}</p>
              <div className="flex gap-2">
                {LIKERT.map((v) => (
                  <label
                    key={v}
                    className={`flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border text-sm transition-colors ${
                      sus[key] === v
                        ? "border-brand bg-brand text-white"
                        : "border-edge2 text-bodytext hover:bg-panel"
                    }`}
                  >
                    <input
                      type="radio"
                      name={key}
                      className="sr-only"
                      checked={sus[key] === v}
                      onChange={() => setSus({ ...sus, [key]: v })}
                    />
                    {v}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </section>

        <section className="space-y-4 rounded-xl border border-edge bg-card p-4">
          <h3 className="text-sm font-semibold">
            Bagian 2: Cerita Anda (opsional)
          </h3>
          <p className="text-xs text-muted">
            Sekecil apa pun, cerita Anda membantu kami memahami angka-angka di
            atas.
          </p>
          {OPEN_ITEMS.map((item) => (
            <label key={item.key} className="block text-sm">
              {item.label}
              <textarea
                value={open[item.key]}
                onChange={(e) => setOpen({ ...open, [item.key]: e.target.value })}
                maxLength={2000}
                rows={3}
                placeholder={item.placeholder}
                className="mt-1 w-full rounded-lg border border-edge2 px-3 py-2 text-sm
                           focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              />
            </label>
          ))}
        </section>

        <button
          disabled={busy}
          className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold
                     text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {busy ? "Menyimpan…" : "Kirim Tanggapan"}
        </button>
      </form>
    </main>
  );
}
