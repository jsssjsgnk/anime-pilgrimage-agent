import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("complete plan can be locally revised, sourced, and exported", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();
  await page.getByRole("radio", { name: "选择去程 新干线" }).click();
  await page.getByRole("radio", { name: "选择返程 新干线" }).click();
  await page.getByRole("radio", { name: "选择基地 下北泽站周边" }).click();
  await page.getByRole("button", { name: /生成可执行 Route B/ }).click();

  const timeline = page.getByRole("region", { name: "Route B · 三日可执行时间轴" });
  await expect(timeline.getByText("计划版本 1")).toBeVisible();
  await expect(timeline.getByRole("heading", { name: "访问与礼仪依据" })).toBeVisible();
  await expect(timeline.getByText("Shimokitazawa neighborhood planning note")).toBeVisible();
  await expect(timeline.getByText(/权威 4\/5 · 访问 2026-07-14/).first()).toBeVisible();

  const dayCards = timeline.locator(".day-card");
  const dayOneBefore = await dayCards.nth(0).textContent();
  const dayThreeBefore = await dayCards.nth(2).textContent();
  await timeline.getByRole("button", { name: /应用为版本 2/ }).click();
  await expect(timeline.getByText("计划版本 2")).toBeVisible();
  await expect(timeline.getByText("第 2 天已按 3 km 局部上限重算；第 1、3 天保持稳定。"))
    .toBeVisible();
  expect(await dayCards.nth(0).textContent()).toBe(dayOneBefore);
  expect(await dayCards.nth(2).textContent()).toBe(dayThreeBefore);

  const jsonDownloadPromise = page.waitForEvent("download");
  await timeline.getByRole("button", { name: "导出 JSON" }).click();
  const jsonDownload = await jsonDownloadPromise;
  expect(jsonDownload.suggestedFilename()).toBe("pilgrimage-plan.json");
  const jsonPath = await jsonDownload.path();
  expect(jsonPath).not.toBeNull();
  const plan = JSON.parse(await readFile(jsonPath, "utf-8")) as {
    schema_version: string;
    plan_version: number;
    route_a_point_ids: string[];
  };
  expect(plan.schema_version).toBe("1");
  expect(plan.plan_version).toBe(2);
  expect(plan.route_a_point_ids.length).toBe(3);

  const geoDownloadPromise = page.waitForEvent("download");
  await timeline.getByRole("button", { name: "导出 GeoJSON" }).click();
  const geoDownload = await geoDownloadPromise;
  expect(geoDownload.suggestedFilename()).toBe("pilgrimage-route.geojson");
  const geoPath = await geoDownload.path();
  expect(geoPath).not.toBeNull();
  const geojson = JSON.parse(await readFile(geoPath, "utf-8")) as {
    type: string;
    schema_version: string;
    features: unknown[];
  };
  expect(geojson.type).toBe("FeatureCollection");
  expect(geojson.schema_version).toBe("1");
  expect(geojson.features.length).toBeGreaterThan(0);

  const htmlDownloadPromise = page.waitForEvent("download");
  await timeline.getByRole("button", { name: "打印 HTML" }).click();
  const htmlDownload = await htmlDownloadPromise;
  expect(htmlDownload.suggestedFilename()).toBe("pilgrimage-plan.html");
  const htmlPath = await htmlDownload.path();
  expect(htmlPath).not.toBeNull();
  const html = await readFile(htmlPath, "utf-8");
  expect(html).toContain("<!doctype html>");
  expect(html).not.toContain("<script");

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-5-mobile.png"
    : "phase-5-desktop.png";
  await page.screenshot({
    path: `../../artifacts/screenshots/${screenshotName}`,
    fullPage: true,
  });
});
