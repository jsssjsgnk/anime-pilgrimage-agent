import { expect, test } from "@playwright/test";

import { captureEvidence } from "./screenshot-evidence";

test("an arbitrary title can confirm several seasons and show real points", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await page.getByLabel("你的巡礼想法").fill("我想用一天巡礼轻音少女");
  await page.getByRole("button", { name: "开始规划" }).click();

  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible();
  const versions = page.getByRole("group", { name: /轻音少女/u }).getByRole("checkbox");
  await expect(versions).toHaveCount(3);
  await page.getByRole("button", { name: "选择全部季度与版本" }).click();
  for (const version of await versions.all()) await expect(version).toBeChecked();

  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 60_000 });
  if (testInfo.project.name.startsWith("mobile")) {
    await page.getByRole("button", { name: "行程信息" }).click();
  }
  await expect(page.getByText("3 个条目", { exact: true })).toBeVisible();
  if (testInfo.project.name.startsWith("mobile")) {
    await page.getByRole("button", { name: "地图与行程" }).click();
  }
  const map = page.getByLabel(/巡礼地点地图，共 \d+ 个地点/u);
  await expect(map.locator(".mix-map-marker").first()).toBeVisible();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-17-k-on-mobile.png"
    : "phase-17-k-on-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});
