"""Prompt template loading + rendering."""
from __future__ import annotations

from pathlib import Path

from jurist.agents.statute_retriever_tools import build_catalog
from jurist.kg.interface import KnowledgeGraph

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def render_statute_retriever_system(
    kg: KnowledgeGraph,
    *,
    snippet_chars: int = 200,
) -> str:
    """Load statute_retriever.system.md and substitute the article catalog."""
    template = (_PROMPTS_DIR / "statute_retriever.system.md").read_text(encoding="utf-8")
    catalog = build_catalog(kg, snippet_chars=snippet_chars)
    return template.replace("{{ARTICLE_CATALOG}}", catalog)
