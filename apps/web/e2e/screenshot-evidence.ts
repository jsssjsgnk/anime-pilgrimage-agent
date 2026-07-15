import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { Page, TestInfo } from "@playwright/test";

export async function captureEvidence(
  page: Page,
  testInfo: TestInfo,
  screenshotName: string,
): Promise<void> {
  const runPath = testInfo.outputPath(screenshotName);
  await page.screenshot({ path: runPath, fullPage: true });

  const stablePath = resolve(
    process.cwd(),
    "../../artifacts/screenshots",
    screenshotName,
  );
  mkdirSync(dirname(stablePath), { recursive: true });
  if (!existsSync(stablePath)) {
    copyFileSync(runPath, stablePath);
  }
}
