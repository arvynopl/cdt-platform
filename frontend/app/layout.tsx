import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { ToastProvider } from "@/components/ui/Toast";
import "./globals.css";

// Self-hosted by next/font at build time, so no external font request (the
// CSP blocks those anyway). Plus Jakarta Sans is an Indonesian typeface.
const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

// Set the theme class before paint to avoid a flash: an explicit stored choice
// wins; otherwise fall back to the OS preference.
const themeInitScript = `(function(){try{var t=localStorage.getItem('cdt_theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme:dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}})();`;

export const metadata: Metadata = {
  title: "CDT — Kenali Pola Investasi Anda",
  description:
    "Simulasi trading untuk memetakan bias pengambilan keputusan Anda, " +
    "ditenagai Cognitive Digital Twin (CDT).",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

const FOOTER_LINKS = [
  { href: "/metodologi", label: "Metodologi dan Istilah" },
  { href: "/umpan-balik", label: "Beri Masukan" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id" className={sans.variable} suppressHydrationWarning>
      <body className="min-h-screen">
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <ToastProvider>
          <a
            href="#konten"
            className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2
                       focus:z-[100] focus:rounded-lg focus:bg-brand focus:px-3 focus:py-2
                       focus:text-sm focus:font-semibold focus:text-white focus:shadow-lg"
          >
            Lompat ke konten utama
          </a>

          <h1 className="sr-only">CDT, kenali pola investasi Anda</h1>

          <TopBar />

          <div className="mx-auto max-w-6xl px-4 py-6">
            <div id="konten" tabIndex={-1} className="outline-none">
              {children}
            </div>
          </div>

          <footer className="mt-8 border-t border-edge">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-6 text-xs text-muted">
              {FOOTER_LINKS.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className="hover:text-strong hover:underline"
                >
                  {l.label}
                </Link>
              ))}
              <span className="ml-auto">
                Alat bantu edukasi, bukan nasihat investasi.
              </span>
            </div>
          </footer>
        </ToastProvider>
      </body>
    </html>
  );
}
