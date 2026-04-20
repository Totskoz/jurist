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


# Minimal Dutch + English stop-words; low-cost coarse filter.
_STOP_WORDS = frozenset({
    "de", "het", "een", "en", "of", "in", "van", "op", "met", "bij",
    "te", "ten", "tot", "dat", "die", "dit", "deze", "is", "zijn",
    "wordt", "worden", "niet", "geen", "als", "ook", "maar", "nog",
    "the", "and", "or", "to", "a", "an", "are",
})


def _tokenize(text: str) -> set[str]:
    return {
        t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
        if t and t not in _STOP_WORDS and len(t) > 1
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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

    def _search_articles(self, args: dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        top_k = int(args.get("top_k") or 5)
        top_k = max(1, min(top_k, 10))
        if not query:
            return ToolResult(
                result_summary="0 hits (empty query)",
                extra={"hits": [], "hit_ids": []},
            )
        q_tokens = _tokenize(query)
        scored: list[tuple[float, Any]] = []
        for node in self._kg.all_nodes():
            snippet = make_snippet(node.body_text, self._snippet_chars)
            field_tokens = _tokenize(f"{node.title} {snippet}")
            score = _jaccard(q_tokens, field_tokens)
            if score > 0:
                scored.append((score, node))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, node in scored[:top_k]:
            hits.append({
                "article_id": node.article_id,
                "label": node.label,
                "title": node.title,
                "snippet": make_snippet(node.body_text, self._snippet_chars),
                "score": round(score, 4),
            })
        return ToolResult(
            result_summary=f"{len(hits)} hit(s)",
            extra={"hits": hits, "hit_ids": [h["article_id"] for h in hits]},
        )

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
        selected = args.get("selected")
        if selected is None or not isinstance(selected, list):
            return ToolResult(
                result_summary="`selected` must be a list of {article_id, reason}",
                is_error=True,
            )
        unknown: list[str] = []
        missing_reason: list[str] = []
        for entry in selected:
            if not isinstance(entry, dict):
                return ToolResult(
                    result_summary="each entry must be {article_id, reason}",
                    is_error=True,
                )
            aid = entry.get("article_id")
            reason = entry.get("reason")
            if not aid:
                return ToolResult(
                    result_summary="entry missing article_id",
                    is_error=True,
                )
            if not reason:
                missing_reason.append(aid)
                continue
            if self._kg.get_node(aid) is None:
                unknown.append(aid)
        if unknown:
            return ToolResult(
                result_summary=(
                    f"unknown article_id(s) in selected: {unknown}. "
                    f"Pick from the catalog you were given."
                ),
                is_error=True,
            )
        if missing_reason:
            return ToolResult(
                result_summary=f"missing reason for: {missing_reason}",
                is_error=True,
            )
        return ToolResult(
            result_summary=f"{len(selected)} selected",
            extra={"selected_count": len(selected), "selected": selected},
        )
