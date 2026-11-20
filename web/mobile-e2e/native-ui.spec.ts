import { expect, test } from "@playwright/test";

for (const width of [360, 768]) {
  test(`kontrol native, API dan tinjauan tidak terpotong pada ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      const state = { status: "awaiting_review", note: "Fixture antarmuka.", busy: false, model_ready: true, progress: 1, mode: "clips", analysis_provider: "manual", source: { name: "fixture.mp4", duration_s: 12, url: "" }, sentences: [], outputs: [], config: { provider: "gemini", model: "fixture-model", consent: false, has_key: false }, plan: [{ id: "p1", title: "Pilihan manual", start_s: 0, end_s: 8, speed: 1, keep: true, required: false, locked: false, text: "Siapkan alat.", score: 0 }] };
      const fixture = window as unknown as { nativeCalls: { name: string; value?: unknown }[]; nativeReads: number; CuplikNative: unknown };
      fixture.nativeCalls = []; fixture.nativeReads = 0;
      fixture.CuplikNative = {
        getState() { fixture.nativeReads++; return JSON.stringify(state); },
        saveConfig(value: string) { fixture.nativeCalls.push({ name: "saveConfig", value: JSON.parse(value) }); },
        render(value: string) { fixture.nativeCalls.push({ name: "render", value: JSON.parse(value) }); },
        chooseVideo() { fixture.nativeCalls.push({ name: "chooseVideo" }); },
      };
    });
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/assets/www/mobile.html");
    await page.getByText("Pengaturan API AI dan model transkripsi", { exact: true }).click();
    await page.getByLabel("Kunci API", { exact: true }).fill("fixture-not-a-secret");
    await page.getByLabel("Izinkan pengiriman teks transkrip ke provider ini", { exact: true }).check();
    await page.getByRole("button", { name: "Simpan pengaturan AI", exact: true }).click();
    await expect(page.getByLabel("Kunci API", { exact: true })).toHaveValue("");
    await page.getByLabel("Awal p1 (detik)", { exact: true }).fill("1");
    const reads = await page.evaluate(() => (window as unknown as { nativeReads: number }).nativeReads);
    await expect.poll(() => page.evaluate(() => (window as unknown as { nativeReads: number }).nativeReads)).toBeGreaterThan(reads);
    await expect(page.getByLabel("Awal p1 (detik)", { exact: true })).toHaveValue("1");
    await page.getByRole("button", { name: "Setujui dan ekspor di hape", exact: true }).click();
    const calls = await page.evaluate(() => (window as unknown as { nativeCalls: { name: string; value: { plan?: { start_s: number }[]; consent?: boolean } }[] }).nativeCalls);
    expect(calls.find(call => call.name === "render")?.value.plan?.[0].start_s).toBe(1);
    expect(calls.find(call => call.name === "saveConfig")?.value.consent).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(errors).toEqual([]);
  });
}
