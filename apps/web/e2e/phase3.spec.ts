import { expect, test } from "@playwright/test";

import { captureEvidence } from "./screenshot-evidence";
import { planWorkspace } from "./workspace-flow";

test("planned map stays compact and opens scene-rich place details", async ({ page }, testInfo) => {
  await planWorkspace(page);

  const map = page.getByLabel(/巡礼地点地图，共 \d+ 个地点/u);
  await expect(map).toBeVisible();
  const mapBox = await map.boundingBox();
  expect(mapBox).not.toBeNull();
  expect(mapBox?.height).toBeLessThanOrEqual(testInfo.project.name.startsWith("mobile") ? 270 : 310);

  const markers = map.locator(".mix-map-marker");
  expect(await markers.count()).toBeGreaterThan(1);
  const pointBrowser = page.locator(".mix-point-browser");
  await pointBrowser.getByText(/浏览当前地点/u).click();
  await pointBrowser.getByRole("button").first().click();
  await expect(page.locator("#mix-place-detail-title")).toBeVisible();
  await expect(page.locator(".mix-place-detail")).toContainText(/第\d+话|集数时间待补充/u);
  const sceneImage = page.locator(".mix-scene-grid img").first();
  if (await sceneImage.count()) await expect(sceneImage).toHaveAttribute("src", /plan=h360/u);

  await page.getByRole("button", { name: "批量选择" }).click();
  const choices = page.getByRole("list", { name: "批量选择地点" }).getByRole("checkbox");
  await choices.nth(0).check();
  await choices.nth(1).check();
  await expect(page.getByText("已选 2 个地点")).toBeVisible();
  await page.getByRole("button", { name: "批量加入" }).click();
  await expect(page.getByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
  await expect(page.getByText(/PlanPatch|invalidated|stable_refs/u)).toHaveCount(0);
  await page.getByRole("button", { name: "取消" }).click();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-3-mobile.png"
    : "phase-3-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});
