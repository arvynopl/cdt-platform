import { expect, type Page } from "@playwright/test";

let seq = 0;

/** A fresh, valid username per test run (serial suite, but keep it unique). */
export function uniqueUser(prefix = "e2e"): string {
  seq += 1;
  return `${prefix}${Date.now().toString(36)}${seq}${Math.floor(Math.random() * 1e6)}`;
}

/**
 * Drive the username-first registration flow from the landing page through to
 * the simulation. Uses form defaults (age/gender/risk/experience and the 9
 * onboarding Likert selects all default to sensible values), so only the
 * required free-text fields and consent are filled.
 */
export async function register(page: Page, username: string): Promise<void> {
  // Reach the registration stage. Retry the whole load → username → continue
  // block so a lost first click (dev-mode hydration race) or a transient reload
  // recovers instead of failing the test.
  await expect(async () => {
    await page.goto("/");
    await page.getByLabel("Nama Pengguna").fill(username);
    await page.getByRole("button", { name: /Lanjutkan/ }).click();
    await expect(page.getByLabel("Nama Lengkap")).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 30_000 });

  await page.getByLabel("Nama Lengkap").fill("Peserta E2E");
  await page.getByLabel(/Kata Sandi \(min/).fill("KataSandi123");
  await page.getByLabel(/Ulangi Kata Sandi/).fill("KataSandi123");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /Daftar dan Mulai/ }).click();

  await page.waitForURL("**/simulasi");
}

/** Execute the current real-session round via the tray + confirmation dialog. */
export async function executeRound(page: Page): Promise<void> {
  await page.locator('[data-tour="execute"]').click();
  await page.getByRole("button", { name: /Ya, Jalankan/ }).click();
}

/** Add a buy order for the first stock card in the real trading interface. */
export async function buyFirstStock(page: Page, shares: number): Promise<void> {
  await page.locator('[data-tour="stocks"] button[aria-expanded]').first().click();
  const ticket = page.locator('[data-tour="ticket"]');
  await expect(ticket).toBeVisible();
  await ticket.locator('input[type="number"]').fill(String(shares));
  await ticket.getByRole("button", { name: /Tambahkan ke Order/ }).click();
}
