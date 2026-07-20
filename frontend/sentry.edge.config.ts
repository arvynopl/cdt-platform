// Sentry init for the Next.js edge runtime. No-op unless a DSN is set.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN ?? process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? "production",
  tracesSampleRate: 0.2,
  sendDefaultPii: false,
});
