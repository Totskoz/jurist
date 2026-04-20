"""NetworkX-backed concrete KnowledgeGraph."""
from __future__ import annotations

from pathlib import Path

import networkx as nx

from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


class NetworkXKG:
    """Concrete KnowledgeGraph. DiGraph node attrs mirror ArticleNode fields
    (minus article_id, which is the node key); edge attrs carry kind + context.
    """

    def __init__(self, graph: nx.DiGraph) -> None:
        self._graph = graph

    @classmethod
    def load_from_json(cls, path: Path) -> NetworkXKG:
        text = path.read_text(encoding="utf-8")  # FileNotFoundError propagates
        snap = KGSnapshot.model_validate_json(text)  # ValidationError propagates
        return cls.from_snapshot(snap)

    @classmethod
    def from_snapshot(cls, snap: KGSnapshot) -> NetworkXKG:
        node_ids = [n.article_id for n in snap.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate article_id in KG snapshot")
        edge_keys = [(e.from_id, e.to_id) for e in snap.edges]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("duplicate edge in KG snapshot")

        g = nx.DiGraph()
        for n in snap.nodes:
            attrs = n.model_dump()
            attrs.pop("article_id")
            g.add_node(n.article_id, **attrs)
        for e in snap.edges:
            g.add_edge(e.from_id, e.to_id, kind=e.kind, context=e.context)
        return cls(g)

    def all_nodes(self) -> list[ArticleNode]:
        out: list[ArticleNode] = []
        for nid, attrs in self._graph.nodes(data=True):
            out.append(ArticleNode(article_id=nid, **attrs))
        return out

    def all_edges(self) -> list[ArticleEdge]:
        out: list[ArticleEdge] = []
        for u, v, attrs in self._graph.edges(data=True):
            out.append(ArticleEdge(from_id=u, to_id=v, **attrs))
        return out

    def get_node(self, article_id: str) -> ArticleNode | None:
        if article_id not in self._graph.nodes:
            return None
        attrs = dict(self._graph.nodes[article_id])
        return ArticleNode(article_id=article_id, **attrs)
