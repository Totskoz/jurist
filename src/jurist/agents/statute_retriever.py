"""M0 fake statute retriever — walks the fake KG on a hardcoded path."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.fakes import FAKE_KG, FAKE_VISIT_PATH
from jurist.schemas import (
    CitedArticle,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    TraceEvent,
)


async def run(input: StatuteRetrieverIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    nodes, _ = FAKE_KG
    by_id = {n.article_id: n for n in nodes}

    # Brief thinking before the first tool call.
    yield TraceEvent(
        type="agent_thinking",
        data={"text": "Ik zoek eerst de bepalingen over jaarlijkse huurverhoging."},
    )

    previous: str | None = None
    for aid in FAKE_VISIT_PATH:
        await asyncio.sleep(0.4)
        if previous is None:
            tool = "search_articles"
            args = {"query": "huurverhoging maximum percentage", "top_k": 5}
        else:
            tool = "follow_cross_ref"
            args = {"from_id": previous, "to_id": aid}

        yield TraceEvent(type="tool_call_started", data={"tool": tool, "args": args})
        await asyncio.sleep(0.2)
        node = by_id[aid]
        yield TraceEvent(
            type="tool_call_completed",
            data={
                "tool": tool,
                "args": args,
                "result_summary": f"{node.label}: {node.title}",
            },
        )
        yield TraceEvent(type="node_visited", data={"article_id": aid})
        if previous is not None:
            yield TraceEvent(
                type="edge_traversed",
                data={"from_id": previous, "to_id": aid},
            )
        previous = aid

    # Final "done" tool call.
    selected = [FAKE_VISIT_PATH[0], FAKE_VISIT_PATH[3]]
    yield TraceEvent(
        type="tool_call_started",
        data={"tool": "done", "args": {"selected_ids": selected}},
    )
    yield TraceEvent(
        type="tool_call_completed",
        data={
            "tool": "done",
            "args": {"selected_ids": selected},
            "result_summary": f"{len(selected)} articles selected.",
        },
    )

    cited = [
        CitedArticle(
            bwb_id=by_id[aid].bwb_id,
            article_id=aid,
            article_label=by_id[aid].label,
            body_text=by_id[aid].body_text,
            reason="Primary rule governing this question."
            if i == 0
            else "Sets the maximum percentage this question depends on.",
        )
        for i, aid in enumerate(selected)
    ]
    out = StatuteRetrieverOut(cited_articles=cited)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
