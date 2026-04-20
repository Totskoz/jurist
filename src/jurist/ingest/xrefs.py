"""Cross-reference extraction: regex fallback pass + dedup merge.

See spec §5.3. Explicit edges from <intref>/<extref> are already fully resolved
by the parser (Task 9) — no sentinel resolution step needed.

This module:
  1. extract_regex_edges — same-BWB leading-number regex scan over body_text.
  2. merge_edges — dedup by (from_id, to_id); explicit wins over regex.
"""
from __future__ import annotations

import re

from jurist.schemas import ArticleEdge, ArticleNode

_ARTIKEL_RE = re.compile(r"\bartikel(?:en)?\s+(\d+[a-z]?)(?![\d:])", re.IGNORECASE)


def extract_regex_edges(nodes: list[ArticleNode]) -> list[ArticleEdge]:
    """Scan each node's body_text for article references; emit same-BWB edges.

    Resolution: look up "Artikel{N}" suffix within the same bwb_id. Missing
    targets (cross-BWB mentions, typos) → drop silently.
    """
    by_bwb: dict[str, dict[str, str]] = {}
    for n in nodes:
        suffix = n.article_id.rsplit("/", 1)[-1]  # e.g. "Artikel248"
        by_bwb.setdefault(n.bwb_id, {})[suffix] = n.article_id

    edges: list[ArticleEdge] = []
    seen: set[tuple[str, str]] = set()
    for n in nodes:
        for m in _ARTIKEL_RE.finditer(n.body_text):
            target_suffix = f"Artikel{m.group(1)}"
            target_id = by_bwb.get(n.bwb_id, {}).get(target_suffix)
            if target_id is None or target_id == n.article_id:
                continue
            key = (n.article_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                ArticleEdge(from_id=n.article_id, to_id=target_id, kind="regex", context=None)
            )
    return edges


def merge_edges(
    explicit: list[ArticleEdge], regex: list[ArticleEdge]
) -> list[ArticleEdge]:
    """Dedup by (from_id, to_id); explicit wins over regex."""
    seen: dict[tuple[str, str], ArticleEdge] = {}
    for e in explicit:
        seen[(e.from_id, e.to_id)] = e
    for e in regex:
        seen.setdefault((e.from_id, e.to_id), e)
    return list(seen.values())
