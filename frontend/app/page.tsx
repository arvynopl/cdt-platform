"use client";

/**
 * Beranda — username-first auth flow (same UX contract as the thesis build):
 * step 1 asks only the username, then routes to login or registration based
 * on /api/auth/check-username. On success the session cookie is set by the
 * backend and we navigate to the simulation.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, type Me, type RegisterPayload } from "@/lib/api";

type Stage = "username" | "login" | "register";

const LIKERT = [1, 2, 3, 4, 5] as const;
const LIKERT_LABELS: Record<number, string> = {
  1: "1 — Sangat Tidak Setuju",
  2: "2 — Tidak Setuju",
  3: "3 — Netral",
  4: "4 — Setuju",
  5: "5 — Sangat Setuju",
};

// 9 onboarding items — 3 per bias (DEI, OCS, LAI); wording identical to the
// research-validated instrument in the thesis build.
const ONBOARDING_ITEMS: [keyof RegisterPayload["onboarding_survey"], string][] = [
  ["dei_q1", "Saya cenderung menjual saham saat sudah untung, walaupun mungkin masih bisa naik."],
  ["dei_q2", "Saya sering menahan saham yang sedang rugi karena yakin harganya akan pulih."],
  ["dei_q3", "Saya merasa lega setelah merealisasikan keuntungan, bahkan yang kecil."],
  ["ocs_q1", "Saya yakin keputusan investasi saya umumnya lebih baik daripada rata-rata investor lain."],
  ["ocs_q2", "Saya merasa perlu sering melakukan transaksi untuk memperoleh hasil yang optimal."],
  ["ocs_q3", "Saya percaya kemampuan saya membaca pergerakan pasar jangka pendek cukup tajam."],
  ["lai_q1", "Saya merasa sangat terganggu ketika portofolio saya mengalami kerugian sementara."],
  ["lai_q2", "Rasa sakit dari kerugian terasa jauh lebih kuat dibandingkan kesenangan dari keuntungan setara."],
  ["lai_q3", "Saya cenderung menunda menjual saham yang rugi karena takut mengunci kerugian."],
];

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm " +
  "focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand";
const btnCls =
  "w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white " +
  "hover:bg-blue-700 disabled:opacity-50";
const btnGhostCls =
  "w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm " +
  "font-medium text-slate-600 hover:bg-slate-100";

export default function BerandaPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("username");
  const [username, setUsername] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitUsername(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const clean = username.trim();
    if (clean.length < 2) {
      setError("Nama pengguna harus minimal 2 karakter.");
      return;
    }
    setBusy(true);
    try {
      const { exists } = await api.post<{ exists: boolean }>(
        "/api/auth/check-username",
        { username: clean },
      );
      setUsername(clean);
      setStage(exists ? "login" : "register");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Sambungan ke server terputus. Periksa koneksi Anda, lalu coba lagi.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md">
      <h2 className="mb-1 text-lg font-semibold">Selamat datang!</h2>
      <p className="mb-6 text-sm leading-relaxed text-slate-500">
        Masukkan nama pengguna Anda untuk mulai. Kalau Anda baru pertama kali
        di sini, kami akan memandu pendaftaran singkat, kurang dari dua menit.
      </p>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {stage === "username" && (
        <>
          <form onSubmit={submitUsername} className="space-y-4">
            <label className="block text-sm font-medium">
              Nama Pengguna
              <input
                className={`${inputCls} mt-1`}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                maxLength={64}
                placeholder="Contoh: jaka.santoso"
                autoFocus
              />
            </label>
            <button className={btnCls} disabled={busy}>
              {busy ? "Memeriksa…" : "Lanjutkan →"}
            </button>
          </form>
          <ValueProp />
        </>
      )}

      {stage === "login" && (
        <LoginForm
          username={username}
          onBack={() => setStage("username")}
          onError={setError}
          onSuccess={() => router.push("/simulasi")}
        />
      )}

      {stage === "register" && (
        <RegisterForm
          username={username}
          onBack={() => setStage("username")}
          onError={setError}
          onSuccess={() => router.push("/simulasi")}
        />
      )}
    </main>
  );
}

// First-time-visitor value proposition, shown only on the username step.
const VALUE_POINTS: [string, string, string][] = [
  ["🎮", "Berlatih tanpa risiko", "Simulasikan keputusan jual-beli dengan data harga nyata — tanpa uang sungguhan."],
  ["🧠", "Kenali pola Anda", "Sistem memetakan kecenderungan seperti menjual untung terlalu cepat atau menahan rugi terlalu lama."],
  ["📈", "Tumbuh tiap sesi", "Setiap sesi menajamkan profil Anda dan memberi umpan balik yang bisa langsung dicoba."],
];

function ValueProp() {
  return (
    <section className="animate-fade-in mt-8 border-t border-slate-200 pt-6">
      <h3 className="text-sm font-semibold text-slate-700">
        Apa yang Anda dapatkan di sini?
      </h3>
      <ul className="mt-3 space-y-3">
        {VALUE_POINTS.map(([icon, title, body]) => (
          <li key={title} className="flex gap-3">
            <span aria-hidden className="text-xl leading-none">
              {icon}
            </span>
            <div>
              <p className="text-sm font-medium text-slate-800">{title}</p>
              <p className="text-sm leading-relaxed text-slate-600">{body}</p>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-slate-500">
        Ini alat bantu edukasi untuk mengenali pola pengambilan keputusan, bukan
        nasihat investasi.{" "}
        <Link href="/metodologi" className="font-medium text-brand hover:underline">
          Pelajari cara kerjanya →
        </Link>
      </p>
    </section>
  );
}

function LoginForm(props: {
  username: string;
  onBack: () => void;
  onError: (msg: string | null) => void;
  onSuccess: () => void;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    props.onError(null);
    setBusy(true);
    try {
      await api.post<Me>("/api/auth/login", {
        username: props.username,
        password,
      });
      props.onSuccess();
    } catch (err) {
      props.onError(
        err instanceof ApiError ? err.detail : "Sambungan ke server terputus. Periksa koneksi Anda, lalu coba lagi.",
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm">
        Nama pengguna: <b className="font-mono">{props.username}</b>
      </p>
      <label className="block text-sm font-medium">
        Kata Sandi
        <input
          type="password"
          className={`${inputCls} mt-1`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          maxLength={128}
          autoFocus
        />
      </label>
      <button className={btnCls} disabled={busy}>
        {busy ? "Memeriksa…" : "Masuk"}
      </button>
      <button type="button" className={btnGhostCls} onClick={props.onBack}>
        ← Ganti nama pengguna
      </button>
    </form>
  );
}

function RegisterForm(props: {
  username: string;
  onBack: () => void;
  onError: (msg: string | null) => void;
  onSuccess: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    full_name: "",
    age: 20,
    gender: "laki-laki" as RegisterPayload["gender"],
    risk_profile: "moderat" as RegisterPayload["risk_profile"],
    investing_capability: "pemula" as RegisterPayload["investing_capability"],
    password: "",
    password2: "",
    consent: false,
  });
  const [survey, setSurvey] = useState<RegisterPayload["onboarding_survey"]>({
    dei_q1: 3, dei_q2: 3, dei_q3: 3,
    ocs_q1: 3, ocs_q2: 3, ocs_q3: 3,
    lai_q1: 3, lai_q2: 3, lai_q3: 3,
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    props.onError(null);
    if (form.password !== form.password2) {
      props.onError("Konfirmasi kata sandi tidak sesuai.");
      return;
    }
    if (!form.consent) {
      props.onError("Anda harus menyetujui partisipasi untuk melanjutkan.");
      return;
    }
    setBusy(true);
    try {
      await api.post<Me>("/api/auth/register", {
        username: props.username,
        password: form.password,
        full_name: form.full_name,
        age: form.age,
        gender: form.gender,
        risk_profile: form.risk_profile,
        investing_capability: form.investing_capability,
        onboarding_survey: survey,
        consent: form.consent,
      } satisfies RegisterPayload);
      props.onSuccess();
    } catch (err) {
      props.onError(
        err instanceof ApiError ? err.detail : "Sambungan ke server terputus. Periksa koneksi Anda, lalu coba lagi.",
      );
      setBusy(false);
    }
  }

  const radioRow = (
    label: string,
    name: string,
    options: readonly string[],
    value: string,
    set: (v: string) => void,
    help?: string,
  ) => (
    <fieldset className="text-sm">
      <legend className="font-medium">{label}</legend>
      {help && <p className="mb-1 text-xs text-slate-500">{help}</p>}
      <div className="mt-1 flex flex-wrap gap-3">
        {options.map((opt) => (
          <label key={opt} className="flex items-center gap-1.5 capitalize">
            <input
              type="radio"
              name={name}
              checked={value === opt}
              onChange={() => set(opt)}
            />
            {opt}
          </label>
        ))}
      </div>
    </fieldset>
  );

  return (
    <form onSubmit={submit} className="space-y-5">
      <p className="text-sm leading-relaxed">
        Nama pengguna <b className="font-mono">{props.username}</b> belum
        terdaftar. Yuk, lengkapi beberapa hal berikut; setelah itu Anda
        langsung bisa mulai.
      </p>

      <h3 className="border-b pb-1 text-sm font-semibold">Data Diri</h3>
      <label className="block text-sm font-medium">
        Nama Lengkap
        <input
          className={`${inputCls} mt-1`}
          value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          maxLength={128}
          required
        />
      </label>
      <label className="block text-sm font-medium">
        Usia (tahun)
        <input
          type="number"
          min={17}
          max={100}
          className={`${inputCls} mt-1`}
          value={form.age}
          onChange={(e) => setForm({ ...form, age: Number(e.target.value) })}
          required
        />
      </label>
      {radioRow("Jenis Kelamin", "gender",
        ["laki-laki", "perempuan", "lainnya"], form.gender,
        (v) => setForm({ ...form, gender: v as RegisterPayload["gender"] }))}

      <h3 className="border-b pb-1 text-sm font-semibold">Profil Investor</h3>
      {radioRow("Profil Risiko", "risk_profile",
        ["konservatif", "moderat", "agresif"], form.risk_profile,
        (v) => setForm({ ...form, risk_profile: v as RegisterPayload["risk_profile"] }),
        "Konservatif: memprioritaskan kestabilan modal. Moderat: menerima risiko terukur. Agresif: bersedia menanggung fluktuasi besar.")}
      {radioRow("Pengalaman Investasi", "investing_capability",
        ["pemula", "menengah", "berpengalaman"], form.investing_capability,
        (v) => setForm({ ...form, investing_capability: v as RegisterPayload["investing_capability"] }),
        "Pemula: belum/jarang berinvestasi. Menengah: aktif 1–3 tahun. Berpengalaman: > 3 tahun atau berlatar keuangan formal.")}

      <h3 className="border-b pb-1 text-sm font-semibold">Kata Sandi</h3>
      <label className="block text-sm font-medium">
        Kata Sandi (min. 8 karakter)
        <input
          type="password"
          className={`${inputCls} mt-1`}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          minLength={8}
          maxLength={128}
          required
        />
      </label>
      <label className="block text-sm font-medium">
        Ulangi Kata Sandi
        <input
          type="password"
          className={`${inputCls} mt-1`}
          value={form.password2}
          onChange={(e) => setForm({ ...form, password2: e.target.value })}
          maxLength={128}
          required
        />
      </label>

      <h3 className="border-b pb-1 text-sm font-semibold">
        Survei Awal Kecenderungan Bias
      </h3>
      <p className="text-xs text-slate-500">
        Sembilan pernyataan singkat ini membantu sistem mengenali titik awal
        Anda. Tidak ada jawaban benar atau salah; pilih saja yang paling
        menggambarkan diri Anda.
      </p>
      {ONBOARDING_ITEMS.map(([key, prompt]) => (
        <label key={key} className="block text-sm">
          {prompt}
          <select
            className={`${inputCls} mt-1`}
            value={survey[key]}
            onChange={(e) =>
              setSurvey({ ...survey, [key]: Number(e.target.value) })
            }
          >
            {LIKERT.map((v) => (
              <option key={v} value={v}>
                {LIKERT_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
      ))}

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={form.consent}
          onChange={(e) => setForm({ ...form, consent: e.target.checked })}
        />
        Saya telah membaca informasi penelitian dan menyetujui partisipasi
        dalam penelitian ini.
      </label>

      <button className={btnCls} disabled={busy}>
        {busy ? "Menyiapkan akun…" : "Daftar dan Mulai"}
      </button>
      <button type="button" className={btnGhostCls} onClick={props.onBack}>
        ← Ganti nama pengguna
      </button>
    </form>
  );
}
