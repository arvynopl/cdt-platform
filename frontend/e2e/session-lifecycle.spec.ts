import { test, expect } from "@playwright/test";
import { register, uniqueUser, executeRound, buyFirstStock } from "./helpers";

/** Skip the practice gate so these tests focus on the real session. */
async function skipPractice(context: import("@playwright/test").BrowserContext) {
  await context.addInitScript(() => {
    try {
      localStorage.setItem("cdt_practice_v1", "done");
    } catch {
      /* storage unavailable — the gate then simply shows practice */
    }
  });
}

test("logs out and can no longer reach the simulation", async ({
  page,
  context,
}) => {
  await skipPractice(context);
  await register(page, uniqueUser());
  await expect(page.getByText(/Putaran 1 dari 14/)).toBeVisible({ timeout: 30_000 });

  // Log out via the account menu in the top bar.
  await page.getByRole("button", { name: "Menu akun" }).click();
  await page.getByRole("menuitem", { name: /Keluar/ }).click();
  await expect(page.getByText(/Selamat datang/)).toBeVisible();

  // The protected simulation now bounces back to the landing page.
  await page.goto("/simulasi");
  await expect(page.getByText(/Selamat datang/)).toBeVisible();
});

test("resumes an in-progress session after navigating away", async ({
  page,
  context,
}) => {
  await skipPractice(context);
  await register(page, uniqueUser());
  await expect(page.getByText(/Putaran 1 dari 14/)).toBeVisible({ timeout: 30_000 });

  // Advance one round, then leave the page entirely.
  await buyFirstStock(page, 5);
  await executeRound(page);
  await expect(page.getByText(/Putaran 2 dari 14/)).toBeVisible();

  await page.goto("/profil");
  await page.goto("/simulasi");

  // The session resumes where it left off (round 2), not a fresh session.
  await expect(page.getByText(/Putaran 2 dari 14/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/melanjutkan sesi sebelumnya/)).toBeVisible();
});

/**
 * Analysis-retry (phase "analysis_error" → "Jalankan Analisis Ulang") can only
 * be reached when the post-session pipeline actually fails. There is no
 * fault-injection hook in the backend to force that deterministically from a
 * black-box E2E, so this path is covered by backend unit tests instead. Left
 * as a documented skip rather than a flaky simulated failure.
 */
test.skip("retries a failed analysis", async () => {
  // Requires a backend fault-injection hook to force the analysis pipeline to
  // fail; out of scope for the black-box E2E stack.
});
