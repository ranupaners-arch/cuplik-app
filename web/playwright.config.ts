import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const systemChromium = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? (existsSync("/usr/local/bin/chromium") ? "/usr/local/bin/chromium" : undefined);
export default defineConfig({
  testDir: "./e2e",
  timeout: 120000,
  workers: 1,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:3100", actionTimeout: 10000, navigationTimeout: 20000, trace: "retain-on-failure", launchOptions: { executablePath: systemChromium, args: ["--no-sandbox"] } },
  webServer: { command: "../.venv/bin/python ../scripts/dev.py --web-port 3100 --api-port 8100 --redis-port 6390 --test", url: "http://127.0.0.1:3100", timeout: 120000, reuseExistingServer: false, gracefulShutdown: { signal: "SIGTERM", timeout: 15000 } },
});
