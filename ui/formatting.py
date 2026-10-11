"""Shared formatting helpers."""
from __future__ import annotations


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def code_preview(text: str, max_lines: int, max_chars: int) -> tuple[str, bool]:
    lines = text.splitlines()
    shown = lines[:max_lines]
    block = "\n".join(shown)
    truncated = len(lines) > max_lines or len(block) > max_chars
    if len(block) > max_chars:
        block = block[:max_chars].rsplit("\n", 1)[0]
    # avoid breaking Discord formatting: escape triple backticks
    block = block.replace("```", "`\u200b``")
    return block, truncated
