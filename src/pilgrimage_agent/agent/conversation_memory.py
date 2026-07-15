"""Project-owned conversation compaction with immutable source events."""

# ruff: noqa: RUF001 -- Chinese user-facing punctuation is intentional.

from __future__ import annotations

import re

from pilgrimage_agent.agent.schemas import (
    ConversationMessage,
    ConversationPromptWindow,
    ConversationSummaryPayload,
)

RECENT_MESSAGE_LIMIT = 8
SUMMARY_TRIGGER = 24

_HARD_CONSTRAINT = re.compile(
    r"(?:必须|一定要|不要走太多|少走|步行|预算|无障碍|輪椅|轮椅|"
    r"从.{0,30}出发|住在|住宿|开始日期|结束日期|第.{0,3}天不要安排|不要自动补)"
)
_CONFIRMATION = re.compile(r"^(?:确认|同意|接受|就这样|继续执行)(?:[。！!\s]|$)")
_REJECTION = re.compile(r"(?:拒绝|不接受|取消这个|排除|清空|彻底删除|不要这个)")


def classify_memory_kind(message: ConversationMessage | str) -> str:
    """Classify user decisions without interpreting arbitrary text as instructions."""

    if isinstance(message, ConversationMessage):
        if message.role != "user":
            return message.memory_kind
        text = message.content.strip()
    else:
        text = message.strip()
    if _HARD_CONSTRAINT.search(text):
        return "hard_constraint"
    if _CONFIRMATION.search(text):
        return "confirmation"
    if _REJECTION.search(text):
        return "rejection"
    return "ordinary"


def build_summary(
    messages: tuple[ConversationMessage, ...],
) -> ConversationSummaryPayload | None:
    """Summarize only the old window while keeping exact critical decisions."""

    if len(messages) < SUMMARY_TRIGGER:
        return None
    summarized = messages[:-RECENT_MESSAGE_LIMIT]
    if not summarized:
        return None
    user_turns = tuple(item for item in summarized if item.role == "user")
    compact_turns = user_turns[-24:]
    lines = tuple(
        f"用户：{item.content.strip()[:240]}"
        for item in compact_turns
        if item.content.strip()
    )
    summary = "此前对话摘要：\n" + ("\n".join(lines) or "尚无较早的用户消息。")
    critical = tuple(
        dict.fromkeys(
            item.content.strip()[:500]
            for item in summarized
            if item.role == "user"
            and item.memory_kind in {"hard_constraint", "confirmation", "rejection"}
            and item.content.strip()
        )
    )[-120:]
    return ConversationSummaryPayload(
        source_first_message_id=summarized[0].message_id,
        through_message_id=summarized[-1].message_id,
        summarized_message_count=len(summarized),
        summary=summary[:8000],
        critical_decisions=critical,
    )


def build_prompt_window(
    messages: tuple[ConversationMessage, ...],
    summary: ConversationSummaryPayload | None,
) -> ConversationPromptWindow:
    """Combine a traceable summary, exact decisions, and the recent working set."""

    recent = messages[-RECENT_MESSAGE_LIMIT:]
    critical = tuple(
        dict.fromkeys(
            (
                *(summary.critical_decisions if summary else ()),
                *(
                    item.content.strip()[:500]
                    for item in messages
                    if item.role == "user"
                    and item.memory_kind
                    in {"hard_constraint", "confirmation", "rejection"}
                ),
            )
        )
    )[-120:]
    return ConversationPromptWindow(
        summary=summary.summary if summary else None,
        critical_decisions=critical,
        recent_messages=recent,
    )
