import { test, expect } from "@playwright/test";
import { register, uniqueUser, executeRound, buyFirstStock } from "./helpers";

/**
 * The critical freeze: a brand-new user registers, plays a full 14-round
 * session (with one real trade so the analysis has something to chew on),
 * lands on the results page, submits the post-session survey, and sees their
 * cognitive profile. This is the flow that was only ever verified by hand.
 */
test("registers, completes a full session, then reads results, survey, and profile", async ({
  page,
  context,
}) => {
  // Skip the practice gate so this test focuses on the real session; the
  // onboarding spec covers practice explicitly.
  await context.addInitScript(() => {
    try {
      localStorage.setItem("cdt_practice_v1", "done");
    } catch {
      /* storage may be unavailable; the gate then simply shows practice */
    }
  });

  await register(page, uniqueUser());
  await expect(page.getByText(/Putaran 1 dari 14/)).toBeVisible({ timeout: 30_000 });

  // One real buy in round 1 so the session records at least one trade.
  await buyFirstStock(page, 5);

  for (let round = 1; round <= 14; round++) {
    await executeRound(page);
    if (round < 14) {
      await expect(
        page.getByText(new RegExp(`Putaran ${round + 1} dari 14`)),
      ).toBeVisible();
    }
  }

  // Background analysis completes, then the app redirects to the results page.
  await page.waitForURL(/\/hasil/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: /Hasil Analisis/ })).toBeVisible();
  await expect(page.getByText(/Nilai Akhir Portofolio/)).toBeVisible();

  // Post-session self-assessment (Likert defaults are pre-selected) → submit.
  await page.getByRole("button", { name: /Kirim Penilaian/ }).click();
  await expect(page.getByText(/penilaian Anda sudah tersimpan/)).toBeVisible();

  // Profile renders from the freshly completed session.
  await page.getByRole("button", { name: /Lihat Profil Saya/ }).click();
  await page.waitForURL("**/profil");
  await expect(page.getByText(/Profil Kognitif Anda/)).toBeVisible();
  await expect(page.getByText(/Peta Bias Anda/)).toBeVisible();
});
