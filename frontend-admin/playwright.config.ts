import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: '../backend/.venv/bin/python ../backend/tools/e2e_server.py',
    url: 'http://127.0.0.1:8765/api/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  // Demo workstations already have Chrome.  Set PLAYWRIGHT_CHANNEL=chromium in
  // CI after `npx playwright install chromium` when a branded Chrome is absent.
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
      },
    },
  ],
})
