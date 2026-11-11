import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 90000,
  reporter: [
    ["list"],
    ["json", { outputFile: "../../artifacts/phase-one/browser/results.json" }],
  ],
  outputDir: "../../artifacts/phase-one/browser/traces",
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    headless: true,
    viewport: { width: 1365, height: 1000 },
    trace: "retain-on-failure",
  },
});
