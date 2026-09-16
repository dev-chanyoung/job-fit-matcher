"""Shared helpers for parsing LLM text responses."""

import re

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (e.g. ```json ... ```) if present."""
    text = text.strip()
    if text.startswith("```"):
        text = _CODE_FENCE_RE.sub("", text).strip()
    return text
