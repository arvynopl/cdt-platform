// Sentry init for the Next.js server runtime. No-op unless a DSN is set.
// This frontend has no server secrets and does minimal SSR, but any App
// Router server error is still captured when a DSN is configured.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN ?? process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? "production",
  tracesSampleRate: 0.2,
  sendDefaultPii: false,
});
