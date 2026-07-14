import { expect, test } from "@playwright/test";

import { captureEvidence } from "./screenshot-evidence";
import { startWorkspace } from "./workspace-flow";

test("natural multi-work request requires one explicit confirmation", async ({ page }, testInfo) => {
  await startWorkspace(page);
  await expect(page.getByText("2 部作品")).toBeVisible();
  await expect(page.getByText(/目录条目|Provider|Anitabi/u)).toHaveCount(0);
  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("巡礼地点")).toBeVisible();
  await expect(page.getByRole("button", { name: "批量选择" })).toBeVisible();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-2-mobile.png"
    : "phase-2-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});
