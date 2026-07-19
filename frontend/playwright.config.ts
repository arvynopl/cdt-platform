import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/**
 * E2E config for the CDT platform.
 *
 * Boots a disposable stack on dedicated ports (backend 8100, frontend 3100) so
 * it never collides with a developer's normal dev servers (3000/8000) or their
 * Neon-connected backend:
 *   - backend  → scripts/run_e2e_server.py: a fresh, seeded SQLite DB + uvicorn,
 *                with the researcher key set so the /peneliti spec can sign in.
 *   - frontend → next dev pointed at the test backend via NEXT_PUBLIC_API_BASE.
 *
 * Cookies are SameSite=Lax; on localhost the two ports are the same site, so
 * session auth works over http without a proxy.
 *
 * Set E2E_PYTHON to the interpreter that has the backend deps installed
 * (e.g. backend/.venv/Scripts/python.exe on Windows). Defaults to "python".
 */

const BACKEND_DIR = path.resolve(__dirname, "..", "backend");
const PY = process.env.E2E_PYTHON || "python";
const FRONTEND_PORT = 3100;
const BACKEND_PORT = 8100;
const BASE_URL = `http://localhost:${FRONTEND_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // Shared, single seeded backend DB → run serially for deterministic cohort
  // state and to avoid SQLite write contention.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    video: "retain-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  webServer: [
    {
      command: `"${PY}" scripts/run_e2e_server.py`,
      cwd: BACKEND_DIR,
      url: `http://localhost:${BACKEND_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        PORT: String(BACKEND_PORT),
        CDT_DATABASE_URL: "sqlite:///e2e_test.db",
        CDT_RESEARCHER_PASSWORD: "devkey",
        CDT_ADMIN_TOKEN: "devadmin",
        CDT_CORS_ORIGINS: BASE_URL,
        CDT_BCRYPT_ROUNDS: "4",
        SENTRY_DSN: "",
      },
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT}`,
      cwd: __dirname,
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_BASE: `http://localhost:${BACKEND_PORT}`,
      },
    },
  ],
});
