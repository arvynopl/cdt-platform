import type { Metadata, Viewport } from "next";
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
          {children}
        </div>
      </body>
    </html>
  );
}
