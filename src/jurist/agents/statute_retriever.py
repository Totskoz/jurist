"""Real statute retriever — Claude Sonnet tool-use loop over the huurrecht KG."""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from jurist.agents.statute_retriever_tools import (
    ToolExecutor,
    tool_definitions,
)
from jurist.config import RunContext, settings
from jurist.llm.client import (
    Coerced,
    Done,
    TextDelta,
    ToolResultEvent,
    ToolUseStart,
    run_tool_loop,
)
from jurist.llm.prompts import render_statute_retriever_system
from jurist.schemas import (
    CitedArticle,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    TraceEvent,
)

logger = logging.getLogger(__name__)


def _build_user_message(inp: StatuteRetrieverIn) -> str:
    lines = [
        "User's question has been decomposed as follows:",
        "",
        "Sub-questions:",
        *[f"- {s}" for s in inp.sub_questions],
        "",
        "Concepts:",
        *[f"- {c}" for c in inp.concepts],
        "",
        f"Intent: {inp.intent}",
        "",
        "Select the articles from the catalog most relevant to these "
        "sub-questions and concepts. When ready, call `done`.",
    ]
    return "\n".join(lines)


async def run(
    input: StatuteRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system_prompt = render_statute_retriever_system(
        ctx.kg, snippet_chars=settings.statute_catalog_snippet_chars,
    )
    executor = ToolExecutor(ctx.kg, snippet_chars=settings.statute_catalog_snippet_chars)
    user_message = _build_user_message(input)

    started = time.monotonic()
    logger.info(
        "statute_retriever loop start: catalog_nodes=%d max_iters=%d cap_s=%.1f",
        len(ctx.kg.all_nodes()),
        settings.max_retriever_iters,
        settings.retriever_wall_clock_cap_s,
    )

    final_selected: list[dict] = []
    iter_count = 0

    async for ev in run_tool_loop(
        client=ctx.llm if not _is_mock(ctx.llm) else None,
        mock=ctx.llm if _is_mock(ctx.llm) else None,
        model=settings.model_retriever,
        executor=executor,
        system=system_prompt,
        tools=tool_definitions(),
        user_message=user_message,
        max_iters=settings.max_retriever_iters,
        wall_clock_cap_s=settings.retriever_wall_clock_cap_s,
    ):
        if isinstance(ev, TextDelta):
            yield TraceEvent(type="agent_thinking", data={"text": ev.text})
        elif isinstance(ev, ToolUseStart):
            iter_count += 1
            yield TraceEvent(
                type="tool_call_started",
                data={"tool": ev.name, "args": ev.args},
            )
        elif isinstance(ev, ToolResultEvent):
            completed_data = {
                "tool": ev.name,
                "args": ev.args,
                "result_summary": ev.result.result_summary,
                "is_error": ev.result.is_error,
                **ev.result.extra,
            }
            yield TraceEvent(type="tool_call_completed", data=completed_data)
            # KG effects
            if ev.result.kg_effect:
                if "node_visited" in ev.result.kg_effect:
                    yield TraceEvent(
                        type="node_visited",
                        data={"article_id": ev.result.kg_effect["node_visited"]},
                    )
                if "edge_traversed" in ev.result.kg_effect:
                    frm, to = ev.result.kg_effect["edge_traversed"]
                    yield TraceEvent(
                        type="edge_traversed",
                        data={"from_id": frm, "to_id": to},
                    )
        elif isinstance(ev, Done):
            final_selected = ev.selected
        elif isinstance(ev, Coerced):
            final_selected = ev.selected
            logger.warning(
                "statute_retriever coerced: reason=%s selected=%d",
                ev.reason,
                len(ev.selected),
            )
            # Emit synthetic done events so the UI shows a consistent terminator.
            args = {"coerced": True, "reason": ev.reason, "selected": ev.selected}
            yield TraceEvent(type="tool_call_started",
                             data={"tool": "done", "args": args})
            yield TraceEvent(
                type="tool_call_completed",
                data={
                    "tool": "done",
                    "args": args,
                    "result_summary": f"coerced ({ev.reason}), {len(ev.selected)} selected",
                    "is_error": False,
                    "selected_count": len(ev.selected),
                },
            )

    cited: list[CitedArticle] = []
    for entry in final_selected:
        aid = entry["article_id"]
        node = ctx.kg.get_node(aid)
        if node is None:
            logger.warning("dropping unknown article_id from final: %s", aid)
            continue
        cited.append(CitedArticle(
            bwb_id=node.bwb_id,
            article_id=aid,
            article_label=node.label,
            body_text=node.body_text,
            reason=entry["reason"],
        ))
    low_confidence = len(cited) < 3
    out = StatuteRetrieverOut(cited_articles=cited, low_confidence=low_confidence)
    logger.info(
        "statute_retriever loop end: cited=%d iters=%d elapsed_s=%.2f",
        len(cited), iter_count, time.monotonic() - started,
    )
    yield TraceEvent(type="agent_finished", data=out.model_dump())


def _is_mock(obj: object) -> bool:
    """Heuristic: MockAnthropicClient and the M4 _DualMock both expose
    `next_turn`; AsyncAnthropic does not. A dual-shape test mock may also
    expose `.messages` (for decomposer's forced-tool path), so we key on
    `next_turn` alone."""
    return hasattr(obj, "next_turn")
