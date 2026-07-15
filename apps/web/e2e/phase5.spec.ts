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
  await page.goto("/");
  await page.getByLabel("你的巡礼想法").fill("我想用一天巡礼轻音少女");
  await page.getByRole("button", { name: "开始规划" }).click();
  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "选择全部季度与版本" }).click();
  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: "批量选择" }).click();
  const choices = page.getByRole("list", { name: "批量选择地点" }).getByRole("checkbox");
  const count = await choices.count();
  expect(count).toBeGreaterThan(25);
  await page.getByRole("button", { name: "全选当前列表" }).click();
  await expect(page.getByText(`已选 ${count} 个地点`)).toBeVisible();
  const requestPromise = page.waitForRequest(
    (request) => request.url().endsWith("/patches/preview")
      && request.method() === "POST",
  );
  await page.getByRole("button", { name: "批量排除" }).click();
  const request = await requestPromise;
  const payload = request.postDataJSON() as {
    patch: { operations: { op: string; place_ids: string[] }[] };
  };
  expect(payload.patch.operations).toHaveLength(1);
  expect(payload.patch.operations[0]).toMatchObject({
    op: "place_batch",
    place_ids: expect.arrayContaining([expect.any(String)]),
  });
  expect(payload.patch.operations[0]?.place_ids).toHaveLength(count);
  const dialog = page.getByRole("dialog", { name: "应用这次修改？" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(`${count} 个地点：从行程中排除`);
});
