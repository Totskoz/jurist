"""Pure retrieval helper for the M3b case retriever.

Sync; no asyncio, no Anthropic. Types live here because they are internal
in-process handoff types, not serialized across any boundary (spec §4.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from jurist.embedding import Embedder
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore


@dataclass(frozen=True)
class CaseCandidate:
    """Pre-rerank handoff from helper → agent. Not persisted; not in schemas.py."""

    ecli: str
    court: str
    date: str
    snippet: str          # first N chars of best chunk, ellipsized
    similarity: float     # cosine from best chunk (0..1]
    url: str


@dataclass(frozen=True)
class RerankPick:
    """Validated row from Haiku's select_cases tool output."""

    ecli: str
    reason: str           # Dutch justification, ≥20 chars post-strip


class InvalidRerankOutput(Exception):
    """Raised by _rerank_once for malformed output. Caught inside the agent;
    a second occurrence is wrapped in RerankFailedError and propagated."""


def retrieve_candidates(
    store: CaseStore,
    embedder: Embedder,
    query: str,
    *,
    chunks_top_k: int,
    eclis_limit: int,
    snippet_chars: int = 400,
) -> list[CaseCandidate]:
    """Embed → cosine top-K chunks → group-by-ECLI (first chunk wins, since
    results are sorted desc by similarity) → take up to `eclis_limit` unique
    ECLIs. Returns [] if the store yields no rows."""
    vec = embedder.encode([query])[0]
    scored = store.query(vec, top_k=chunks_top_k)
    if not scored:
        return []

    # Python dicts preserve insertion order; LanceDB returns rows sorted
    # descending by similarity, so the first occurrence of each ECLI is its
    # highest-scoring chunk.
    seen: dict[str, tuple[CaseChunkRow, float]] = {}  # ecli → (row, similarity)
    for row, sim in scored:
        if row.ecli not in seen:
            seen[row.ecli] = (row, sim)
        if len(seen) >= eclis_limit:
            break

    candidates: list[CaseCandidate] = []
    for row, sim in seen.values():
        snippet = _truncate(row.text, snippet_chars)
        candidates.append(CaseCandidate(
            ecli=row.ecli,
            court=row.court,
            date=row.date,
            snippet=snippet,
            similarity=float(sim),
            url=row.url,
        ))
    return candidates


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


__all__ = [
    "CaseCandidate",
    "RerankPick",
    "InvalidRerankOutput",
    "retrieve_candidates",
]
