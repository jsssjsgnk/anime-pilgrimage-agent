import { expect, test } from "@playwright/test";
import { captureEvidence } from "./screenshot-evidence";
import { provideDeterministicRequirements } from "./workflow-fixture";

test("confirmed Route A becomes a validated three-day Route B", async ({ page }, testInfo) => {
  await provideDeterministicRequirements(page);
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await page.getByRole("button", { name: /确认条件并查询 Bangumi/ }).click();
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();

  await expect(page.getByRole("heading", { name: "选择抵离交通与住宿基地" })).toBeVisible();
  await page.getByRole("radio", { name: "选择去程 人工交通" }).click();
  await page.getByRole("radio", { name: "选择返程 人工交通" }).click();
  await page.getByRole("radio", { name: /选择基地 .*Route A 中心候选/ }).click();
  await expect(page.getByRole("radio", { name: /选择基地 .*Route A 中心候选/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  const routeBResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/workflows\/[^/]+\/resume$/.test(new URL(response.url()).pathname),
    { timeout: 20_000 },
  );
  await page.getByRole("button", { name: /生成可执行 Route B/ }).click();
  expect((await routeBResponse).ok()).toBe(true);

  const timeline = page.getByRole("region", { name: "Route B · 三日可执行时间轴" });
  await expect(
    timeline.getByRole("heading", { name: "Route B · 三日可执行时间轴" }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(timeline.getByText("ORS 道路估算")).toBeVisible();
  await expect(timeline.getByText(/Route A 中心候选/, { exact: true })).toBeVisible();
  await expect(timeline.getByText(/DAY 01/)).toBeVisible();
  await expect(timeline.getByRole("link", { name: /现场导航 1/ }).first()).toHaveAttribute(
    "href",
    /https:\/\/www\.google\.com\/maps\/dir\/\?api=1/,
  );

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-3-mobile.png"
    : "phase-3-desktop.png";
  await captureEvidence(page, testInfo, screenshotName);
});
