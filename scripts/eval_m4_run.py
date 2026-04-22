"""Drive the full M4 pipeline on the locked question with the real Anthropic API
and dump a trace + summary + rendered answer for offline evaluation.

Outputs (relative to CWD):
  out/m4-eval/trace.jsonl    every TraceEvent, one per line
  out/m4-eval/summary.json   per-agent timings, event counts, answer shape
  out/m4-eval/answer.md      rendered Dutch answer for human inspection

Requires ANTHROPIC_API_KEY + the two ingests (KG + LanceDB). The run is awaited
before events are drained, so the terminal event (run_finished | run_failed) is
always present by the time subscribe() yields it.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # mirror jurist.config, so ANTHROPIC_API_KEY is visible before imports

LOCKED_Q = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
OUT_DIR = Path("out/m4-eval")


def _parse_iso_ms(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


async def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    from anthropic import AsyncAnthropic

    from jurist.api.orchestrator import run_question
    from jurist.api.sse import EventBuffer
    from jurist.config import RunContext, settings
    from jurist.embedding import Embedder
    from jurist.kg.networkx_kg import NetworkXKG
    from jurist.vectorstore import CaseStore

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[setup] KG:       {settings.kg_path}")
    kg = NetworkXKG.load_from_json(settings.kg_path)
    print(f"[setup] LanceDB:  {settings.lance_path}")
    store = CaseStore(settings.lance_path)
    store.open_or_create()
    n_rows = store.row_count()
    print(f"[setup] rows:     {n_rows}")
    if n_rows == 0:
        print("LanceDB empty — run jurist.ingest.caselaw first", file=sys.stderr)
        return 3
    print(f"[setup] Embedder: {settings.embed_model} (cold-load ~5-10s)")
    emb = Embedder(model_name=settings.embed_model)
    print(f"[setup] AsyncAnthropic (max_retries={settings.anthropic_max_retries})")
    llm = AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        max_retries=settings.anthropic_max_retries,
    )
    ctx = RunContext(kg=kg, llm=llm, case_store=store, embedder=emb)

    print(f"\n[run]   question: {LOCKED_Q}")
    t_wall = time.monotonic()
    buf = EventBuffer(max_history=10_000)  # evaluation needs full history
    await run_question(LOCKED_Q, run_id="eval_m4", buffer=buf, ctx=ctx)
    wall = time.monotonic() - t_wall
    print(f"[run]   orchestrator done in {wall:.2f}s")
    print(f"[run]   total events emitted: {buf._total_put}")

    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    print(f"[run]   drained {len(events)} events; terminal={events[-1].type}")

    # ---- write raw trace
    trace_path = OUT_DIR / "trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(ev.model_dump_json() + "\n")

    # ---- per-agent timings (from stamped ts)
    first_ts = _parse_iso_ms(events[0].ts)
    agent_timings: dict[str, dict[str, float]] = {}
    for ev in events:
        if ev.type == "agent_started":
            agent_timings.setdefault(ev.agent, {})["start"] = _parse_ts_safe(ev.ts)
        elif ev.type == "agent_finished":
            agent_timings.setdefault(ev.agent, {})["end"] = _parse_ts_safe(ev.ts)
    for t in agent_timings.values():
        if "start" in t and "end" in t:
            t["duration_s"] = round(t["end"] - t["start"], 3)
            t["started_at_offset_s"] = round(t["start"] - first_ts, 3)

    # ---- event counts
    per_type = Counter(ev.type for ev in events)
    per_agent_type: Counter[tuple[str, str]] = Counter()
    for ev in events:
        per_agent_type[(ev.agent, ev.type)] += 1

    summary = {
        "question": LOCKED_Q,
        "total_wall_seconds": round(wall, 3),
        "total_events": len(events),
        "terminal": events[-1].type,
        "terminal_reason": events[-1].data.get("reason")
        if events[-1].type == "run_failed"
        else None,
        "per_agent": agent_timings,
        "events_by_type": dict(per_type.most_common()),
        "events_by_agent_type": {
            f"{a}:{t}": n for (a, t), n in sorted(per_agent_type.items())
        },
        "final_answer_shape": None,
    }

    if events[-1].type == "run_finished":
        fa = events[-1].data["final_answer"]
        summary["final_answer_shape"] = {
            "korte_conclusie_len": len(fa["korte_conclusie"]),
            "aanbeveling_len": len(fa["aanbeveling"]),
            "n_wetsartikelen": len(fa["relevante_wetsartikelen"]),
            "n_uitspraken": len(fa["vergelijkbare_uitspraken"]),
            "article_ids": [a["article_id"] for a in fa["relevante_wetsartikelen"]],
            "eclis": [u["ecli"] for u in fa["vergelijkbare_uitspraken"]],
            "quote_lengths_articles": [
                len(a["quote"]) for a in fa["relevante_wetsartikelen"]
            ],
            "quote_lengths_cases": [
                len(u["quote"]) for u in fa["vergelijkbare_uitspraken"]
            ],
        }

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- rendered answer
    if events[-1].type == "run_finished":
        fa = events[-1].data["final_answer"]
        lines: list[str] = []
        lines.append(f"# Antwoord\n\n**Vraag:** *{LOCKED_Q}*\n")
        lines.append(f"## Korte conclusie\n\n{fa['korte_conclusie']}\n")
        lines.append("## Relevante wetsartikelen\n")
        for wa in fa["relevante_wetsartikelen"]:
            lines.append(
                f"### {wa['article_label']} — `{wa['article_id']}` "
                f"(bwb: `{wa['bwb_id']}`)\n"
            )
            lines.append(f"> {wa['quote']}\n")
            lines.append(f"{wa['explanation']}\n")
        lines.append("## Vergelijkbare uitspraken\n")
        for uc in fa["vergelijkbare_uitspraken"]:
            lines.append(f"### `{uc['ecli']}`\n")
            lines.append(f"> {uc['quote']}\n")
            lines.append(f"{uc['explanation']}\n")
        lines.append(f"## Aanbeveling\n\n{fa['aanbeveling']}\n")
        (OUT_DIR / "answer.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n[out]   trace:   ", trace_path)
    print("[out]   summary: ", OUT_DIR / "summary.json")
    print("[out]   answer:  ", OUT_DIR / "answer.md")
    print(f"\n[done]  wall={wall:.2f}s events={len(events)} terminal={events[-1].type}")
    return 0 if events[-1].type == "run_finished" else 1


def _parse_ts_safe(s: str) -> float:
    try:
        return _parse_iso_ms(s)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
