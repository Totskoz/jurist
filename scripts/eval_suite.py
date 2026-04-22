"""M5 — manifest-driven eval harness.

Runs the full pipeline (via the orchestrator) for each question in
tests/eval/questions.yaml, evaluates a small fixed-vocabulary DSL of
assertions, and writes:
- out/m5-eval/<Q>/trace.jsonl, answer.md, summary.json
- docs/evaluations/2026-04-22-m5-suite-<pre|post>.md (opens with a rollup table)

Decision M5-4: simple fixed-vocabulary assertion DSL, not sandboxed eval().
Allowed functions in assertions: contains(x, substr), count_contains(x, substr),
len(x), `==`, `>=`, `<=`, `and`, `or`, `not`.

Namespace for assertions:
- `answer`: the StructuredAnswer (dict form)
- `decomposer`: the DecomposerOut (dict form)

Usage:
  uv run python scripts/eval_suite.py --label pre    # runs against current branch
  uv run python scripts/eval_suite.py --label post
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from anthropic import AsyncAnthropic

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import RunContext, settings
from jurist.embedding import Embedder
from jurist.kg.networkx_kg import NetworkXKG
from jurist.vectorstore import CaseStore

MANIFEST = Path("tests/eval/questions.yaml")
OUT_DIR = Path("out/m5-eval")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def contains(text: str | None, substr: str) -> bool:
    return bool(text) and substr in text


def count_contains(text: str | None, substr: str) -> int:
    return 0 if not text else text.count(substr)


class _DotDict(dict):
    def __getattr__(self, k):
        v = self[k] if k in self else None
        if isinstance(v, dict):
            return _DotDict(v)
        return v


class AssertionRunner:
    """Fixed-vocabulary DSL. Not a general-purpose evaluator."""

    ALLOWED = {"contains": contains, "count_contains": count_contains, "len": len}

    def __init__(self, answer: dict, decomposer: dict) -> None:
        self.ns = {
            "answer": _DotDict(answer or {}),
            "decomposer": _DotDict(decomposer or {}),
            **self.ALLOWED,
        }

    def check(self, expr: str) -> bool:
        # Restrict builtins — block attribute access except via _DotDict.
        return bool(eval(expr, {"__builtins__": {}}, self.ns))  # noqa: S307


async def run_single(q: dict, ctx: RunContext) -> dict:
    run_id = f"eval_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=10_000)
    task = asyncio.create_task(run_question(q["question"], run_id, buf, ctx))
    events = []
    async for ev in buf.subscribe():
        events.append(ev.model_dump())
    await task

    final = next(
        (e for e in reversed(events) if e["type"] == "run_finished"),
        None,
    )
    answer = final["data"]["final_answer"] if final else {}
    decomposer = next(
        (
            e["data"]
            for e in events
            if e["type"] == "agent_finished" and e.get("agent") == "decomposer"
        ),
        {},
    )

    return {
        "id": q["id"],
        "question": q["question"].strip(),
        "expect_kind": q["expect_kind"],
        "actual_kind": (answer or {}).get("kind", "unknown"),
        "events_total": len(events),
        "assertions": [
            {"expr": a, "result": AssertionRunner(answer, decomposer).check(a)}
            for a in q.get("assertions", [])
        ],
        "answer": answer,
        "decomposer_out": decomposer,
        "events": events,
    }


def render_summary_md(results: list[dict], label: str) -> str:
    ts = datetime.now(UTC).isoformat()
    header = f"# M5 eval suite — {label} ({ts})\n\n"
    table = [
        "| id | expect | actual | assertions |",
        "|----|--------|--------|------------|",
    ]
    for r in results:
        asserts_ok = sum(1 for a in r["assertions"] if a["result"])
        asserts_total = len(r["assertions"])
        kind_ok = "OK" if r["actual_kind"] == r["expect_kind"] else "MISMATCH"
        table.append(
            f"| {r['id']} | {r['expect_kind']} | {r['actual_kind']} ({kind_ok}) | "
            f"{asserts_ok}/{asserts_total} |"
        )
    per_q: list[str] = []
    for r in results:
        per_q.append(f"\n## {r['id']} — {r['question']}\n")
        per_q.append(
            f"Expected kind: `{r['expect_kind']}`, actual: `{r['actual_kind']}`\n"
        )
        per_q.append("\nAssertions:\n")
        for a in r["assertions"]:
            mark = "PASS" if a["result"] else "FAIL"
            per_q.append(f"- [{mark}] `{a['expr']}`")
    return header + "\n".join(table) + "\n" + "\n".join(per_q) + "\n"


def _bootstrap_ctx() -> RunContext:
    """Load the same resources the FastAPI lifespan loads, for standalone use."""
    logger.info("Loading KG from %s", settings.kg_path)
    kg = NetworkXKG.load_from_json(settings.kg_path)
    logger.info("Loaded KG: %d nodes, %d edges", len(kg.all_nodes()), len(kg.all_edges()))

    logger.info("Opening case index from %s", settings.lance_path)
    case_store = CaseStore(settings.lance_path)
    case_store.open_or_create()
    logger.info("Case index: %d rows", case_store.row_count())

    logger.info("Loading embedder %s (cold load ~5-10s)", settings.embed_model)
    embedder = Embedder(model_name=settings.embed_model)
    logger.info("Embedder ready")

    llm = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        max_retries=settings.anthropic_max_retries,
    )
    logger.info("Anthropic client ready (max_retries=%d)", settings.anthropic_max_retries)

    return RunContext(kg=kg, llm=llm, case_store=case_store, embedder=embedder)


async def _amain(label: str) -> int:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ctx = _bootstrap_ctx()

    results: list[dict] = []
    for q in manifest:
        logger.info("Running %s: %s", q["id"], q["question"].strip()[:60])
        r = await run_single(q, ctx)
        q_dir = OUT_DIR / r["id"]
        q_dir.mkdir(exist_ok=True)
        (q_dir / "trace.jsonl").write_text(
            "\n".join(json.dumps(e) for e in r["events"]),
            encoding="utf-8",
        )
        (q_dir / "summary.json").write_text(
            json.dumps(
                {k: v for k, v in r.items() if k != "events"},
                indent=2,
            ),
            encoding="utf-8",
        )
        results.append(r)

    report_path = Path(f"docs/evaluations/2026-04-22-m5-suite-{label}.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_summary_md(results, label), encoding="utf-8")

    passed = sum(
        1
        for r in results
        if r["actual_kind"] == r["expect_kind"]
        and all(a["result"] for a in r["assertions"])
    )
    print(f"passed {passed}/{len(results)}; report: {report_path}")
    return 0 if passed == len(results) else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--label", choices=["pre", "post"], required=True)
    args = p.parse_args()
    return asyncio.run(_amain(args.label))


if __name__ == "__main__":
    sys.exit(main())
