import { expect, test } from "@playwright/test";

test("works can be added, confirmed, edited, and removed without restarting", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await page.getByLabel("你的巡礼想法").fill("我想用一天巡礼轻音少女");
  await page.getByRole("button", { name: "开始规划" }).click();
  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible();
  await page.getByRole("button", { name: "选择全部季度与版本" }).click();
  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 60_000 });

  if (testInfo.project.name.startsWith("mobile")) {
    await page.getByRole("button", { name: "行程信息" }).click();
  }
  await page.getByLabel("添加作品").fill("孤独摇滚！");
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
  await page.getByRole("button", { name: "确认并重新规划" }).click();

  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible({ timeout: 30_000 });
  const bocchiGroup = page.getByRole("group", { name: /孤独摇滚/u });
  await expect(bocchiGroup.getByRole("checkbox").first()).toBeChecked();
  await page.getByRole("button", { name: "确认并整理地点" }).click();
  await expect(page.getByRole("button", { name: "生成层级行程" })).toBeVisible({ timeout: 60_000 });

  if (testInfo.project.name.startsWith("mobile")) {
    await page.getByRole("button", { name: "行程信息" }).click();
  }
  const kOnItem = page.getByRole("listitem").filter({ hasText: "轻音少女" });
  const bocchiItem = page.getByRole("listitem").filter({ hasText: "孤独摇滚！" });
  await expect(kOnItem.getByText("3 个条目", { exact: true })).toBeVisible();
  await expect(bocchiItem.getByText("1 个条目", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑已选版本" }).click();
  await expect(page.getByRole("heading", { name: "作品匹配结果" })).toBeVisible();
  await expect(bocchiGroup.getByRole("checkbox").first()).toBeChecked();
  await page.getByRole("button", { name: "取消编辑" }).click();

  if (testInfo.project.name.startsWith("mobile")) {
    await page.getByRole("button", { name: "行程信息" }).click();
  }
  await page.getByRole("button", { name: "移除作品 孤独摇滚！" }).click();
  await page.getByRole("button", { name: "确认并重新规划" }).click();
  await expect(kOnItem.getByText("3 个条目", { exact: true })).toBeVisible();
  await expect(bocchiItem).toHaveCount(0);
});
