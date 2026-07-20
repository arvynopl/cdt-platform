// Sentry browser init. A complete no-op unless NEXT_PUBLIC_SENTRY_DSN is set,
// so local dev and any deploy without the env stay silent. sendDefaultPii is
// false to match the backend's UU PDP posture (no user PII shipped).
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? "production",
  tracesSampleRate: 0.2,
  sendDefaultPii: false,
});

// Enables navigation (App Router transition) instrumentation.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
