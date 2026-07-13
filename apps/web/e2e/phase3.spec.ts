import { expect, test } from "@playwright/test";

test("confirmed Route A becomes a validated three-day Route B", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await page.getByRole("button", { name: "确认并查看 Route A" }).click();

  await expect(page.getByRole("heading", { name: "选择抵离交通与住宿基地" })).toBeVisible();
  await page.getByRole("radio", { name: "选择去程 新干线" }).click();
  await page.getByRole("radio", { name: "选择返程 新干线" }).click();
  await page.getByRole("radio", { name: "选择基地 下北泽站周边" }).click();
  await expect(page.getByRole("radio", { name: "选择基地 下北泽站周边" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByRole("button", { name: /生成可执行 Route B/ }).click();

  const timeline = page.getByRole("region", { name: "Route B · 三日可执行时间轴" });
  await expect(timeline.getByRole("heading", { name: "Route B · 三日可执行时间轴" })).toBeVisible();
  await expect(timeline.getByText("ORS 道路估算")).toBeVisible();
  await expect(timeline.getByText("下北泽站周边", { exact: true })).toBeVisible();
  await expect(timeline.getByText(/DAY 01/)).toBeVisible();
  await expect(timeline.getByRole("link", { name: /现场导航 1/ }).first()).toHaveAttribute(
    "href",
    /https:\/\/www\.google\.com\/maps\/dir\/\?api=1/,
  );

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-3-mobile.png"
    : "phase-3-desktop.png";
  await page.screenshot({
    path: `../../artifacts/screenshots/${screenshotName}`,
    fullPage: true,
  });
});
