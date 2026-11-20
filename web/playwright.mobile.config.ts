import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./mobile-e2e",
  workers: 1,
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:3200", launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? (existsSync("/usr/local/bin/chromium") ? "/usr/local/bin/chromium" : undefined), args: ["--no-sandbox"] } },
  webServer: { command: "node scripts/serve-mobile-ui.mjs", url: "http://127.0.0.1:3200/assets/www/mobile.html", reuseExistingServer: false },
});
