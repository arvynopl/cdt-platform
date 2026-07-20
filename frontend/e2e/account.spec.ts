import { test, expect } from "@playwright/test";
import { register, uniqueUser } from "./helpers";

/**
 * UU PDP data-subject rights: a user can download all their data, then delete
 * (anonymise) their account. After deletion the username is free again, which
 * proves the identity was removed.
 */
test("exports data, then deletes the account and frees the username", async ({
  page,
}) => {
  const username = uniqueUser();
  await register(page, username);

  await page.goto("/akun");
  await expect(page.getByRole("heading", { name: /Akun & Privasi/ })).toBeVisible();

  // Export downloads a JSON file.
  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Unduh \(JSON\)/ }).click(),
  ]);
  expect(jsonDownload.suggestedFilename()).toBe("data_saya_cdt.json");

  // The CSV option downloads a ZIP; validate it is a real ZIP archive
  // (PK magic bytes) so the whole cookie-auth → binary-download path is covered.
  const [zipDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Unduh \(CSV\/ZIP\)/ }).click(),
  ]);
  expect(zipDownload.suggestedFilename()).toBe("data_saya_cdt_csv.zip");
  const zipPath = await zipDownload.path();
  const { readFileSync } = await import("node:fs");
  const head = readFileSync(zipPath).subarray(0, 4);
  expect(head.toString("latin1")).toBe("PK\x03\x04");

  // Delete requires the typed confirmation word.
  await page.getByRole("button", { name: /Hapus Akun Saya/ }).click();
  const confirmFinal = page.getByRole("button", { name: /Ya, hapus akun saya/ });
  await expect(confirmFinal).toBeDisabled();
  await page.getByRole("textbox").fill("HAPUS");
  await expect(confirmFinal).toBeEnabled();
  await confirmFinal.click();

  // Redirected to the landing page; the username is now available again,
  // so re-entering it routes to registration rather than login.
  await expect(page.getByText(/Selamat datang/)).toBeVisible();
  await page.getByLabel("Nama Pengguna").fill(username);
  await page.getByRole("button", { name: /Lanjutkan/ }).click();
  await expect(page.getByLabel("Nama Lengkap")).toBeVisible();
});
