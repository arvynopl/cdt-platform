"use client";

/**
 * Akun & Privasi — the UU PDP data-subject controls (audit F8):
 *  - "Unduh Data Saya": downloads everything the system holds about the user
 *    as a JSON file (data portability).
 *  - "Hapus Akun": withdrawal. The account is anonymised — identity and login
 *    are removed and the account can never sign in again, while the
 *    de-identified research data collected under consent is retained. The
 *    consequences are spelled out and a typed confirmation is required.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type Me } from "@/lib/api";

const CONFIRM_WORD = "HAPUS";

export default function AkunPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then(() => setReady(true))
      .catch(() => router.replace("/"));
  }, [router]);

  if (!ready) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        Memuat…
      </div>
    );
  }

  return (
    <main className="space-y-5 pb-10">
      <div>
        <h2 className="text-lg font-semibold">Akun &amp; Privasi</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          Anda memegang kendali atas data Anda. Di sini Anda bisa mengunduh
          seluruh data yang kami simpan, atau menarik diri dari penelitian.
        </p>
      </div>

      <ExportSection />
      <DeleteSection onDeleted={() => router.replace("/")} />
    </main>
  );
}

function ExportSection() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.get<Record<string, unknown>>("/api/me/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "data_saya_cdt.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Data belum dapat diunduh. Coba lagi sebentar.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold">Unduh Data Saya</h3>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">
        Sebuah berkas JSON berisi profil, jawaban survei, seluruh sesi, dan
        umpan balik Anda. Cocok untuk arsip pribadi atau diolah sendiri.
      </p>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <button
        onClick={download}
        disabled={busy}
        className="mt-3 rounded-lg border border-slate-300 px-4 py-2 text-sm
                   font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
      >
        {busy ? "Menyiapkan…" : "⤓ Unduh Data Saya (JSON)"}
      </button>
    </section>
  );
}

function DeleteSection({ onDeleted }: { onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/me/delete");
      // Local hygiene: drop the practice/tour flags so a future account on
      // this browser starts fresh.
      try {
        localStorage.removeItem("cdt_practice_v1");
        localStorage.removeItem("cdt_tour_v2");
      } catch {
        /* storage unavailable — nothing to clean */
      }
      onDeleted();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Akun belum dapat dihapus. Coba lagi sebentar.",
      );
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-red-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-red-700">Hapus Akun</h3>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">
        Tindakan ini menarik Anda dari penelitian dan{" "}
        <b>tidak dapat dibatalkan</b>. Identitas dan akses masuk Anda (nama
        pengguna dan kata sandi) dihapus permanen, sehingga akun ini tidak bisa
        digunakan lagi.
      </p>
      <p className="mt-2 text-sm leading-relaxed text-slate-600">
        Data hasil latihan Anda (metrik bias dan lintasan CDT) tetap disimpan
        dalam bentuk yang <b>tidak lagi bisa dikaitkan dengan Anda</b>, sesuai
        persetujuan penelitian yang Anda berikan di awal. Ingin salinannya?
        Unduh data Anda dahulu di atas.
      </p>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="mt-3 rounded-lg border border-red-300 px-4 py-2 text-sm
                     font-medium text-red-700 hover:bg-red-50"
        >
          Hapus Akun Saya…
        </button>
      ) : (
        <div className="mt-3 space-y-3 rounded-lg bg-red-50 p-3">
          <label className="block text-sm text-slate-700">
            Untuk memastikan, ketik <b>{CONFIRM_WORD}</b> di bawah ini:
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                         focus:border-red-400 focus:outline-none focus:ring-1 focus:ring-red-400"
            />
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setOpen(false);
                setConfirm("");
              }}
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm
                         font-medium text-slate-700 hover:bg-slate-100"
            >
              Batal
            </button>
            <button
              onClick={remove}
              disabled={busy || confirm.trim() !== CONFIRM_WORD}
              className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold
                         text-white hover:bg-red-700 disabled:opacity-40"
            >
              {busy ? "Menghapus…" : "Ya, hapus akun saya"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
