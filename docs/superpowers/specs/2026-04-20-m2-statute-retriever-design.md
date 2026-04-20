# M2 — Real Statute Retriever — Design

**Date:** 2026-04-20
**Status:** Approved. Implementation not yet started.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§5.2, §11 M2)
**Branch:** `m2-statute-retriever`

---

## 1. Context and goals

Replace the M0 fake `statute_retriever` with a real Claude Sonnet 4.6 tool-use loop that navigates the M1 huurrecht KG (218 articles, 283 edges from BW7 Titel 4 + Uhw) and returns the cited articles relevant to the user's question.

**M2 is done when** — per parent spec §11 and the acceptance criteria in §14 below — the retriever runs a real LLM loop, terminates via `done` (not coerced) on the locked demo question, `cited_articles` includes `art. 7:248 BW`, the KG animation reflects a non-trivial walk (≥3 nodes visited), and tool/guardrail unit tests pass.

**In scope.** The `statute_retriever` agent, its tool implementations, a thin Anthropic LLM client wrapper, the system prompt template, guardrails (iteration/wall-clock caps, duplicate-call detector), and the test suite covering them.

**Out of scope.** Decomposer, case retriever, synthesizer, validator — all remain fakes/stub. No vector search for statutes (in-prompt catalog handles global view). No Anthropic retry/backoff. No multi-request batching. No concurrency (single demo user).

## 2. Architecture

### 2.1 File changes

**Added:**
- `src/jurist/agents/statute_retriever_tools.py` — tool implementations over a `KnowledgeGraph`.
- `src/jurist/llm/__init__.py` + `client.py` — thin Anthropic wrapper; exposes `run_tool_loop`.
- `src/jurist/llm/prompts/statute_retriever.system.md` — system prompt template with `{{ARTICLE_CATALOG}}` slot.

**Modified:**
- `src/jurist/agents/statute_retriever.py` — replaces M0 fake; consumes `RunContext`.
- `src/jurist/api/orchestrator.py` — builds and threads `RunContext(kg, llm)` through agent calls.
- `src/jurist/api/app.py` — FastAPI lifespan instantiates `AsyncAnthropic` client → `app.state.anthropic`.
- `src/jurist/config.py` — adds `RunContext` dataclass and M2 tunables.

**Unchanged:** `decomposer`, `case_retriever`, `synthesizer`, `validator_stub`, `api/sse.py`, frontend. The event protocol is preserved exactly; the reducer in `runStore.ts` needs no changes.

### 2.2 Agent contract

`run(input)` shape is preserved for fakes. The real statute retriever adds a keyword argument for injected state:

```python
# src/jurist/agents/statute_retriever.py
async def run(
    input: StatuteRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    ...
```

The orchestrator's `_pump` function doesn't inspect agent signatures — it just consumes the yielded stream — so the asymmetry is local to the call site. Only agents that need external state (KG, LLM client, later: vector store) take a `ctx`. This avoids premature abstraction over the other fake agents.

### 2.3 RunContext

```python
# src/jurist/config.py
@dataclass
class RunContext:
    kg: KnowledgeGraph
    llm: AnthropicClient   # thin wrapper from src/jurist/llm/client.py
```

FastAPI lifespan builds the KG (M1) and the Anthropic client once, stores them in `app.state`, and the endpoint handler passes them into `run_question` as a `RunContext`. Future milestones add fields (e.g., `vector_store` for case retriever).

### 2.4 Per-run data flow

