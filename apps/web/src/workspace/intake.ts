const TITLE_BRACKETS = /[《「『【]([^》」』】]{1,100})[》」』】]/g;
const CONTEXT_TAIL = /[，,。；;]\s*(?:住|住宿|从|出发|每天|希望|预算|日期|时间|步行|交通|安排|基地|大概|然后).*$/u;
const INTENT_PREFIX = /^.*?(?:巡礼|打卡|探访|去看)\s*/u;
const JOINERS = /\s*(?:、|,|，|；|;|\n|以及|还有|或者|和|与|跟|及)\s*/u;

function cleanTitle(value: string): string {
  return value
    .replace(/^[\s“”"'《》「」『』【】]+|[\s“”"'《》「」『』【】]+$/gu, "")
    .replace(/^(?:我想|我想要|想要|想|计划|准备|打算)\s*/u, "")
    .replace(/\s*(?:这几部|这些)?(?:动画|动漫|作品)\s*$/u, "")
    .trim();
}

function uniqueTitles(values: string[]): string[] {
  return [...new Set(values.map(cleanTitle).filter((value) => value.length > 0 && value.length <= 100))].slice(0, 3);
}

export function extractSubjectQueries(input: string): string[] {
  const bracketed = [...input.matchAll(TITLE_BRACKETS)].map((match) => match[1] ?? "");
  if (bracketed.length > 0) return uniqueTitles(bracketed);

  const withoutContext = input.trim().replace(CONTEXT_TAIL, "");
  const titleSegment = withoutContext.replace(INTENT_PREFIX, "");
  return uniqueTitles(titleSegment.split(JOINERS));
}
