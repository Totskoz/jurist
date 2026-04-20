"""Statute retriever tool implementations + helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jurist.kg.interface import KnowledgeGraph


def make_snippet(body: str, max_chars: int = 200) -> str:
    """Collapse whitespace and truncate to a word boundary with an ellipsis."""
    compact = " ".join(body.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "…"


@dataclass
class ToolResult:
    """Normalized tool execution result.

    - result_summary: human-readable one-liner for TracePanel.
    - extra: structured fields surfaced in TraceEvent.data (hit_ids,
      neighbor_ids, body_text, outgoing_refs, etc.) AND serialized into
      the Anthropic tool_result content.
    - is_error: follows Anthropic tool_result semantics.
    - kg_effect: signals to the caller (the retriever agent) which KG-state
      event to emit next: {"node_visited": id} or
      {"edge_traversed": (from, to)}.
    """

    result_summary: str
    extra: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    kg_effect: dict[str, Any] | None = None


class ToolExecutor:
    def __init__(self, kg: KnowledgeGraph, snippet_chars: int = 200) -> None:
        self._kg = kg
        self._snippet_chars = snippet_chars

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        handlers = {
            "search_articles": self._search_articles,
            "list_neighbors": self._list_neighbors,
            "get_article": self._get_article,
            "follow_cross_ref": self._follow_cross_ref,
            "done": self._validate_done,
        }
        handler = handlers.get(name)
        if handler is None:
            return ToolResult(
                result_summary=f"unknown tool: {name}",
                is_error=True,
            )
        return handler(args)

    def _get_article(self, args: dict[str, Any]) -> ToolResult:
        article_id = args.get("article_id")
        if not article_id:
            return ToolResult(
                result_summary="missing required argument: article_id",
                is_error=True,
            )
        node = self._kg.get_node(article_id)
        if node is None:
            return ToolResult(
                result_summary=f"unknown article_id: {article_id}",
                is_error=True,
            )
        return ToolResult(
            result_summary=f"{node.label} — {node.title}",
            extra={
                "article_id": article_id,
                "label": node.label,
                "title": node.title,
                "body_text": node.body_text,
                "outgoing_refs": list(node.outgoing_refs),
            },
            kg_effect={"node_visited": article_id},
        )

    # Subsequent tasks fill in.
    def _search_articles(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def _list_neighbors(self, args: dict[str, Any]) -> ToolResult:
        article_id = args.get("article_id")
        if not article_id:
            return ToolResult(
                result_summary="missing required argument: article_id",
                is_error=True,
            )
        node = self._kg.get_node(article_id)
        if node is None:
            return ToolResult(
                result_summary=f"unknown article_id: {article_id}",
                is_error=True,
            )
        neighbors: list[dict[str, str]] = []
        for nid in node.outgoing_refs:
            nb = self._kg.get_node(nid)
            if nb is None:
                # In-corpus-only invariant: outgoing_refs should be filtered by
                # ingester; but be defensive.
                continue
            neighbors.append({
                "article_id": nid,
                "label": nb.label,
                "title": nb.title,
            })
        return ToolResult(
            result_summary=f"{len(neighbors)} neighbor(s)",
            extra={
                "neighbors": neighbors,
                "neighbor_ids": [n["article_id"] for n in neighbors],
            },
        )

    def _follow_cross_ref(self, args: dict[str, Any]) -> ToolResult:
        from_id = args.get("from_id")
        to_id = args.get("to_id")
        if not from_id or not to_id:
            return ToolResult(
                result_summary="missing required arguments: from_id, to_id",
                is_error=True,
            )
        from_node = self._kg.get_node(from_id)
        if from_node is None:
            return ToolResult(
                result_summary=f"unknown from_id: {from_id}",
                is_error=True,
            )
        to_node = self._kg.get_node(to_id)
        if to_node is None:
            return ToolResult(
                result_summary=f"unknown to_id: {to_id}",
                is_error=True,
            )
        if not self._kg.has_edge(from_id, to_id):
            return ToolResult(
                result_summary=(
                    f"no edge from {from_id} to {to_id} in the corpus — "
                    f"use get_article({to_id}) if you only need the content."
                ),
                is_error=True,
            )
        return ToolResult(
            result_summary=f"{to_node.label} — {to_node.title}",
            extra={
                "article_id": to_id,
                "label": to_node.label,
                "title": to_node.title,
                "body_text": to_node.body_text,
                "outgoing_refs": list(to_node.outgoing_refs),
            },
            kg_effect={"edge_traversed": (from_id, to_id), "node_visited": to_id},
        )

    def _validate_done(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