```
POST /api/ask
  → orchestrator.run_question(q, run_id, buffer, ctx=RunContext(kg, llm))
    → decomposer.run(dec_in)                              # fake, unchanged
    → statute_retriever.run(stat_in, ctx=ctx):
        1. Build catalog from ctx.kg.all_nodes() →
           [{id, label, title, body_text[:200]}] × 218
        2. Load system prompt template, substitute {{ARTICLE_CATALOG}}
        3. Build user message from sub_questions + concepts + intent
        4. Bind tool executor to ctx.kg
        5. ctx.llm.run_tool_loop(system, tools, user, max_iters, cap_s)
           For each loop step:
             - text delta          → yield agent_thinking
             - tool_use(name, args) → yield tool_call_started
                                      execute via executor
                                      yield tool_call_completed
                                      yield node_visited / edge_traversed (§4)
                                      inject tool_result for next turn
             - done | coerced       → build StatuteRetrieverOut
        6. yield agent_finished(out.model_dump())
    → case_retriever.run(case_in)                         # fake, unchanged
    → synthesizer.run(synth_in)                           # fake, unchanged
    → validator_stub.run(val_in)                          # stub, unchanged
  → run_finished
```

## 3. Tool surface

Five tools exposed to Claude (`list_neighbors` added beyond parent spec §5.2; motivated by token-savings and context hygiene during exploration).

| Tool | Input | Returns | Error cases |
|------|-------|---------|-------------|
| `search_articles` | `query: str`, `top_k: int = 5` (max 10) | `[{article_id, label, title, snippet}]` | — |
| `list_neighbors` | `article_id: str` | `[{article_id, label, title}]` — one per outgoing_ref | unknown id → `is_error` |
| `get_article` | `article_id: str` | `{article_id, label, title, body_text, outgoing_refs: list[str]}` | unknown id → `is_error` |
| `follow_cross_ref` | `from_id: str`, `to_id: str` | same shape as `get_article(to_id)` | unknown id OR edge (from,to) not in KG → `is_error` with hint: "use `get_article(to_id)` if you only need the content" |
| `done` | `selected: [{article_id, reason}]` | (terminates loop) | any unknown `article_id` → `is_error`, one regeneration allowed, then coerce |

**`done.selected` shape note.** Each entry is `{article_id, reason}` — the `reason` field maps directly to `CitedArticle.reason` in the agent output. Per-article justification beats one global reasoning string because the answer panel renders it inline.

**`search_articles` implementation.** Lexical only in M2 (token-overlap scoring over `title + body_text[:200]`). No embeddings for statutes; the in-prompt catalog already provides a global view, so search is a fallback, not primary. Revisit if quality disappoints.

**`list_neighbors` returns labels/titles only, no body** — a cheap "survey before load" operation that lets the model prune irrelevant neighbors without consuming bodies into context.

**Body passthrough.** `get_article` returns the raw `body_text` verbatim — no annotation, no sanitization of dangling prose refs. The ingester has already filtered `outgoing_refs` to in-corpus IDs only, so `outgoing_refs` is the model's reliable "you CAN follow these" signal. Attempts to `follow_cross_ref` / `get_article` an out-of-corpus ID return `is_error`.

## 4. Event translation

The `llm.client.run_tool_loop` helper yields internal `LoopEvent`s; the retriever agent translates them to `TraceEvent`s:

| LoopEvent | TraceEvent(s) emitted |
|-----------|----------------------|
| `TextDelta(text)` | `agent_thinking{text}` |
| `ToolUseStart(name, args)` | `tool_call_started{tool, args}` |
| `ToolResult(name, args, result_summary, is_error, extra)` | `tool_call_completed{tool, args, result_summary, is_error, **extra}` + per-tool node/edge events (below) |
| `Done(selected)` | (terminates; caller returns `StatuteRetrieverOut`) |
| `Coerced(reason, selected)` | synthetic `tool_call_started{tool: "done", args: {coerced: true, reason}}` → `tool_call_completed` |

Per-tool node/edge events:

| Tool | Extra events after `tool_call_completed` |
|------|------------------------------------------|
| `search_articles` | none (peek operation; hit IDs travel in `tool_call_completed.data.hit_ids` for frontend chips) |
| `list_neighbors` | none (peek; neighbor IDs in `tool_call_completed.data.neighbor_ids`) |
| `get_article` | `node_visited{article_id}` |
| `follow_cross_ref` | `node_visited{to_id}` then `edge_traversed{from_id, to_id}` (matches M0 fake order; frontend reducer is coded against it) |
| `done` | none |

