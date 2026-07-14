import { expect, type Page } from "@playwright/test";

export async function startWorkspace(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "开始规划" }).click();
  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible({ timeout: 30_000 });
}

export async function confirmWorkspace(page: Page) {
  await startWorkspace(page);
  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 30_000 });
}

export async function planWorkspace(page: Page) {
  await confirmWorkspace(page);
  await page.getByRole("button", { name: "生成层级行程" }).click();
  await expect(page.getByRole("heading", { name: "分日行程" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "已排程" })).toHaveClass(/is-active/u);
}
