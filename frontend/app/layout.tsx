import type { Metadata, Viewport } from "next";
import Link from "next/link";
import HeaderBar from "@/components/HeaderBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kenali Pola Investasi Anda — CDT",
  description:
    "Simulasi trading untuk memetakan bias pengambilan keputusan Anda, " +
    "ditenagai Cognitive Digital Twin (CDT).",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body>
        <a
          href="#konten"
          className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2
                     focus:z-[100] focus:rounded-lg focus:bg-brand focus:px-3 focus:py-2
                     focus:text-sm focus:font-semibold focus:text-white focus:shadow-lg"
        >
          Lompat ke konten utama
        </a>
        <div className="mx-auto min-h-screen max-w-3xl px-4 py-6">
          <header className="mb-8 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold">
                Kenali Pola Investasi Anda
              </h1>
              <p className="text-sm text-slate-500">
                Simulasi investasi yang membantu Anda mengenali kebiasaan
                mengambil keputusan, didukung <em>Cognitive Digital Twin</em>.
              </p>
            </div>
            <HeaderBar />
          </header>
          <div id="konten" tabIndex={-1} className="outline-none">
            {children}
          </div>
          <footer className="mt-12 border-t border-slate-200 pt-4 text-xs text-slate-500">
            <Link href="/metodologi" className="hover:text-slate-700 hover:underline">
              Metodologi &amp; istilah
            </Link>
            <span className="mx-2">·</span>
            Alat bantu edukasi, bukan nasihat investasi.
          </footer>
        </div>
      </body>
    </html>
  );
}
