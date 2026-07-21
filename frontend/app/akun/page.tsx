"use client";

/**
 * Manajemen Akun — profile editing, password change, data export, and account
 * withdrawal in one place.
 *
 * Username is shown but never editable: it is the login identity and the key
 * research records are grouped by. Feedback goes through toasts rather than
 * inline banners so the forms stay compact.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import Panel from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import {
  api,
  ApiError,
  download,
  type AccountInfo,
  type AccountProfile,
} from "@/lib/api";

const CONFIRM_WORD = "HAPUS";

const field =
  "w-full rounded-lg border border-edge2 bg-card px-3 py-2 text-sm text-strong " +
  "focus:border-brand focus:outline-none";
const labelCls = "block text-xs font-medium text-muted";

const GENDERS: AccountProfile["gender"][] = [
  "laki-laki",
  "perempuan",
  "lainnya",
];
const RISKS: AccountProfile["risk_profile"][] = [
  "konservatif",
  "moderat",
  "agresif",
];
const CAPABILITIES: AccountProfile["investing_capability"][] = [
  "pemula",
  "menengah",
  "berpengalaman",
];

export default function AkunPage() {
  const router = useRouter();
  const [account, setAccount] = useState<AccountInfo | null>(null);

  useEffect(() => {
    api
      .get<AccountInfo>("/api/me/account")
      .then(setAccount)
      .catch(() => router.replace("/"));
  }, [router]);

  return (
    <main className="animate-fade-in mx-auto max-w-3xl space-y-5 pb-10">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Manajemen Akun</h2>
        <p className="mt-1 text-sm text-bodytext">
          Ubah data diri, ganti kata sandi, atau unduh data Anda.
        </p>
      </div>

      <ProfileSection account={account} onSaved={setAccount} />
      <PasswordSection />
      <DataSection />
      <DangerSection onDeleted={() => router.replace("/")} />
    </main>
  );
}

// ---------------------------------------------------------------------------

function ProfileSection({
  account,
  onSaved,
}: {
  account: AccountInfo | null;
  onSaved: (a: AccountInfo) => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState<AccountProfile | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (account?.profile) setForm({ ...account.profile });
  }, [account]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    try {
      await api.patch("/api/me/profile", form);
      const fresh = await api.get<AccountInfo>("/api/me/account");
      onSaved(fresh);
      toast("Data diri tersimpan.", "success");
    } catch (err) {
      toast(
        err instanceof ApiError ? err.detail : "Data belum tersimpan. Coba lagi.",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Data Diri" subtitle="Nama pengguna tidak dapat diubah.">
      {!form ? (
        <p className="text-sm text-muted">Memuat data Anda.</p>
      ) : (
        <form onSubmit={save} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={labelCls}>
              Nama Pengguna
              <input
                value={account?.username ?? ""}
                readOnly
                disabled
                className={`${field} mt-1 cursor-not-allowed opacity-60`}
              />
            </label>
            <label className={labelCls}>
              Nama Lengkap
              <input
                className={`${field} mt-1`}
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                minLength={2}
                maxLength={128}
                required
              />
            </label>
            <label className={labelCls}>
              Usia
              <input
                type="number"
                min={17}
                max={100}
                className={`${field} tnum mt-1`}
                value={form.age}
                onChange={(e) =>
                  setForm({ ...form, age: Number(e.target.value) })
                }
                required
              />
            </label>
            <label className={labelCls}>
              Jenis Kelamin
              <select
                className={`${field} mt-1 capitalize`}
                value={form.gender}
                onChange={(e) =>
                  setForm({
                    ...form,
                    gender: e.target.value as AccountProfile["gender"],
                  })
                }
              >
                {GENDERS.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </label>
            <label className={labelCls}>
              Profil Risiko
              <select
                className={`${field} mt-1 capitalize`}
                value={form.risk_profile}
                onChange={(e) =>
                  setForm({
                    ...form,
                    risk_profile: e.target
                      .value as AccountProfile["risk_profile"],
                  })
                }
              >
                {RISKS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className={labelCls}>
              Pengalaman Investasi
              <select
                className={`${field} mt-1 capitalize`}
                value={form.investing_capability}
                onChange={(e) =>
                  setForm({
                    ...form,
                    investing_capability: e.target
                      .value as AccountProfile["investing_capability"],
                  })
                }
              >
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <Button type="submit" disabled={busy}>
            {busy ? "Menyimpan" : "Simpan Perubahan"}
          </Button>
        </form>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function PasswordSection() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);

  const mismatch = repeat.length > 0 && next !== repeat;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== repeat) {
      toast("Konfirmasi kata sandi belum sama.", "error");
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/me/password", {
        current_password: current,
        new_password: next,
      });
      setCurrent("");
      setNext("");
      setRepeat("");
      toast("Kata sandi berhasil diubah. Perangkat lain ikut keluar.", "success");
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.detail
          : "Kata sandi belum berubah. Coba lagi.",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Kata Sandi"
      subtitle="Mengganti kata sandi akan mengeluarkan perangkat lain."
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <label className={labelCls}>
            Kata Sandi Sekarang
            <input
              type="password"
              className={`${field} mt-1`}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              maxLength={128}
              required
            />
          </label>
          <label className={labelCls}>
            Kata Sandi Baru
            <input
              type="password"
              className={`${field} mt-1`}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              minLength={8}
              maxLength={128}
              required
            />
          </label>
          <label className={labelCls}>
            Ulangi Kata Sandi Baru
            <input
              type="password"
              className={`${field} mt-1`}
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              maxLength={128}
              required
            />
          </label>
        </div>
        <p className="text-xs text-muted">Minimal 8 karakter.</p>
        {mismatch && (
          <p className="text-xs text-loss">Konfirmasi belum sama.</p>
        )}
        <Button type="submit" disabled={busy || mismatch}>
          {busy ? "Menyimpan" : "Ubah Kata Sandi"}
        </Button>
      </form>
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function DataSection() {
  const toast = useToast();
  const [busy, setBusy] = useState<null | "json" | "csv">(null);

  async function downloadJson() {
    setBusy("json");
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
    } catch {
      toast("Data belum dapat diunduh. Coba lagi.", "error");
    } finally {
      setBusy(null);
    }
  }

  async function downloadCsv() {
    setBusy("csv");
    try {
      await download("/api/me/export/csv", "data_saya_cdt_csv.zip");
    } catch {
      toast("Data belum dapat diunduh. Coba lagi.", "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel
      title="Unduh Data"
      subtitle="Berisi profil, jawaban survei, seluruh sesi, dan masukan Anda."
    >
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={downloadJson} disabled={busy !== null}>
          {busy === "json" ? "Menyiapkan" : "Unduh JSON"}
        </Button>
        <Button variant="secondary" onClick={downloadCsv} disabled={busy !== null}>
          {busy === "csv" ? "Menyiapkan" : "Unduh CSV"}
        </Button>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Pilih JSON untuk satu berkas lengkap. Pilih CSV untuk berkas ZIP berisi
        satu tabel per jenis data, siap dibuka di Excel.
      </p>
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function DangerSection({ onDeleted }: { onDeleted: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await api.post("/api/me/delete");
      try {
        localStorage.removeItem("cdt_practice_v1");
        localStorage.removeItem("cdt_tour_v2");
      } catch {
        /* storage unavailable, nothing to clean */
      }
      onDeleted();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.detail : "Akun belum dapat dihapus.",
        "error",
      );
      setBusy(false);
    }
  }

  return (
    <Panel title="Hapus Akun" className="border-loss/40">
      <p className="text-sm leading-relaxed text-bodytext">
        Tindakan ini menarik Anda dari penelitian dan tidak dapat dibatalkan.
        Nama pengguna dan kata sandi dihapus permanen, jadi akun ini tidak bisa
        dipakai lagi.
      </p>
      <p className="mt-2 text-sm leading-relaxed text-bodytext">
        Data hasil latihan Anda tetap disimpan tanpa identitas, sesuai
        persetujuan penelitian di awal. Ingin salinannya? Unduh dulu di atas.
      </p>

      {!open ? (
        <Button variant="secondary" className="mt-4" onClick={() => setOpen(true)}>
          Hapus Akun Saya
        </Button>
      ) : (
        <div className="mt-4 space-y-3 rounded-lg bg-panel p-3">
          <label className="block text-sm text-bodytext">
            Ketik <b className="text-strong">{CONFIRM_WORD}</b> untuk memastikan.
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="off"
              className={`${field} mt-1`}
            />
          </label>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setOpen(false);
                setConfirm("");
              }}
            >
              Batal
            </Button>
            <Button
              variant="danger"
              onClick={remove}
              disabled={busy || confirm.trim() !== CONFIRM_WORD}
            >
              {busy ? "Menghapus" : "Ya, Hapus Akun Saya"}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}
