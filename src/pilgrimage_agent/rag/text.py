"""Safe extraction, normalization, multilingual tokens, and bounded chunks."""

from __future__ import annotations

import base64
import io
import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
LATIN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "s",
        "should",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
    }
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\x00", "")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def lexical_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).lower()
    latin = [
        token
        for token in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", normalized)
        if token not in LATIN_STOPWORDS
    ]
    cjk_runs = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", normalized)
    cjk = [run[index : index + 2] for run in cjk_runs for index in range(len(run) - 1)]
    singles = [run for run in cjk_runs if len(run) == 1]
    return tuple((*latin, *cjk, *singles))


@dataclass(frozen=True)
class ExtractedText:
    text: str
    page_count: int | None
    status: str
    warning: str | None = None


def extract_text_content(
    content: str, *, media_type: str, content_is_base64: bool
) -> ExtractedText:
    if media_type == "application/pdf":
        if not content_is_base64:
            raise ValueError("PDF content must be base64 encoded")
        try:
            payload = base64.b64decode(content, validate=True)
        except ValueError as error:
            raise ValueError("PDF content is not valid base64") from error
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("document exceeds the 10 MiB limit")
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError("PDF exceeds the 200 page limit")
        pages = [normalize_text(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(page for page in pages if page)
        if len(text) < 80:
            return ExtractedText(
                text=text,
                page_count=len(reader.pages),
                status="needs_ocr",
                warning="PDF contains too little extractable text; OCR is not performed.",
            )
        return ExtractedText(text=text, page_count=len(reader.pages), status="active")

    payload = content.encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("document exceeds the 10 MiB limit")
    return ExtractedText(text=normalize_text(content), page_count=None, status="active")
