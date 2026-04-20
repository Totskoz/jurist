"""Statute retriever tool implementations + helpers."""
from __future__ import annotations


def make_snippet(body: str, max_chars: int = 200) -> str:
    """Collapse whitespace and truncate to a word boundary with an ellipsis."""
    compact = " ".join(body.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "…"
