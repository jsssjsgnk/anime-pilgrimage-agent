import { expect, test } from "@playwright/test";
import { captureEvidence } from "./screenshot-evidence";
import { readFile } from "node:fs/promises";
import { provideDeterministicRequirements } from "./workflow-fixture";

test("complete plan can be locally revised, sourced, and exported", async ({ page }, testInfo) => {
  await provideDeterministicRequirements(page);
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await page.getByRole("button", { name: /确认条件并查询 Bangumi/ }).click();
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();
  await page.getByRole("radio", { name: "选择去程 人工交通" }).click();
  await page.getByRole("radio", { name: "选择返程 人工交通" }).click();
  await page.getByRole("radio", { name: /选择基地 .*Route A 中心候选/ }).click();
  await page.getByRole("button", { name: /生成可执行 Route B/ }).click();

  const timeline = page.getByRole("region", { name: "Route B · 三日可执行时间轴" });
  await expect(timeline.getByText("计划版本 1")).toBeVisible();
  await expect(timeline.getByRole("heading", { name: "访问与礼仪依据" })).toBeVisible();
  await expect(timeline.getByRole("heading", { name: "访问与礼仪依据" })).toBeVisible();

  const dayCards = timeline.locator(".day-card");
  const dayOneBefore = await dayCards.nth(0).textContent();
  const dayThreeBefore = await dayCards.nth(2).textContent();
  await timeline.getByRole("button", { name: /应用为版本 2/ }).click();
  await expect(timeline.getByText("计划版本 2")).toBeVisible();
  await expect(timeline.getByText(/第 1、3 天保持稳定/)).toBeVisible();
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
  expect(plan.route_a_point_ids.length).toBeGreaterThan(3);

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
  await captureEvidence(page, testInfo, screenshotName);
});

test("conversation replans one day and survives a browser reload", async ({ page }) => {
  await provideDeterministicRequirements(page);
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await page.getByRole("button", { name: /确认条件并查询 Bangumi/ }).click();
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();
  await page.getByRole("radio", { name: "选择去程 人工交通" }).click();
  await page.getByRole("radio", { name: "选择返程 人工交通" }).click();
  await page.getByRole("radio", { name: /选择基地 .*Route A 中心候选/ }).click();
  await page.getByRole("button", { name: /生成可执行 Route B/ }).click();

  const timeline = page.getByRole("region", { name: "Route B · 三日可执行时间轴" });
  await expect(timeline.getByText("计划版本 1")).toBeVisible();
  const conversation = page.getByRole("region", { name: "和规划 Agent 继续聊" });
  await conversation.getByLabel("继续询问或提出修改").fill("第二天少走 20%，其他天保持不变");
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/messages")
      && response.request().method() === "POST",
    { timeout: 20_000 },
  );
  await conversation.getByRole("button", { name: "发送" }).click();
  expect((await responsePromise).status()).toBe(200);
  await expect(conversation.getByText(/已更新计划 · 第 2 天 · 修订 1\/3/)).toBeVisible();
  await expect(timeline.getByText("计划版本 2")).toBeVisible();

  await page.reload();
  const restoredConversation = page.getByRole("region", { name: "和规划 Agent 继续聊" });
  await expect(restoredConversation.getByText("第二天少走 20%，其他天保持不变")).toBeVisible();
  await expect(restoredConversation.getByText(/已更新计划 · 第 2 天 · 修订 1\/3/)).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Route B · 三日可执行时间轴" })
      .getByText("计划版本 2"),
  ).toBeVisible();
});
