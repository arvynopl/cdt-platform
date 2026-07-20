import type { Metadata } from "next";
import Link from "next/link";
import { GLOSSARY } from "@/lib/glossary";

export const metadata: Metadata = {
  title: "Metodologi & Istilah — CDT",
  description:
    "Cara kerja Cognitive Digital Twin (CDT) dan penjelasan istilah bias " +
    "pengambilan keputusan yang dipakai di aplikasi ini.",
};

const STEPS = [
  {
    n: 1,
    title: "Anda bermain dalam simulasi",
    body:
      "Setiap sesi menyajikan 14 putaran menggunakan data harga historis nyata. " +
      "Keputusan beli, jual, dan tahan yang Anda ambil direkam sebagai jejak perilaku.",
  },
  {
    n: 2,
    title: "Perilaku diukur menjadi indeks bias",
    body:
      "Dari jejak itu, aplikasi menghitung tiga indeks: efek disposisi (DEI), " +
      "keyakinan berlebih (OCS), dan menghindari kerugian (LAI). Ketiganya " +
      "menggambarkan seberapa kuat masing-masing kecenderungan pada sesi tersebut.",
  },
  {
    n: 3,
    title: "Profil diperbarui sedikit demi sedikit",
    body:
      "Hasil tiap sesi memperbarui profil jangka panjang Anda (Cognitive Digital " +
      "Twin) memakai rata-rata bergerak, sehingga arahnya mencerminkan kebiasaan " +
      "yang menetap, bukan satu sesi yang kebetulan.",
  },
  {
    n: 4,
    title: "Anda membaca pola dan berlatih",
    body:
      "Halaman hasil dan profil menerjemahkan angka menjadi umpan balik yang " +
      "dapat ditindaklanjuti, agar Anda mengenali pola sendiri dan mengujinya " +
      "pada sesi berikutnya.",
  },
];

export default function MetodologiPage() {
  return (
    <main className="space-y-6 pb-12">
      <div>
        <h2 className="text-lg font-semibold">Metodologi &amp; Istilah</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">
          Halaman ini menjelaskan secara ringkas cara kerja aplikasi dan arti
          istilah yang Anda temui di halaman hasil dan profil. Tujuannya satu:
          angka yang Anda lihat bukan kotak hitam.
        </p>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold">Cara kerja singkat</h3>
        <ol className="space-y-3">
          {STEPS.map((s) => (
            <li key={s.n} className="flex gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center
                           rounded-full bg-brand-soft text-xs font-semibold text-brand"
              >
                {s.n}
              </span>
              <div>
                <p className="text-sm font-medium text-slate-800">{s.title}</p>
                <p className="text-sm leading-relaxed text-slate-600">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold">Istilah yang sering muncul</h3>
        <dl className="space-y-4">
          {Object.entries(GLOSSARY).map(([key, entry]) => (
            <div key={key}>
              <dt className="text-sm font-semibold text-slate-800">
                {entry.label}
              </dt>
              <dd className="mt-0.5 text-sm leading-relaxed text-slate-600">
                {entry.long}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <p className="text-xs leading-relaxed text-slate-400">
        Aplikasi ini adalah alat bantu edukasi untuk mengenali pola pengambilan
        keputusan, bukan nasihat investasi. Metrik bersifat indikatif dan paling
        bermakna setelah beberapa sesi.
      </p>

      <Link
        href="/simulasi"
        className="inline-block rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white"
      >
        Kembali ke Simulasi →
      </Link>
    </main>
  );
}
