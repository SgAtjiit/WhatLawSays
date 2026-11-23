import { defineConfig, devices } from "@playwright/test";

// Sign-in runs against the Firebase Auth emulator; the API is served from
// fixtures recorded from the real backend (see tests/e2e/support.js), so the
// suite needs neither a Firebase project nor a running backend.
const PORT = 5174;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 45_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome" }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: "npx firebase emulators:start --only auth --project demo-whatlawsays",
      url: "http://127.0.0.1:9099",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: `npx vite --mode emulator --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}`,
      reuseExistingServer: true,
    },
  ],
});
