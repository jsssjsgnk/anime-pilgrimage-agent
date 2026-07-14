import { expect, test } from "@playwright/test";

import { captureEvidence } from "./screenshot-evidence";

test("single conversational workspace is responsive", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "多作品巡礼工作区" })).toBeVisible();
  await expect(page.getByLabel("你的巡礼想法")).toHaveValue(/孤独摇滚/u);
  await expect(page.getByText("仅提供只读规划，不执行预订或付款")).toBeVisible();
  await expect(page.getByText(/Route A|Route B|PlanPatch|Anitabi|目录身份/u)).toHaveCount(0);
  await expect(page.getByText("经典路线兼容流程")).toHaveCount(0);

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-1-mobile.png"
    : "phase-1-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});
