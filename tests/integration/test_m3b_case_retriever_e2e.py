"""M3b end-to-end integration test. Gated on RUN_E2E=1.

Requires:
- ANTHROPIC_API_KEY in env
- data/lancedb/cases.lance populated from M3a ingest
- bge-m3 model in HuggingFace cache
"""
from __future__ import annotations

import os
import re

import pytest

_RUN_E2E = os.getenv("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_E2E,
    reason="integration test — set RUN_E2E=1 to run (costs Anthropic tokens + ~30s)",
)


@pytest.mark.asyncio
async def test_m3b_locked_question_returns_three_valid_cases() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    from anthropic import AsyncAnthropic

    from jurist.agents import case_retriever
    from jurist.config import RunContext, settings
    from jurist.embedding import Embedder
    from jurist.kg.networkx_kg import NetworkXKG
    from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut, CitedArticle
    from jurist.vectorstore import CaseStore

    # Preconditions
    if not settings.lance_path.exists():
        pytest.skip(
            f"LanceDB index missing at {settings.lance_path} — "
            "run `uv run python -m jurist.ingest.caselaw` first"
        )
    if not settings.kg_path.exists():
        pytest.skip(
            f"KG missing at {settings.kg_path} — "
            "run `uv run python -m jurist.ingest.statutes` first"
        )

    # Wire up real RunContext
    kg = NetworkXKG.load_from_json(settings.kg_path)
    store = CaseStore(settings.lance_path)
    store.open_or_create()
    assert store.row_count() > 0, "LanceDB is empty"

    embedder = Embedder(model_name=settings.embed_model)
    llm = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    ctx = RunContext(kg=kg, llm=llm, case_store=store, embedder=embedder)

    # Realistic M4-shape input (stand in for the decomposer + M2 retriever
    # that are wired earlier in the full pipeline).
    inp = CaseRetrieverIn(
        question=(
            "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
        ),
        sub_questions=[
            "Mag een verhuurder de huur eenzijdig met 15% verhogen?",
            "Geldt de maximale huurverhoging voor zowel gereguleerde als "
            "geliberaliseerde huurwoningen?",
            "Wat kan de huurder doen tegen een buitensporige huurverhoging?",
        ],
        statute_context=[
            CitedArticle(
                bwb_id="BWBR0005290",
                article_id="BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel248",
                article_label="Boek 7, Artikel 248",
                body_text="De verhuurder kan tot aan het tijdstip...",
                reason="Regelt jaarlijkse huurverhoging bij gereguleerde huur.",
            ),
        ],
    )

    events = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    final = events[-1]
    assert final.type == "agent_finished", (
        f"expected agent_finished, got {final.type} events={[e.type for e in events]}"
    )
    out = CaseRetrieverOut.model_validate(final.data)

    # Acceptance assertions (spec §15)
    assert len(out.cited_cases) == 3

    all_eclis = store.all_eclis()
    for c in out.cited_cases:
        # ECLI exists in LanceDB
        assert c.ecli in all_eclis, f"rerank picked unknown ECLI {c.ecli}"
        # Similarity in (0, 1]
        assert 0.0 < c.similarity <= 1.0 + 1e-6, (
            f"implausible similarity {c.similarity} for {c.ecli}"
        )
        # Reason non-trivial Dutch
        assert len(c.reason.strip()) >= 20, (
            f"reason too short for {c.ecli}: {c.reason!r}"
        )
        # Contains at least one Dutch letter (lowercase ascii a-z)
        assert re.search(r"[a-z]", c.reason.casefold()), (
            f"reason lacks letters: {c.reason!r}"
        )
        # URL pattern
        assert re.match(
            r"^https://uitspraken\.rechtspraak\.nl/details\?id=ECLI:",
            c.url,
        ), f"unexpected URL: {c.url}"

    # 3 distinct ECLIs
    assert len({c.ecli for c in out.cited_cases}) == 3
