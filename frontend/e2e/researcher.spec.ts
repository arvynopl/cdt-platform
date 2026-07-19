import { test, expect } from "@playwright/test";

/**
 * The researcher dashboard is key-gated (X-Researcher-Key), separate from the
 * participant session cookie. Verify the gate rejects a wrong key, accepts the
 * configured one, renders cohort KPIs, and exports a dataset as CSV.
 *
 * The test backend sets CDT_RESEARCHER_PASSWORD=devkey (see playwright.config).
 */
test("gates the researcher dashboard and exports a dataset", async ({ page }) => {
  await page.goto("/peneliti");
  await expect(page.getByRole("heading", { name: /Dasbor Peneliti/ })).toBeVisible();

  // Wrong key is rejected.
  await page.getByLabel("Kunci Peneliti").fill("kunci-salah");
  await page.getByRole("button", { name: /Buka Dasbor/ }).click();
  await expect(page.getByText(/Kunci akses tidak valid/)).toBeVisible();
  await page.getByRole("button", { name: /Ganti kunci/ }).click();

  // Correct key loads the cohort KPIs.
  await page.getByLabel("Kunci Peneliti").fill("devkey");
  await page.getByRole("button", { name: /Buka Dasbor/ }).click();
  await expect(page.getByText("Total Partisipan")).toBeVisible();

  // Exporting a dataset triggers a CSV download.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Semua sesi/ }).click(),
  ]);
  expect(download.suggestedFilename()).toContain("all_sessions");
});
