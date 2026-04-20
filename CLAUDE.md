# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Jurist is a portfolio multi-agent demo answering Dutch **huurrecht** (tenancy law) questions with grounded citations. Locked demo question: *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*. Built as interview prep for an AI-engineer role at DAS (Dutch legal insurance). The scope is deliberately small — one rechtsgebied, ~9 KG nodes, ~300 cases, four live agents + one stubbed validator.

**Authoritative design:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`. Read this before making substantive design decisions. Milestone plans live in `docs/superpowers/plans/YYYY-MM-DD-*.md`.

Current state: **M1 complete** (tag `m1-statute-ingestion`) — real huurrecht KG (218 articles, 283 edges from BW7 Titel 4 + Uhw) loaded at FastAPI startup. M0 fake agents still drive the run — `/api/ask` returns the locked hardcoded answer. M2–M5 each replace a remaining fake with real code (see the spec's milestones section).

## Commands

### Backend (Python 3.11, `uv`)

- Install deps: `uv sync --extra dev`
- Build KG (prerequisite for API start): `uv run python -m jurist.ingest.statutes --refresh -v`
- Run full test suite: `uv run pytest -v` (~75s due to `asyncio.sleep` in fake agents)
- Run a single test: `uv run pytest tests/api/test_orchestrator.py::test_orchestrator_runs_agents_in_expected_order -v`
- Lint: `uv run ruff check .`
- Start API server: `uv run python -m jurist.api` — listens on `http://127.0.0.1:8766` with hot-reload. API hard-fails at startup if `data/kg/huurrecht.json` is missing — run the KG build step first on a fresh clone.

### Frontend (Node 20+, from `web/`)

- Install deps: `cd web && npm install`
- Typecheck: `cd web && npx tsc --noEmit`
- Start dev server: `cd web && npm run dev` — Vite on `http://localhost:5173`, proxies `/api/*` → `127.0.0.1:8766`
- Production build: `cd web && npm run build`

### Environment quirks

