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

test("retry memakai pekerjaan tersimpan dan pembatalan langsung mengunci kontrol", async ({ page }) => {
  await page.addInitScript(() => {
    const state = { status: "interrupted", note: "Layanan sebelumnya terhenti.", busy: false, retryable: true, model_ready: true, progress: 0, plan: [], sentences: [], outputs: [], config: { provider: "gemini", model: "", consent: false }, active_job: { status: "interrupted", action: "analyze", attempt: 1 } };
    const fixture = window as unknown as { retries: number; cancellations: number; CuplikNative: unknown };
    fixture.retries = 0; fixture.cancellations = 0;
    fixture.CuplikNative = {
      getState: () => JSON.stringify(state),
      retryJob() { fixture.retries++; state.busy = true; state.retryable = false; state.status = "queued"; state.active_job.status = "queued"; state.active_job.attempt = 2; },
      cancel() { fixture.cancellations++; state.status = "cancelling"; state.active_job.status = "cancelling"; state.note = "Membatalkan proses."; },
    };
  });
  await page.goto("/assets/www/mobile.html");
  await page.getByRole("button", { name: "Coba ulang pekerjaan sebelumnya", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pilih video dari hape", exact: true })).toBeDisabled();
  await expect(page.getByRole("progressbar", { name: "Progres video Android" })).not.toHaveAttribute("value");
  await page.getByRole("button", { name: "Batalkan proses", exact: true }).click();
  await expect(page.getByRole("button", { name: "Menunggu pembatalan…", exact: true })).toBeDisabled();
  expect(await page.evaluate(() => ({ retries: (window as unknown as { retries: number }).retries, cancellations: (window as unknown as { cancellations: number }).cancellations }))).toEqual({ retries: 1, cancellations: 1 });
});

test("QC membedakan track tersedia dengan suara hening pada MP4", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 900 });
  await page.addInitScript(() => {
    window.CuplikNative = { getState: () => JSON.stringify({ status: "done", note: "Ekspor selesai.", busy: false, model_ready: true, progress: 1, plan: [], sentences: [], config: { provider: "gemini", model: "", consent: false }, outputs: [{ file: "export-test.mp4", title: "Fixture QC", url: "", duration_s: 3, duration_matches: true, audio_present: true, qc: { status: "needs_review", issues: ["very_quiet_audio", "long_silence"], note: "Pengukuran PCM/dBFS, bukan LUFS.", audio: { rms_dbfs: -120, peak_dbfs: -120, longest_silence_s: 3, silence_spans: [{ start_s: 0, end_s: 3 }] } } }] }) } as typeof window.CuplikNative;
  });
  await page.goto("/assets/www/mobile.html");
  await page.getByText("QC hasil: perlu ditinjau", { exact: true }).click();
  await expect(page.getByText("Suara sangat pelan atau hening", { exact: true })).toBeVisible();
  await expect(page.getByText(/RMS -120.0 dBFS/)).toBeVisible();
  await expect(page.getByText("Bagian hening: 0.0–3.0 dtk", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
