import { defineConfig } from '@playwright/test';

// globalSetup seeds a temp data dir, generates fixtures and starts the real server (replay mode) on a free port,
// then exports ACRETIA_BASE_URL; the `baseURL` fixture in helpers.ts reads it. Set E2E_BASE_URL to reuse a running server.
export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 10 * 60 * 1000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    acceptDownloads: true,
    testIdAttribute: 'data-testid',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
