import { expect, test } from "@playwright/test";

test("subject search requires confirmation before showing sourced Route A", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: /整理旅行条件/ }).click();

  await expect(page.getByRole("heading", { name: "确认你要巡礼的作品" })).toBeVisible();
  await expect(page.getByText("Bangumi #328609")).toBeVisible();
  await expect(page.getByRole("heading", { name: "孤独摇滚！" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Route A/ })).toHaveCount(0);

  await page.getByRole("button", { name: "确认并查看 Route A" }).click();
  await expect(page.getByRole("button", { name: /已确认此作品/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: /Route A · 3 个有来源点位/ })).toBeVisible();
  await expect(page.getByLabel(/Route A 地图，共 3 个点/)).toBeVisible();
  await expect(page.getByText("下北泽站东口")).toBeVisible();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-2-mobile.png"
    : "phase-2-desktop.png";
  await page.screenshot({
    path: `../../artifacts/screenshots/${screenshotName}`,
    fullPage: true,
  });
});