**Principle.** `node_visited` = "body was read". `search_articles` and `list_neighbors` are peek operations — they surface IDs via `tool_call_completed.data` without lighting nodes. Cited status is promoted on `run_finished` by the frontend store (already wired).

**`result_summary` format.** Stays a human-readable string (e.g., `"5 hits"`, `"Boek 7, Artikel 248 — Huurprijzen"`). Additive structured fields (`hit_ids`, `neighbor_ids`, `is_error`) live alongside in `tool_call_completed.data` — unchanged frontends keep working; new frontends can render chips.

**Revisit behavior.** Model calls `get_article(X)` for an already-visited X: re-emit `node_visited` (legitimate re-focus). Consecutive duplicates are caught by the duplicate-call detector (§5).

## 5. Guardrails

| Control | Rule |
|---------|------|
| Iteration definition | One assistant turn = one iteration. Parallel `tool_use` blocks in a single turn count as 1 (Anthropic semantics). |
| Iteration cap | **15** (configurable via `JURIST_MAX_RETRIEVER_ITERS`). |
| Token budget | No explicit cap. Cached catalog (~18k tokens) + growing conversation stays well under 200k across 15 turns. |
| Wall-clock cap | **90 s** (configurable via `JURIST_RETRIEVER_WALL_CLOCK_CAP_S`). Orchestrator coerces `done` on timeout. Safety net — iteration cap should fire first in practice. |
| Dup detector | Same tool + identical `args` two consecutive calls → inject `tool_result{is_error: true, message}` advisory instead of executing. Three consecutive dupes → coerce `done`. |
| Coerced-done emit | Synthetic `tool_call_started{tool: "done", args: {coerced: true, reason: "max_iter" \| "wall_clock" \| "dup_loop"}}` + `tool_call_completed`. Trace + UI show consistent termination. |
| Coerced selection | All nodes touched by `get_article` or `follow_cross_ref`, visit-recency ordered, capped at **8**. `reason = "auto-selected (coerced: <cause>)"`. Articles surfaced only by `search_articles` are excluded. |
| Empty `cited_articles` | Allowed. Model can `done(selected=[])`. Log a warning; synthesizer handles downstream. |
| Tool executor exceptions | `run_tool_loop` wraps in `try/except`; converts to `tool_result{is_error: true, message: "internal error"}`. Loop continues. |
| Anthropic 429/5xx | No retry in M2. Orchestrator emits `run_failed{reason: "llm_error", detail}`. User re-asks. |
| Unknown `article_id` in `done` | `is_error` with regeneration hint. One retry allowed, then coerce. |

## 6. System prompt & catalog

Template at `src/jurist/llm/prompts/statute_retriever.system.md`, rendered once per run by substituting `{{ARTICLE_CATALOG}}`:

```markdown
You are a Dutch tenancy-law (huurrecht) statute researcher. Your job is to
identify which articles from the huurrecht corpus are most relevant to the
user's question, then call `done` with your selections.

## Your corpus
The catalog below lists every article you can access. You do NOT need to
search first — pick candidates directly from the catalog, then load their
bodies with `get_article`, follow cross-references with `follow_cross_ref`,
or peek at connected articles with `list_neighbors`.

## Tools
- search_articles(query, top_k=5): lexical search. Use if the catalog
  doesn't show obvious candidates.
- list_neighbors(article_id): labels/titles of cross-referenced articles.
  Cheap — use to survey before loading bodies.
- get_article(article_id): full article body + outgoing_refs.
- follow_cross_ref(from_id, to_id): same as get_article(to_id), plus
  records the traversal. Edge must exist in corpus.
- done(selected): terminate. selected = [{article_id, reason}, ...].

## Policies
- Reason in Dutch when considering article content.
- Cite only articles whose content directly bears on the question.
- Target 3–6 cited articles.
- You have 15 iterations. Call done as soon as you have enough evidence.

## Article catalog
{{ARTICLE_CATALOG}}
```