- `uv` lives at `C:\Users\totti\.local\bin` and isn't always on `PATH`. Prepend it in bash with `export PATH="/c/Users/totti/.local/bin:$PATH"` if `uv` is not found.
- Git's LF→CRLF warnings on Windows commits are benign; don't try to suppress them.
- API port is **8766**, not 8000 (Django project on this host) and not 8765 (previous zombie-socket incident). If you change the backend port, also change the Vite proxy target in `web/vite.config.ts`.
- Full M0 run emits ~184 events (mostly `answer_delta` tokens from the synthesizer's word-level streaming). `EventBuffer.max_history` defaults to 500 to hold a full run's history; `settings.max_history_per_run` matches. If you shrink these, verify the `test_orchestrator_emits_run_started_and_run_finished` test still passes.

## Architecture

### Agent contract (spec §5)

Every agent — real or fake — is an async generator with this shape:

```python
async def run(input: AgentIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    # ... domain events (thinking, tool calls, node_visited, answer_delta, etc.)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

The **final** yielded event is always `agent_finished` with the typed Pydantic output serialized into `.data`. Orchestrator downstream re-validates via `AgentOut.model_validate(final.data)`. Agents yield events **unstamped** — `agent`, `run_id`, and `ts` fields are filled in by `_pump` in the orchestrator, not by the agent.

### Pipeline

`orchestrator.run_question` chains 5 agents sequentially, wiring each agent's output into the next's input:

```
run_started
  → decomposer  (question → sub_questions, concepts, intent)
  → statute_retriever  (from decomposer out → cited_articles)
  → case_retriever  (from decomposer + stat.cited_articles → cited_cases)
  → synthesizer  (question + stat + case → StructuredAnswer)
  → validator  (question + all context → valid?)
run_finished (carries final_answer)
```

All 5 run on one asyncio task. Parallelization is explicitly out of scope for v1 (spec §15 decision log).

### SSE transport

- `EventBuffer` (`src/jurist/api/sse.py`) is a single-subscriber, bounded-history buffer with replay semantics. `put` appends + signals; `subscribe` replays history then awaits live events until a terminal event (`run_finished` or `run_failed`) closes the buffer. The `_total_put` counter lets a late subscriber know how many events scrolled out of history.
- `POST /api/ask` spawns `asyncio.create_task(run_question(...))`, registers the buffer keyed by `question_id`, and returns immediately. The run continues asynchronously.
- `GET /api/stream?question_id=X` subscribes and emits SSE frames. **Important:** `app.py`'s generator yields `{"data": ev.model_dump_json()}` **dicts** to `EventSourceResponse`, not strings from `format_sse`. Yielding `format_sse(ev)` would double-wrap the `data: ` prefix. `format_sse` is only used by `test_sse.py` for the raw-frame unit test.
- `_runs` and `_tasks` are in-process dicts with no eviction. Fine for a demo; a real deployment would need cleanup.

### Frontend state (Zustand)

`web/src/state/runStore.ts` is a single store with a reducer (`apply`) that switches on `ev.type`. Key progressions:

- **KG node state:** `default` → `current` (active visit) → `visited` (prior visit) → `cited` (promoted on `run_finished`). Stored in a `Map<string, NodeState>`.
- **Edge state:** `default` → `traversed`. Stored in a `Map<string, EdgeState>` keyed by `${from}::${to}`.
- **Thinking:** `thinkingByAgent[agent]` accumulates `agent_thinking` deltas per-agent (not globally), so TracePanel can show each agent's stream in its own section.
- **Answer:** `answerText` is the concatenation of `answer_delta` tokens (shown while streaming); `finalAnswer` is the validated `StructuredAnswer` set on `run_finished` (switches AnswerPanel to the structured view).

### Closed-set citation grounding (deferred to M4)

The synthesizer will use **per-request `Literal[...]` enums** over retrieved IDs to force Claude to cite only from the candidate set (schema-time constraint), followed by **post-hoc resolution** that confirms every ID + quote survives in the knowledge base, with **regenerate-once-then-hard-fail** on mismatch. Three-layer defense; no silent fallback. Detailed in spec §15.

### What's fake vs. real in M0

| Component | M0 | Becomes real in |
|---|---|---|
| `decomposer` | Yields canned thinking + fixed DecomposerOut | M4 (Haiku) |
| `statute_retriever` | Walks hardcoded `FAKE_VISIT_PATH` through `FAKE_KG` | M2 (Sonnet tool-use loop) |
| `case_retriever` | Emits `FAKE_CASES` one by one | M3 (bge-m3 + LanceDB + Haiku rerank) |
| `synthesizer` | Streams `FAKE_ANSWER` token-by-token | M4 (Sonnet + closed-set grounding) |
| `validator_stub` | Always returns `valid=True` | Intentionally stubbed — real validator is v2 scope |
| `/api/kg` | Real — loads `data/kg/huurrecht.json` at startup (built by `jurist.ingest.statutes`) | — |

The validator is the **only** intentional stub. Everything else is a fake that emits realistic event streams so the frontend animation and SSE plumbing can be exercised end-to-end without LLMs or data sources.

## Conventions worth knowing

- **TDD with frequent commits.** Each task in the plans follows: failing test → see fail → implement → tests pass → commit. One task ≈ one commit. Follow this cadence when continuing milestones.
- **No framework agents.** Explicit non-goal: no LangChain, LangGraph, CrewAI, AutoGen. Agents are plain Python async generators with Pydantic I/O. The Anthropic SDK is used directly.
- **Single remote vendor.** Only Anthropic is called remotely. Embeddings (bge-m3) run locally via sentence-transformers.
- **Design-first.** For any change that affects the architecture, event protocol, or milestone scope, update the design spec (`docs/superpowers/specs/...`) before changing code. The plans (`docs/superpowers/plans/...`) then derive from the spec.
