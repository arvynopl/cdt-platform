import type { Metadata, Viewport } from "next";
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
        <div className="mx-auto min-h-screen max-w-3xl px-4 py-6">
          <header className="mb-8">
            <h1 className="text-xl font-semibold">
              Kenali Pola Investasi Anda
            </h1>
            <p className="text-sm text-slate-500">
              Simulasi trading untuk memetakan bias pengambilan keputusan Anda,
              ditenagai <em>Cognitive Digital Twin</em> (CDT).
            </p>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