**Catalog format** — one article per line:

```
[<article_id>] "<label>" — <title>: <snippet>
```

where `<snippet>` is `body_text[:200]` with whitespace collapsed, truncated at last word boundary, trailing `"…"` if truncated.

**Helper:**

```python
def make_snippet(body: str, max_chars: int = 200) -> str:
    compact = " ".join(body.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "…"
```

**Expected catalog size.** ~66 KB text (~18k tokens) for all 218 articles. Fits comfortably under prompt-cache limits.

**Prompt cache breakpoint.** One breakpoint at the end of the system message. System prompt (role + policies + tool descriptions + filled catalog) is identical across runs → cached once, near-free thereafter. No breakpoints in the growing conversation history (modest savings not worth the fragility at this milestone).

**Language.** Prompt structure in English for maintainer clarity. Catalog rows are Dutch verbatim. Model reasons in Dutch naturally when given Dutch content.

## 7. LLM client

`src/jurist/llm/client.py` — thin Anthropic wrapper, minimal for M2 needs. One public entry point:

```python
async def run_tool_loop(
    *,
    client: AsyncAnthropic,
    model: str,
    system: str,
    tools: list[ToolDef],
    tool_executor: Callable[[str, dict], Awaitable[ToolResult]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    ...
```

**Model parameters:**
- `model = "claude-sonnet-4-6"` (parent spec §4).
- `temperature = 0` for reproducibility during demos.
- `max_tokens = 4096` per turn.
- No extended thinking in M2 (adds latency we can't afford for live demo; revisit if tool-use quality disappoints).

**Streaming.** Uses `client.messages.stream()` context manager. Text-block deltas → `TextDelta`. Tool_use blocks → assembled → `ToolUseStart` → executor → `ToolResult` injected into next turn.

**Lifecycle.** Single `AsyncAnthropic` instance created in FastAPI lifespan (`app.state.anthropic`), reused across runs. SDK is safe for concurrent use.

**Scope discipline.** No retries, no structured-output variant, no per-request `Literal` builders. Those belong to M4 (decomposer + synthesizer) and can be added to this module or stand alone — decide then.

## 8. Testing

Three layers.

### 8.1 Unit

**`tests/agents/test_statute_retriever_tools.py`**
- `search_articles`: returns top-K sorted by score; handles empty query / empty corpus.
- `list_neighbors`: correct neighbors; unknown id → error.
- `get_article`: full body + outgoing_refs; unknown id → error.
- `follow_cross_ref`: valid edge returns body; dangling edge + unknown id → errors with correct messages.

All against a small hand-crafted fixture KG, not the real huurrecht KG.

**`tests/llm/test_client.py`**
- `run_tool_loop` terminates on `done`.
- Coerces on `max_iter`; selected = visit-recency-ordered, capped at 8.
- Coerces on wall-clock cap.
- Dup detector: 2 consecutive dupes → advisory `tool_result{is_error: true}`; 3 → coerce.
- Tool executor exception → `is_error` tool_result, loop continues.

Uses a scripted `MockAnthropicClient` (see §8.4) — no real API calls.

**`tests/agents/test_statute_retriever.py`**
- Mocks LLM via scripted turn sequence + real fixture KG.
- Asserts event order: `agent_started → ... → agent_finished`.
- Asserts tool events correctly wrapped by `node_visited` / `edge_traversed` per §4.
- Asserts tool errors surface as `tool_call_completed` with `is_error=true` preserved.

**`tests/agents/test_statute_retriever_prompt.py`**
- Snapshot test: renders system prompt against a tiny fixture KG, compares to frozen expected output. Catches accidental policy/catalog drift.

### 8.2 Orchestrator

**`tests/api/test_orchestrator.py` (updates)**
- New `RunContext(kg, llm)` signature; passes a `MockAnthropicClient`.
- Existing `test_orchestrator_emits_run_started_and_run_finished` tightens event-shape assertions (types present, ordering) rather than specific counts, because M2 changes the retriever's event volume.

### 8.3 Integration

**`tests/integration/test_m2_statute_retriever_e2e.py`**
- Gated on `RUN_E2E=1` (real Anthropic calls cost tokens).
- Runs the full retriever against the real M1 KG with the canned decomposer fixture.
- Asserts:
  - Terminates via `done` (not coerced).
  - `cited_articles` includes the `art. 7:248 BW` article_id.
  - Visit path (from event log) ≥ 3 nodes.
  - Zero `is_error` events in the log.

### 8.4 Mock LLM fixture

`tests/fixtures/mock_llm.py`:

```python
@dataclass
class ScriptedToolUse:
    name: str
    args: dict[str, Any]

@dataclass
class ScriptedTurn:
    text_deltas: list[str] = field(default_factory=list)
    tool_uses: list[ScriptedToolUse] = field(default_factory=list)

class MockAnthropicClient:
    def __init__(self, script: list[ScriptedTurn]) -> None: ...
    # matches the real client's run_tool_loop signature
```

## 9. Observability

Stdlib `logging` in the retriever — no new dependencies:
- **INFO** at loop start (catalog size, iteration budget) and loop end (cited count, iterations used, wall-clock elapsed).
- **WARNING** on each coercion with reason (max_iter / wall_clock / dup_loop).
- **ERROR** on unexpected exceptions in tool executor or LLM call.

Output goes to stderr; uvicorn captures it.

## 10. Configuration

Environment variables (in `src/jurist/config.py`):

| Var | Default | Purpose |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | required | LLM auth (existing) |
| `JURIST_MODEL_RETRIEVER` | `claude-sonnet-4-6` | Override model |
| `JURIST_MAX_RETRIEVER_ITERS` | `15` | Iteration cap |
| `JURIST_RETRIEVER_WALL_CLOCK_CAP_S` | `90` | Wall-clock cap (seconds) |
| `JURIST_STATUTE_CATALOG_SNIPPET_CHARS` | `200` | `body_text` snippet size in catalog |

## 11. Dependencies

- **anthropic** — Python SDK, already listed in parent spec §4 as required.

No other new dependencies. `sentence-transformers` stays out of M2 (arrives with M3 case ingestion).

## 12. Open items

- **`search_articles` lexical scoring.** M2 implements Jaccard-like token-overlap scoring against `title + body_text[:200]` (case-folded, Dutch stop-words removed). BM25 is an explicit future-work item, not an M2 alternative — revisit only if Jaccard baseline quality disappoints in real runs.
- **Catalog ordering within the prompt.** Proposal: sort by `article_id` lexically (stable, predictable). Model can re-order internally.
- **Extended thinking re-evaluation.** If tool-use navigation is noisy, enabling extended thinking (Sonnet 4.6 supports it) could improve plan quality at a latency cost. Not in scope for initial M2 implementation; revisit after first real-run observations.

## 13. Out of scope (deferred)

- Real decomposer (parent §5.1, M4).
- Case retriever (parent §5.3, M3).
- Synthesizer + closed-set grounding (parent §5.4, M4).
- Vector search for statutes.
- Anthropic retry/backoff.
- Actively prompting for parallel tool use. If Claude spontaneously emits multiple `tool_use` blocks in one turn, the loop executes them and counts the turn as one iteration (§5); we just don't ask for it in the system prompt.
- Cross-breakpoint conversation-history caching.

## 14. Acceptance criteria

M2 is done when:

1. Real Claude Sonnet tool-use loop replaces the M0 fake in `src/jurist/agents/statute_retriever.py`.
2. The locked-question integration test (gated on `RUN_E2E=1`) passes: terminates via `done` (not coerced), `cited_articles` includes BW 7:248, visit path ≥ 3 nodes, zero `is_error` events.
3. All unit tests pass: tools, client (including guardrails), retriever event shape, prompt snapshot.
4. Orchestrator test updated to pass `RunContext`; event-shape assertions pass with new retriever event volume.
5. `uv run ruff check .` clean.
6. Fresh-clone smoke: `uv sync` → `uv run python -m jurist.ingest.statutes` → `python -m jurist.api` → `npm run dev` → ask the locked question → real KG-walk animation visible, real articles cited in the answer panel.

## 15. Decisions log (M2-specific)

| # | Decision | Alternatives considered | Reason |
|---|----------|------------------------|--------|
| 1 | Five tools (adds `list_neighbors` to parent spec §5.2's four) | Spec as-written (4 tools); unified `get_article(id, from_id?)` (3 tools) | Peek-before-load avoids pulling heavy bodies into context purely to survey cross-refs; meaningful token hygiene + cleaner reasoning. |
| 2 | Catalog `{id, label, title, body_text[:200]}` in system prompt, cached | `{id, label, title}` only; hand-authored summaries (M1.5 prerequisite) | Title alone is too weak (many articles share section headers like "Huurprijzen"); body-snippet gives real signal; cache makes 18k-token prefix effectively free after call 1. |
| 3 | No concept-driven hard-prune of catalog | Prune non-matching rows before sending; seed-hints in user message | Hard-prune breaks prompt caching (per-run variable); lexical concept-match has silent false negatives (e.g., "huurverhoging" ≠ "verhoogd"); keeps the narrative "LLM reasons over the full corpus." |
| 4 | `search_articles` is lexical-only in M2 | Hybrid lexical + bge-m3 vectors (parent spec) | Catalog in prompt already gives global view; search is a fallback; embeddings pull sentence-transformers in a milestone early. Revisit if quality disappoints. |
| 5 | `node_visited` only on `get_article` / `follow_cross_ref` | Also on `search_articles` hits | Keeps "visit" = "body was read"; peek operations surface IDs via `tool_call_completed.data` without exploding the node state machine. |
| 6 | `follow_cross_ref` validates edge exists; unknown edges → `is_error` | Silent fallback to `get_article(to)` | Preserves semantic integrity; model self-corrects via the error message. |
| 7 | Wall-clock cap 90 s in addition to 15-iter cap | Iteration cap only | Safety net for the live demo; iter cap should fire first in practice but wall-clock protects if the model hangs on a slow turn. |
| 8 | Dup detector: 2 consecutive → advisory, 3 → coerce done | Immediate coerce on first duplicate; no detector | Gives the model one chance to recover; hard coerce on second dup would kill useful retries (e.g., model re-reads after tool error). |
| 9 | Body text served verbatim; no annotation of dangling prose refs | Annotate with `[↪ in KG]` / `[⚠ external]` markers | Annotation logic is a drift risk; `outgoing_refs` already filters to in-corpus IDs → model has a reliable signal via the structured field. Body stays faithful to source. |
| 10 | `RunContext(kg, llm)` threaded through orchestrator | Module-level singletons; agent-as-class | No test-time monkey-patching; future milestones add fields without widening `run_question` positional args. |
| 11 | Thin `llm/client.py` — `run_tool_loop` only | Full Anthropic wrapper (structured output, retries, etc.) | YAGNI; M4 agents can add what they need. |
| 12 | Temperature 0; no extended thinking | Non-zero temp for creative navigation; thinking for better planning | Reproducibility in live demo trumps creative navigation; thinking latency risk exceeds demo benefit at this milestone. |

---

*End of spec.*
