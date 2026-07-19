import { test, expect } from "@playwright/test";
import { register, uniqueUser } from "./helpers";

/**
 * First-time onboarding: a new user meets the guided tour, works through the
 * three scripted practice rounds (buy → observe → sell), and is then handed
 * into the real 14-round session.
 */
test("guides a first-time user through the tour and practice into the session", async ({
  page,
}) => {
  await register(page, uniqueUser());

  // The spotlight tour opens over the practice screen; prove it appears, then
  // dismiss it so the practice controls become interactive.
  await expect(page.getByText(/Panduan 1 dari/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /Lewati panduan/ }).click();
  await expect(page.getByText(/Mode Latihan/)).toBeVisible();

  const ticket = page.locator('[data-tour="ticket"]');
  const execute = page.locator('[data-tour="execute"]');

  // Round 1 — place a buy.
  await ticket.locator('input[type="number"]').fill("100");
  await ticket.getByRole("button", { name: /Tambahkan ke Order/ }).click();
  await execute.click();

  // Round 2 — observe (the input is disabled; just execute). Match the
  // progress span exactly so it doesn't also hit the narration heading.
  await expect(page.getByText("Latihan 2 dari 3", { exact: true })).toBeVisible();
  await execute.click();

  // Round 3 — sell the whole position.
  await expect(page.getByText("Latihan 3 dari 3", { exact: true })).toBeVisible();
  await ticket.locator('input[type="number"]').fill("100");
  await ticket.getByRole("button", { name: /Tambahkan ke Order/ }).click();
  await execute.click();

  // Completion → into the real session.
  await expect(page.getByText(/Latihan selesai/)).toBeVisible();
  await page.getByRole("button", { name: /Masuk ke Simulasi/ }).click();
  await expect(page.getByText(/Putaran 1 dari 14/)).toBeVisible({ timeout: 30_000 });
});
