"use client";

// App Router global error boundary. Replaces the root layout when a rendering
// error escapes, so a crash shows a friendly page instead of a blank screen,
// and reports the error to Sentry (a no-op when no DSN is configured).

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="id">
      <body
        style={{
          fontFamily: "system-ui, -apple-system, sans-serif",
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f8fafc",
          color: "#1e293b",
        }}
      >
        <main style={{ maxWidth: "26rem", padding: "2rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem" }}>⚠️</div>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginTop: "0.5rem" }}>
            Maaf, terjadi kendala
          </h1>
          <p style={{ fontSize: "0.875rem", lineHeight: 1.6, color: "#475569" }}>
            Halaman ini gagal ditampilkan. Coba muat ulang; jika masih terjadi,
            kembali beberapa saat lagi. Data Anda aman dan tersimpan.
          </p>
          <button
            onClick={() => reset()}
            style={{
              marginTop: "1rem",
              borderRadius: "0.5rem",
              border: "none",
              background: "#2563eb",
              color: "#fff",
              padding: "0.625rem 1.25rem",
              fontSize: "0.875rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Muat ulang halaman
          </button>
        </main>
      </body>
    </html>
  );
}
