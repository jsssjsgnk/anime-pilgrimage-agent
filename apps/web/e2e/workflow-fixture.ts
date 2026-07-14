import type { Page } from "@playwright/test";

function relativeDate(offsetDays: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + offsetDays);
  return value.toISOString().slice(0, 10);
}

export async function provideDeterministicRequirements(page: Page): Promise<void> {
  await page.route("**/api/workflows", async (route) => {
    const original = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({
        ...original,
        requirements: {
          origin: "京都",
          destination: "东京",
          start_date: relativeDate(60),
          end_date: relativeDate(62),
          anime_query: "孤独摇滚！",
          budget_level: "medium",
          walking_preference: "low",
          max_walking_meters_per_day: 5_000,
        },
      }),
    });
  });
}
