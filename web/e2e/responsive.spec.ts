import { expect, test } from "@playwright/test";

for (const viewport of [{ name: "hape", width: 360, height: 800 }, { name: "tablet", width: 768, height: 1024 }, { name: "laptop", width: 1440, height: 900 }]) {
  test(`studio responsif ${viewport.name}: navigasi, form dan hasil`, async ({ page, request }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    const noOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Buat", exact: true })).toHaveAttribute("aria-current", "page");
    await page.getByRole("combobox", { name: "Jenis sumber", exact: true }).selectOption("upload");
    await page.getByRole("combobox", { name: "Mode", exact: true }).selectOption("condense");
    await page.getByLabel("Periksa koherensi sebelum render", { exact: true }).check();
    await noOverflow();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `/tmp/cuplik-home-${viewport.name}.png`, fullPage: false });
    const project = await (await request.post("/api/projects", { data: { source_kind: "demo" } })).json();
    const output = await (await request.post(`/api/projects/${project.id}/outputs`, { data: { mode: "condense", settings: { target_seconds: 40 } } })).json();
    await page.goto(`/outputs/${output.id}`);
    await expect(page.getByTestId("output-status")).toHaveText("awaiting_review", { timeout: 90000 });
    await page.getByText("Keputusan per beat", { exact: true }).click();
    await noOverflow();
    await page.getByRole("button", { name: "Setujui bab dan render Ringkas", exact: true }).click();
    await expect(page.getByTestId("output-status")).toHaveText("done", { timeout: 90000 });
    const qcDetails = page.locator("details").filter({ has: page.locator("summary", { hasText: "Pemeriksaan kualitas Ringkas" }) });
    if (await qcDetails.getAttribute("open") === null) await qcDetails.locator("summary").click();
    await expect(page.getByRole("link", { name: "Laporan QC Ringkas (JSON)", exact: true })).toHaveCount(1);
    const video = page.locator("video").first();
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThan(0);
    const box = await video.boundingBox();
    expect(box!.width).toBeGreaterThan(viewport.width < 600 ? 250 : 400);
    await noOverflow();
    await video.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/cuplik-studio-${viewport.name}.png`, fullPage: false });
    await page.getByRole("link", { name: "Preferensi", exact: true }).click();
    await expect(page.getByRole("link", { name: "Preferensi", exact: true })).toHaveAttribute("aria-current", "page");
    await noOverflow();
    expect(errors).toEqual([]);
  });
}

test("form tetap terbaca pada lebar 320px dan pembesaran teks", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
  await expect(page.getByRole("button", { name: "Mulai proses", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
});
