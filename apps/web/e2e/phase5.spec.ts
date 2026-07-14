import { expect, test } from "@playwright/test";

import { captureEvidence } from "./screenshot-evidence";
import { planWorkspace } from "./workspace-flow";

test("natural conversation previews a change and survives reload", async ({ page }, testInfo) => {
  await planWorkspace(page);
  const versionBefore = await page.locator(".mix-section-heading .mix-kicker").textContent();
  const conversationTab = page.getByRole("button", { name: "对话" });
  if (await conversationTab.isVisible()) await conversationTab.click();

  const editor = page.getByLabel("继续修改行程");
  await editor.fill("我想每天少走一点");
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/messages")
      && response.request().method() === "POST",
    { timeout: 20_000 },
  );
  await page.getByRole("button", { name: "发送" }).click();
  expect((await responsePromise).ok()).toBe(true);
  await expect(page.getByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
  await expect(page.getByText("只重新计算受影响的行程")).toBeVisible();
  await page.getByRole("button", { name: "确认并重新规划" }).click();

  const mapTab = page.getByRole("button", { name: "地图与行程" });
  if (await mapTab.isVisible()) await mapTab.click();
  await expect(page.locator(".mix-section-heading .mix-kicker")).not.toHaveText(versionBefore ?? "", { timeout: 30_000 });

  await page.reload();
  await expect(page.getByText("我想每天少走一点", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/工作区\s+[a-f0-9]{8}|partial_ready|evidence_collector|PlanPatch|itinerary_planner/u)).toHaveCount(0);

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-5-mobile.png"
    : "phase-5-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});

test("bulk selection submits one combined preview", async ({ page }) => {
  await planWorkspace(page);
  await page.getByRole("button", { name: "批量选择" }).click();
  const choices = page.getByRole("list", { name: "批量选择地点" }).getByRole("checkbox");
  expect(await choices.count()).toBeGreaterThan(2);
  await choices.nth(0).check();
  await choices.nth(1).check();
  await choices.nth(2).check();
  await expect(page.getByText("已选 3 个地点")).toBeVisible();
  await page.getByRole("button", { name: "批量排除" }).click();
  const dialog = page.getByRole("dialog", { name: "应用这次修改？" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("从行程中排除、从行程中排除、从行程中排除");
});
