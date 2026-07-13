import { expect, test } from "@playwright/test";

test("foundation shell is responsive and captures a request", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /真正走得完的旅程/ })).toBeVisible();
  await expect(page.getByText("只读规划 · 不预订 · 不付款")).toBeVisible();
  await page.getByRole("button", { name: /整理旅行条件/ }).click();
  await expect(page.getByText(/不会静默确认关键选择/)).toBeVisible();

  const screenshotName = testInfo.project.name.startsWith("mobile")
    ? "phase-1-mobile.png"
    : "phase-1-desktop.png";
  await page.screenshot({
    path: `../../artifacts/screenshots/${screenshotName}`,
    fullPage: true,
  });
});

