# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Jurist is a portfolio multi-agent demo answering Dutch **huurrecht** (tenancy law) questions with grounded citations. Locked demo question: *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*. Built as interview prep for an AI-engineer role at DAS (Dutch legal insurance). The scope is deliberately small — one rechtsgebied, 218 KG nodes, ~few hundred cases (post-fence filter), four live agents + one stubbed validator.

**Authoritative design:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`. Read this before making substantive design decisions. Milestone plans live in `docs/superpowers/plans/YYYY-MM-DD-*.md`.

Current state: **M3b landed on master** — the `case_retriever` agent runs a real pipeline: embed sub-questions with bge-m3, retrieve top-150 LanceDB chunks, dedupe to 20 unique ECLIs, Haiku-rerank to 3 `CitedCase`s with Dutch reason strings. Closed-set grounding via JSON-Schema `enum` on ECLI; one regen then `run_failed{reason:"case_rerank"}` on malformed output. API startup adds an Embedder cold-load (~5-10s, one-time per process) and a fail-fast gate on `data/lancedb/cases.lance`. Decomposer and synthesizer remain M0 fakes (→ M4); validator is a permanent stub.

## Commands

### Backend (Python 3.11, `uv`)

- Install deps: `uv sync --extra dev`
- Build KG (prerequisite for API start): `uv run python -m jurist.ingest --refresh -v` (dispatches via `src/jurist/ingest/__main__.py`).
- Build caselaw index: `uv run python -m jurist.ingest.caselaw -v` (one-time ~20–40 min; downloads ~2.3 GB bge-m3 on first run; uses `data/cases/` disk cache + `data/lancedb/cases.lance`).
- Run full test suite: `uv run pytest -v` (~75s due to `asyncio.sleep` in fake agents)
- Run a single test: `uv run pytest tests/api/test_orchestrator.py::test_orchestrator_runs_agents_in_expected_order -v`
- Lint: `uv run ruff check .`
- Start API server: `uv run python -m jurist.api` — listens on `http://127.0.0.1:8766` with hot-reload. API hard-fails at startup if `data/kg/huurrecht.json` OR `data/lancedb/cases.lance` is missing/empty — run both ingest steps first on a fresh clone. First boot additionally cold-loads bge-m3 (~5-10s; ~1.1 GB RAM resident). `ANTHROPIC_API_KEY` is not required at startup (the SDK defers the auth check), but the statute retriever and case rerank will 401 on first call without it; see `.env.example`.

### Frontend (Node 20+, from `web/`)

- Install deps: `cd web && npm install`
- Typecheck: `cd web && npx tsc --noEmit`
- Start dev server: `cd web && npm run dev` — Vite on `http://localhost:5173`, proxies `/api/*` → `127.0.0.1:8766`
- Production build: `cd web && npm run build`

### Environment quirks

