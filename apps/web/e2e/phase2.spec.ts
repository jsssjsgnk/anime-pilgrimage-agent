import { expect, test } from "@playwright/test";

test("subject search requires confirmation before showing sourced Route A", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();

  await expect(page.getByRole("heading", { name: "确认你要巡礼的作品" })).toBeVisible();
  await expect(page.getByText("Bangumi #328609")).toBeVisible();
  await expect(page.getByRole("heading", { name: "孤独摇滚！" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Route A/ })).toHaveCount(0);

  const basemapRequest = page.waitForRequest((request) => request.url() === "https://tiles.openfreemap.org/styles/liberty");
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();
  await basemapRequest;
  await expect(page.getByRole("button", { name: /已确认此作品/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: /Route A · 3 个有来源点位/ })).toBeVisible();
  const routeMap = page.getByLabel(/Route A 交互式地图，共 3 个点/);
  await expect(routeMap).toBeVisible();
  await expect(routeMap).toHaveAttribute("data-map-provider", "OpenFreeMap");
  await expect(routeMap).toHaveAttribute("data-map-status", "ready", { timeout: 20_000 });
  await expect(routeMap.locator(".maplibregl-canvas")).toBeVisible();
  await expect(routeMap.locator(".route-map-marker")).toHaveCount(3);
  await expect(routeMap.locator(".maplibregl-ctrl-zoom-in")).toBeVisible();
  await expect(routeMap.locator(".maplibregl-ctrl-attrib")).toContainText("OpenStreetMap");
  await expect(page.getByText(/当前合法导入文件只包含这 3 个有来源点位/)).toBeVisible();
  await expect(page.getByText("下北泽站东口")).toBeVisible();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-2-mobile.png"
    : "phase-2-desktop.png";
  await page.screenshot({
    path: `../../artifacts/screenshots/${screenshotName}`,
    fullPage: true,
  });

  await routeMap.getByRole("button", { name: "地图点位 1：下北沢SHELTER周边" }).click();
  await expect(routeMap.locator(".maplibregl-popup")).toContainText("01 · 下北沢SHELTER周边");
});
