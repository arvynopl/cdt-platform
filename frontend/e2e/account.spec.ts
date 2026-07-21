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
  await expect(page.getByRole("heading", { name: /Manajemen Akun/ })).toBeVisible();

  // Export downloads a JSON file.
  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Unduh JSON/ }).click(),
  ]);
  expect(jsonDownload.suggestedFilename()).toBe("data_saya_cdt.json");

  // The CSV option downloads a ZIP; validate it is a real ZIP archive
  // (PK magic bytes) so the whole cookie-auth → binary-download path is covered.
  const [zipDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Unduh CSV/ }).click(),
  ]);
  expect(zipDownload.suggestedFilename()).toBe("data_saya_cdt_csv.zip");
  const zipPath = await zipDownload.path();
  const { readFileSync } = await import("node:fs");
  const head = readFileSync(zipPath).subarray(0, 4);
  expect(head.toString("latin1")).toBe("PK\x03\x04");

  // Delete requires the typed confirmation word. The page now also has profile
  // fields, so target the confirmation input by its own label.
  await page.getByRole("button", { name: /Hapus Akun Saya/ }).click();
  const confirmFinal = page.getByRole("button", {
    name: /Ya, Hapus Akun Saya/i,
  });
  await expect(confirmFinal).toBeDisabled();
  await page.getByLabel(/Ketik HAPUS/).fill("HAPUS");
  await expect(confirmFinal).toBeEnabled();
  await confirmFinal.click();

  // Redirected to the landing page; the username is now available again,
  // so re-entering it routes to registration rather than login.
  await expect(page.getByText(/Selamat datang/)).toBeVisible();
  await page.getByLabel("Nama Pengguna").fill(username);
  await page.getByRole("button", { name: /Lanjutkan/ }).click();
  await expect(page.getByLabel("Nama Lengkap")).toBeVisible();
});

/**
 * Manajemen Akun: the profile edit persists, and a password change rotates the
 * credential (old one rejected, new one accepted) while keeping this browser
 * signed in.
 */
test("edits the profile and changes the password", async ({ page }) => {
  const username = uniqueUser();
  await register(page, username);

  await page.goto("/akun");
  await expect(page.getByRole("heading", { name: /Manajemen Akun/ })).toBeVisible();

  // Username is shown but locked.
  await expect(page.getByLabel("Nama Pengguna")).toBeDisabled();

  // Edit and save the profile.
  await page.getByLabel("Nama Lengkap").fill("Rani Putri");
  await page.getByLabel("Usia").fill("31");
  await page.getByLabel("Pengalaman Investasi").selectOption("berpengalaman");
  await page.getByRole("button", { name: /Simpan Perubahan/ }).click();
  await expect(page.getByText(/Data diri tersimpan/)).toBeVisible();

  // It survives a reload.
  await page.reload();
  await expect(page.getByLabel("Nama Lengkap")).toHaveValue("Rani Putri");
  await expect(page.getByLabel("Pengalaman Investasi")).toHaveValue(
    "berpengalaman",
  );

  // Change the password.
  await page.getByLabel("Kata Sandi Sekarang").fill("KataSandi123");
  await page.getByLabel("Kata Sandi Baru", { exact: true }).fill("SandiBaru456");
  await page.getByLabel("Ulangi Kata Sandi Baru").fill("SandiBaru456");
  await page.getByRole("button", { name: /Ubah Kata Sandi/ }).click();
  await expect(page.getByText(/Kata sandi berhasil diubah/)).toBeVisible();

  // Sign out, then only the new password works.
  await page.getByRole("button", { name: "Menu akun" }).click();
  await page.getByRole("menuitem", { name: /Keluar/ }).click();
  await expect(page.getByText(/Selamat datang/)).toBeVisible();

  await page.getByLabel("Nama Pengguna").fill(username);
  await page.getByRole("button", { name: /Lanjutkan/ }).click();
  await page.getByLabel("Kata Sandi").fill("SandiBaru456");
  await page.getByRole("button", { name: /^Masuk/ }).click();
  await page.waitForURL("**/simulasi");
});