- `uv` lives at `C:\Users\totti\.local\bin` and isn't always on `PATH`. Prepend it in bash with `export PATH="/c/Users/totti/.local/bin:$PATH"` if `uv` is not found.
- Git's LF→CRLF warnings on Windows commits are benign; don't try to suppress them.
- API port is **8766**, not 8000 (Django project on this host) and not 8765 (previous zombie-socket incident). If you change the backend port, also change the Vite proxy target in `web/vite.config.ts`.
- Full run emits ~200+ events post-M3b (most are `answer_delta` tokens from the synthesizer's word-level streaming; M2 adds a variable count of `tool_call_started` / `tool_call_completed` / `node_visited` / `edge_traversed` / `agent_thinking` events depending on how many tools the statute retriever calls; M3b adds `search_started` + one `case_found` per unique ECLI (up to `caselaw_candidate_eclis`, default 20) + `reranked`). `EventBuffer.max_history` defaults to 500; `settings.max_history_per_run` matches. If you shrink these, verify the orchestrator tests still pass.
- Env vars: copy `.env.example` → `.env` and set `ANTHROPIC_API_KEY`. All other settings have sensible defaults. `python-dotenv` loads `.env` at `jurist.config` import time.

## Architecture

### Agent contract (spec §5)

Every agent — real or fake — is an async generator with this shape:

```python
async def run(input: AgentIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    # ... domain events (thinking, tool calls, node_visited, answer_delta, etc.)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

The **final** yielded event is always `agent_finished` with the typed Pydantic output serialized into `.data`. Orchestrator downstream re-validates via `AgentOut.model_validate(final.data)`. Agents yield events **unstamped** — `agent`, `run_id`, and `ts` fields are filled in by `_pump` in the orchestrator, not by the agent. Real agents that need external resources add a keyword-only `ctx: RunContext` parameter (see `statute_retriever.run(input, *, ctx)`); fakes keep the single-input signature.

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

All 5 run on one asyncio task. Parallelization is explicitly out of scope for v1 (spec §15 decision log). The orchestrator wraps the `statute_retriever` and `case_retriever` pumps in try/except: statute errors and generic case-retriever errors surface as `run_failed{reason: "llm_error", detail}`; `RerankFailedError` from the case retriever surfaces as `run_failed{reason: "case_rerank", detail}`. Fakes are assumed not to fail (spec §5).

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

### Statute retriever (M2)

- **Loop driver:** `src/jurist/llm/client.py::run_tool_loop` — async generator yielding a `LoopEvent` ADT (`TextDelta` / `ToolUseStart` / `ToolResultEvent` / `Done` / `Coerced`). Supports a scripted `MockAnthropicClient` for tests and real `AsyncAnthropic.messages.stream()` for prod, picked via duck-typing. Five coercion paths: `max_iter` (15), `wall_clock` (90s), `dup_loop` (3 consecutive identical calls), `done_error` (done with unknown ids twice), `stall` (empty turn). Coerced selections are visit-recency-ordered and capped at 8.
- **Tool surface:** `src/jurist/agents/statute_retriever_tools.py::ToolExecutor` implements 5 tools (`search_articles`, `list_neighbors`, `get_article`, `follow_cross_ref`, `done`). `tool_definitions()` exposes the Anthropic JSON-schema array; `build_catalog(kg)` renders the full corpus as the system-prompt preamble (~63KB, cached at one `ephemeral` breakpoint).
- **Agent translation:** `src/jurist/agents/statute_retriever.py::run` maps each `LoopEvent` to `TraceEvent`s; on coercion it also emits synthetic `tool_call_started`/`tool_call_completed` for "done" so the UI sees a consistent terminator. `_is_mock(ctx.llm)` (checks `next_turn` without `messages`) routes test vs prod.
- **Tests:** 113 unit tests use `MockAnthropicClient` — no network. 1 RUN_E2E-gated integration test (`tests/integration/test_m2_statute_retriever_e2e.py`) asserts art. 7:248 BW is cited on the locked question; run with `RUN_E2E=1 uv run pytest tests/integration/...`.

### Caselaw ingestion (M3a)

- **Pipeline:** `src/jurist/ingest/caselaw.py::run_ingest` — nine stages (warm model → list → resume → fetch → parse → filter → chunk → embed → write). Sync + `ThreadPoolExecutor(max_workers=5)` for the fetch stage.
- **Data source:** `data.rechtspraak.nl/uitspraken/zoeken` filtered on `subject=civielRecht_verbintenissenrecht` + `modified>=2024-01-01`, then a local keyword fence (`huur`/`verhuur`/`woonruimte`/`huurcommissie`). Parent spec §8.2's original `rechtsgebied=Huurrecht` filter was wrong — no such URI exists in the taxonomy.
- **Embedder:** `src/jurist/embedding.py::Embedder` wraps `sentence-transformers` `BAAI/bge-m3` (1024-d, L2-normalized). Shared with M3b.
- **Storage:** `src/jurist/vectorstore.py::CaseStore` concrete LanceDB class (no interface — parent spec §15 decision #12). Deduplicates on `(ecli, chunk_idx)`.
- **Profiles:** `src/jurist/ingest/caselaw_profiles.py` — `{rechtsgebied_name → (subject_uri, keyword_terms)}`. Only `huurrecht` populated; multi-rechtsgebied is a dict-entry diff.
- **Consumed by:** M3b `case_retriever` via `Embedder` + `CaseStore.query()` + Haiku rerank. See "Case retriever (M3b)" below.

### Case retriever (M3b)

- **Pipeline:** `src/jurist/agents/case_retriever.py::run` — 5 stages (embed → LanceDB top-K → ECLI dedupe → Haiku rerank → assemble `CitedCase`s). Pure helper `src/jurist/agents/case_retriever_tools.py` owns stages 1-3 + JSON-Schema tool + Dutch prompt builders; the agent module owns events + the Haiku call + regen/hard-fail.
- **Over-fetch ratio:** top-150 chunks → group-by-ECLI → cap 20 unique (tunable via `JURIST_CASELAW_CANDIDATE_CHUNKS` / `JURIST_CASELAW_CANDIDATE_ECLIS`). Sized against M3a's ~7.8 chunks/case average; top-20 chunks literally would collapse to ~2-3 unique ECLIs post-dedupe.
- **Closed-set grounding:** per-request JSON-Schema `enum` on `ecli` in the `select_cases` tool definition — mirror of the synthesizer's per-request `Literal[...]` at the retrieval boundary (parent spec §15 decision #17). Agent-side `_validate_picks` is the belt-and-suspenders check.
- **Error handling:** `InvalidRerankOutput` on malformed tool output → regen once with a Dutch error note appended. Second failure → `RerankFailedError` → orchestrator emits `run_failed{reason:"case_rerank"}`. `<3` candidates → same hard-fail (index underpopulated or query wildly off-topic).
- **Cost/latency:** one Haiku call per run (two on regen). System prompt + candidate list cached at one `cache_control: ephemeral` breakpoint. ~200-500ms typical; ~1-2s worst case.
- **Tests:** 10 pure-helper tests + 2 happy-path agent tests + 7 error-path agent tests + 2 lifespan gate tests + 2 orchestrator integration tests. 1 RUN_E2E-gated e2e test (`tests/integration/test_m3b_case_retriever_e2e.py`) asserts 3 valid `CitedCase`s for the locked question.

### Closed-set citation grounding (deferred to M4)

The synthesizer will use **per-request `Literal[...]` enums** over retrieved IDs to force Claude to cite only from the candidate set (schema-time constraint), followed by **post-hoc resolution** that confirms every ID + quote survives in the knowledge base, with **regenerate-once-then-hard-fail** on mismatch. Three-layer defense; no silent fallback. Detailed in spec §15.

### What's fake vs. real after M3b

| Component | State | Becomes real in |
|---|---|---|
| `decomposer` | M0 fake — yields canned thinking + fixed DecomposerOut | M4 (Haiku) |
| `statute_retriever` | **Real** — Claude Sonnet tool-use loop over the 218-node KG (5 tools) | — |
| `case_retriever` | **Real** — bge-m3 + LanceDB top-150→20 ECLIs + Haiku rerank to 3 | — |
| `synthesizer` | M0 fake — streams `FAKE_ANSWER` token-by-token | M4 (Sonnet + closed-set grounding) |
| `validator_stub` | Permanent stub — always returns `valid=True` | — (real validator is v2 scope) |
| `/api/kg` | Real — loads `data/kg/huurrecht.json` at startup (built by `jurist.ingest.statutes`) | — |

The validator is the only intentional stub; the two remaining fakes (`decomposer`, `synthesizer`) still emit realistic event streams so the frontend can be exercised end-to-end without the live LLM/vector-store dependencies they'll gain in M4.

## Conventions worth knowing

- **TDD with frequent commits.** Each task in the plans follows: failing test → see fail → implement → tests pass → commit. One task ≈ one commit. Follow this cadence when continuing milestones.
- **No framework agents.** Explicit non-goal: no LangChain, LangGraph, CrewAI, AutoGen. Agents are plain Python async generators with Pydantic I/O. The Anthropic SDK is used directly.
- **Single remote vendor.** Only Anthropic is called remotely. Embeddings (bge-m3) run locally via sentence-transformers.
- **Design-first.** For any change that affects the architecture, event protocol, or milestone scope, update the design spec (`docs/superpowers/specs/...`) before changing code. The plans (`docs/superpowers/plans/...`) then derive from the spec.
