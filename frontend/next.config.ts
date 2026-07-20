import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

/**
 * Security headers.
 *
 * The CSP is the delicate one: the frontend (Vercel) calls the API on a
 * DIFFERENT origin (Fly.io), so `connect-src` MUST list the API origin or
 * every fetch is blocked and the app dies. We derive it from the same
 * NEXT_PUBLIC_API_BASE that lib/api.ts uses, so prod and dev stay in sync.
 *
 * A production-only CSP: `next dev` relies on eval + websocket HMR, which a
 * strict policy would break, so in development we widen script-src/connect-src.
 * Plotly (bundled, not remote) runs under `script-src 'self'`; Next injects
 * inline bootstrap scripts and Tailwind/Plotly inject inline styles, hence
 * 'unsafe-inline' for script/style (App Router static export can't mint a
 * per-request nonce).
 */
const isDev = process.env.NODE_ENV !== "production";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
let apiOrigin = "http://localhost:8000";
try {
  apiOrigin = new URL(apiBase).origin;
} catch {
  // keep the fallback if NEXT_PUBLIC_API_BASE is malformed
}

// When a Sentry DSN is configured, the browser SDK POSTs events to the
// project's ingest host — allow it in connect-src or the CSP would block them.
let sentryOrigin: string | null = null;
if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  try {
    sentryOrigin = new URL(process.env.NEXT_PUBLIC_SENTRY_DSN).origin;
  } catch {
    // ignore a malformed DSN; Sentry init would no-op on it anyway
  }
}

const connectSrc = [
  "'self'",
  apiOrigin,
  ...(sentryOrigin ? [sentryOrigin] : []),
  ...(isDev ? ["ws:", "wss:"] : []),
];
const scriptSrc = ["'self'", "'unsafe-inline'", ...(isDev ? ["'unsafe-eval'"] : [])];

const csp = [
  "default-src 'self'",
  `script-src ${scriptSrc.join(" ")}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src ${connectSrc.join(" ")}`,
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

// withSentryConfig adds source-map handling + tunneling. Without an auth token
// (SENTRY_AUTH_TOKEN) it simply skips source-map upload; the build still works,
// and everything stays a no-op at runtime until NEXT_PUBLIC_SENTRY_DSN is set.
export default withSentryConfig(nextConfig, {
  silent: !process.env.CI,
  widenClientFileUpload: true,
});
