const SAFE_DETAIL_MESSAGES: readonly [RegExp, string][] = [
  [/state version conflict|version conflict/iu, "行程刚刚发生了变化，请刷新后再试。"],
  [/must retain at least one subject/iu, "当前工作区至少需要保留一部作品。"],
  [/at most twelve subjects/iu, "一个工作区最多管理 12 部作品。"],
  [/explicit confirmation|requires confirmation/iu, "这项修改需要你明确确认后才能应用。"],
  [/workspace.*not found|not found.*workspace/iu, "当前行程已不存在或无法访问。"],
];

export async function safeApiErrorMessage(response: Response): Promise<string> {
  let detail: unknown;
  try {
    const body = await response.json() as { detail?: unknown };
    detail = body.detail;
  } catch {
    detail = undefined;
  }

  if (typeof detail === "string") {
    const known = SAFE_DETAIL_MESSAGES.find(([pattern]) => pattern.test(detail));
    if (known) return known[1];
  }
  if (response.status === 404) return "当前内容已不存在或无法访问，请刷新后重试。";
  if (response.status === 409) return "行程刚刚发生了变化，请刷新后重试。";
  if (response.status === 422) return "这次输入无法处理，请检查后重试。";
  if (response.status === 429) return "请求过于频繁，请稍后再试。";
  if (response.status >= 500) return "服务暂时不可用，请稍后再试。";
  return `请求未能完成（${response.status}），请稍后重试。`;
}
