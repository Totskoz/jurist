# M3b — Case Retriever — Design

**Date:** 2026-04-21
**Status:** Approved. Implementation not yet started.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§5.3, §11 M3b)
**Sibling spec (ingest):** `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md`
**Branch:** `m3b-case-retriever`

---

## 1. Context and goals

M3a shipped the ingestion half of case-law — a populated LanceDB index at `data/lancedb/cases.lance` (~47k chunks across ~6k huur-relevant ECLIs, per the M3a post-mortem in `docs/discussions.md`). The `case_retriever` agent still emits `FAKE_CASES` from `src/jurist/fakes.py`.

**M3b replaces that fake with a real bge-m3 + Haiku-rerank retriever over the M3a index.** No frontend work; no orchestrator refactor; event protocol unchanged (the fake already emits the parent spec's §5.3 event set, so the frontend is compatible).

**Done when** (inherits parent §11 M3b + this spec's §15):

1. Parent-spec amendment commit landed on `master` (§12).
2. `case_retriever.run()` does real work: embed → LanceDB top-K → group-by-ECLI → Haiku rerank → emit `CaseRetrieverOut`.
3. On the locked question: 3 cases returned, every ECLI exists in LanceDB, every similarity ∈ (0, 1], every reason is a non-trivial Dutch string (≥20 chars).
4. Citation click opens `https://uitspraken.rechtspraak.nl/details?id=ECLI:...` in a new tab (spec acceptance criterion; already works — tested here).
5. Rerank hard-fails (one regen, then `run_failed { reason: "case_rerank" }`) on persistently malformed output — no silent fallback to cosine-only.
6. API refuses to start if `data/lancedb/cases.lance` is missing or empty — matches the KG fail-fast gate from M2.
7. Unit tests green across: pure retrieval helper, agent happy path, agent error paths, orchestrator integration, vectorstore (signature update).
8. `RUN_E2E=1 uv run pytest tests/integration/test_m3b_case_retriever_e2e.py` passes: real Embedder, real LanceDB, real Haiku, locked question.
9. `uv run ruff check .` clean.

**In scope.** New agent module + pure helper, rerank tool-schema + Dutch prompt, `RunContext` extensions for `case_store` + `embedder`, API lifespan gate, `CaseStore.query()` signature update (returns similarity), four new settings (§8), one `schemas.py` change (`question` field on `CaseRetrieverIn`), two internal dataclasses in the helper module (`CaseCandidate`, `RerankPick`), parent-spec amendment.

**Out of scope.** Decomposer (still M0 fake → M4). Synthesizer (still M0 fake → M4). Validator (permanent stub). Frontend. KG or caselaw re-ingestion. Evaluation harness. Cross-question corpus freshness. Pacht / adjacent-regime expansion.

## 2. Architecture

### 2.1 Pipeline (one `async def run()`, five stages)

```
CaseRetriever (M3b)
  1. Embed           embedder.encode(["\n".join(sub_questions)])           → (1, 1024) np.float32, L2-normalized
  2. Retrieve        case_store.query(vec, top_k=caselaw_candidate_chunks) → list[(CaseChunkRow, similarity)], desc-sorted
  3. Dedupe          group-by-ECLI, keep best chunk per ECLI, cap at N     → list[CaseCandidate] (≤caselaw_candidate_eclis)
  4. Rerank          Haiku messages.create, forced-tool, enum on ECLI      → list[RerankPick] (exactly 3)
                        ├─ invalid → one regen with advisory addendum
                        └─ still invalid → raise RerankFailedError
  5. Assemble        join picks with dedupe metadata (similarity, url, …)  → CaseRetrieverOut
```

Stages 1–3 are pure (sync, no Anthropic, no asyncio); stages 4–5 live in the async agent module.

### 2.2 File changes

**Added:**
- `src/jurist/agents/case_retriever_tools.py` — pure helper: `retrieve_candidates`, `build_rerank_tool_schema`, `build_rerank_user_message`, `CaseCandidate` dataclass, `RerankPick` dataclass, `InvalidRerankOutput` exception.
- `src/jurist/llm/prompts.py` — **+1 function** `render_case_rerank_system()`. (File exists; one function added.)
- `tests/agents/test_case_retriever_tools.py`, `tests/agents/test_case_retriever.py`, `tests/agents/test_case_retriever_errors.py`.
- `tests/integration/test_m3b_case_retriever_e2e.py` (RUN_E2E-gated).

**Modified:**
- `src/jurist/agents/case_retriever.py` — **rewritten** from the M0 fake. Async generator; events + rerank call + regen-or-hard-fail.
- `src/jurist/schemas.py` — add `question: str` field to `CaseRetrieverIn`.
- `src/jurist/vectorstore.py` — `CaseStore.query()` returns `list[tuple[CaseChunkRow, float]]` (was `list[CaseChunkRow]`). Similarity = `1 - _distance` for cosine metric.
- `src/jurist/config.py` — four new settings (§8); `RunContext` gains `case_store: CaseStore` and `embedder: Embedder`.
- `src/jurist/api/app.py` — lifespan opens `CaseStore`, verifies non-empty, loads `Embedder`, threads both into `RunContext`. Fail-fast gate on missing/empty index.
- `src/jurist/api/orchestrator.py` — case_retriever pump wrapped in try/except catching `RerankFailedError` → `run_failed{reason:"case_rerank"}` and generic `Exception` → `run_failed{reason:"llm_error"}`; mirrors the existing statute_retriever guard.
- `tests/fixtures/mock_llm.py` — add `MockMessagesClient` + `MockAnthropicForRerank` (alongside the existing streaming `MockAnthropicClient`).
- `tests/vectorstore/test_vectorstore.py` — update the one assertion that unpacks query results.
- `tests/api/test_orchestrator.py` — extend with two failure-path tests (case_rerank, llm_error via case_retriever).
- `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` — §5.3 step 2, §5.3 `CaseRetrieverIn`, §13 env vars, §15 decision log (§12 of this doc).
- `.env.example` — document the four new settings.

**Unchanged.** Decomposer, synthesizer, validator stub, statute retriever, KG, ingestion, frontend (KGPanel / TracePanel / AnswerPanel / CitationLink / runStore), fakes module (still imports `FAKE_CASES` for tests that want a synthetic corpus, though the agent no longer uses it).

### 2.3 Concurrency model

Entirely synchronous inside the agent's async body: no `asyncio.gather`, no threads. The only `await` points are stages 4 (Anthropic call) and event yields.

## 3. Retrieval helper — `src/jurist/agents/case_retriever_tools.py`

Pure, sync, unit-testable without Anthropic or asyncio.

### 3.1 Internal types

```python
@dataclass(frozen=True)
class CaseCandidate:
    """Pre-rerank candidate; handoff from helper → agent. Not persisted."""
    ecli: str
    court: str
    date: str
    snippet: str        # first N chars of best chunk, ellipsized at word boundary
    similarity: float   # cosine from best chunk (0..1]
    url: str

@dataclass(frozen=True)
class RerankPick:
    """Single row of the Haiku tool output (post-validation)."""
    ecli: str
    reason: str         # non-empty Dutch justification, ≥20 chars

class InvalidRerankOutput(Exception):
    """Raised when a single rerank attempt produces malformed output.
    Caught inside the agent; triggers a regen. If raised twice, the agent
    wraps it in RerankFailedError and propagates to the orchestrator."""
```

### 3.2 `retrieve_candidates`

```python
def retrieve_candidates(
    store: CaseStore,
    embedder: Embedder,
    query: str,
    *,
    chunks_top_k: int,
    eclis_limit: int,
    snippet_chars: int = 400,
) -> list[CaseCandidate]:
    """Embed → cosine top-K chunks → group-by-ECLI (first wins, since rows are
    sorted descending by similarity) → take up to eclis_limit unique ECLIs.

    Returns an empty list if the store yields no rows (e.g., empty corpus).
    Caller (agent) decides whether <3 candidates is fatal.
    """
```

**Implementation notes.**
- `store.query(vec, top_k=chunks_top_k)` returns `[(CaseChunkRow, similarity), …]` sorted by descending similarity (LanceDB invariant for cosine metric; verified in the M3a round-trip test).
- Grouping preserves insertion order (Python dict), so the first chunk seen per ECLI is the highest-similarity chunk — no extra sort needed.
- Snippet truncation: `row.text[:snippet_chars].rstrip()`, then append `"…"` if the original was longer. Word-boundary trim is not required — 400 chars is generous enough that mid-word truncation on the rare 399-char boundary is cosmetic.

### 3.3 `build_rerank_tool_schema`

Per-request JSON Schema for Haiku's forced tool call. The `enum` on `ecli` is the JSON-Schema form of the "per-request `Literal[...]`" closed-set pattern parent spec §15 decision #9 mandates for the synthesizer — same mechanism, one milestone earlier.

```python
def build_rerank_tool_schema(candidate_eclis: list[str]) -> dict:
    return {
        "name": "select_cases",
        "description": (
            "Selecteer exact 3 van de kandidaat-uitspraken die het meest "
            "relevant zijn voor de vraag en het wettelijk kader."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "picks": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ecli":   {"type": "string", "enum": candidate_eclis},
                            "reason": {"type": "string", "minLength": 20},
                        },
                        "required": ["ecli", "reason"],
                    },
                },
            },
            "required": ["picks"],
        },
    }
```

Invoked with `tool_choice={"type": "tool", "name": "select_cases"}` to force the model to call exactly this tool.

### 3.4 `build_rerank_user_message`

Dutch prompt. Concatenates the user's original question, sub-questions (Dutch bullet list), statute context (label + statute-retriever reason per article), and the numbered candidate list (ECLI | court | date | similarity | snippet).

```
Vraag: {question}

Sub-vragen:
- {sub_q_1}
- {sub_q_2}

Relevante wetsartikelen (uit de kennisgraaf):
- {article_label_1}: {reason_1}
- {article_label_2}: {reason_2}

Kandidaat-uitspraken (N):
[1] ECLI:NL:RBAMS:2022:5678 | Rechtbank Amsterdam | 2022-03-14 | sim 0.81
    "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig …"
[2] …

Kies 3 uitspraken via `select_cases`. Geef voor elke keuze een korte
Nederlandse reden (1–2 zinnen) die verwijst naar feitelijke gelijkenis,
juridische strekking, of toepassing van de genoemde artikelen.
```

Note: `question` is a new field on `CaseRetrieverIn` (§4.1). Statute-context article titles are **not** rendered — `CitedArticle` carries only `article_label` and `reason`. The label + reason is sufficient anchoring; the statute retriever's reason is already the model's best summary of why the article matters.

## 4. Schema changes — `src/jurist/schemas.py`

### 4.1 `CaseRetrieverIn` — add `question`

```python
class CaseRetrieverIn(BaseModel):
    question: str                 # NEW — user's original wording, threaded from orchestrator
    sub_questions: list[str]
    statute_context: list[CitedArticle]
```

The orchestrator already has `question` in scope (passed to `run_question`). Adding it to the `CaseRetrieverIn` is one line in `src/jurist/api/orchestrator.py` where `case_in` is constructed.

**No other schema changes.** `CitedCase`, `CaseRetrieverOut`, `CaseChunkRow`, and the trace/structured-answer types are untouched.

### 4.2 `CaseCandidate` and `RerankPick` are NOT in `schemas.py`

They are dataclasses local to `case_retriever_tools.py` — internal handoff types, never serialized, never crossing the SSE boundary. Keeping them out of `schemas.py` avoids polluting the Pydantic surface with in-process types.

## 5. Agent — `src/jurist/agents/case_retriever.py`

### 5.1 Shape (replaces the M0 fake entirely)

```python
async def run(
    input: CaseRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    yield TraceEvent(type="search_started")

    candidates = retrieve_candidates(
        store=ctx.case_store,
        embedder=ctx.embedder,
        query="\n".join(input.sub_questions),
        chunks_top_k=settings.caselaw_candidate_chunks,
        eclis_limit=settings.caselaw_candidate_eclis,
        snippet_chars=settings.caselaw_rerank_snippet_chars,
    )
    if len(candidates) < 3:
        raise RerankFailedError(
            f"retrieval produced {len(candidates)} candidates (<3); "
            "LanceDB index may be underpopulated or query wildly off-topic"
        )

    for cand in candidates:
        yield TraceEvent(
            type="case_found",
            data={"ecli": cand.ecli, "similarity": cand.similarity},
        )

    picks = await _rerank_with_retry(
        client=ctx.llm,
        candidates=candidates,
        question=input.question,
        sub_questions=input.sub_questions,
        statute_context=input.statute_context,
    )

    yield TraceEvent(
        type="reranked",
        data={"kept": [p.ecli for p in picks]},
    )

    by_ecli = {c.ecli: c for c in candidates}
    cited = [
        CitedCase(
            ecli=p.ecli,
            court=by_ecli[p.ecli].court,
            date=by_ecli[p.ecli].date,
            snippet=by_ecli[p.ecli].snippet,
            similarity=by_ecli[p.ecli].similarity,
            reason=p.reason,
            url=by_ecli[p.ecli].url,
        )
        for p in picks
    ]
    yield TraceEvent(
        type="agent_finished",
        data=CaseRetrieverOut(cited_cases=cited).model_dump(),
    )
```

### 5.2 Rerank call — non-streaming, forced tool

Forced-tool responses rarely emit pre-tool prose, so streaming adds no UX value. A single `await client.messages.create(...)`:

```python
response = await client.messages.create(
    model=settings.model_rerank,
    system=[{"type": "text", "text": render_case_rerank_system(),
             "cache_control": {"type": "ephemeral"}}],
    tools=[build_rerank_tool_schema([c.ecli for c in candidates])],
    tool_choice={"type": "tool", "name": "select_cases"},
    messages=[{"role": "user", "content": user_message}],
    max_tokens=1500,
)
tool_use = _extract_tool_use(response, "select_cases")    # or InvalidRerankOutput
_validate_picks(tool_use.input, candidate_eclis)           # or InvalidRerankOutput
return [RerankPick(**p) for p in tool_use.input["picks"]]
```

### 5.3 Regen semantics

```python
async def _rerank_with_retry(...) -> list[RerankPick]:
    system = render_case_rerank_system()
    user = build_rerank_user_message(question, sub_questions, statute_context, candidates)
    schema = build_rerank_tool_schema([c.ecli for c in candidates])

    try:
        return await _rerank_once(client, system, user, schema)
    except InvalidRerankOutput as first_err:
        logger.warning("rerank attempt 1 invalid: %s — retrying once", first_err)
        user_retry = (
            user + "\n\n"
            f"Je vorige antwoord was ongeldig ({first_err}). "
            "Kies exact 3 verschillende ECLI's uit de lijst en geef "
            "voor elk een korte Nederlandse reden (≥20 tekens)."
        )
        try:
            return await _rerank_once(client, system, user_retry, schema)
        except InvalidRerankOutput as second_err:
            raise RerankFailedError(
                f"case rerank invalid after retry: {second_err}"
            ) from second_err
```

Matches the parent spec §5.4's synthesizer grounding philosophy: one regen with an advisory addendum pointing at the specific defect, then hard-fail. No silent fallback to cosine-only top-3 with fabricated reasons.

### 5.4 What counts as invalid

Checked in order, cheapest first:

1. No `tool_use` content block in the response (model returned text only — rare with `tool_choice`, but possible on model glitch).
2. `tool_use.name != "select_cases"` (model called a different tool — shouldn't happen with forced choice).
3. `tool_use.input["picks"]` length ≠ 3.
4. Duplicate ECLIs in `picks`.
5. An ECLI not in the candidate set.
6. Any `reason` shorter than 20 characters after strip.

Anthropic's SDK enforces the JSON Schema server-side (items 3–5 covered by `minItems/maxItems/uniqueItems/enum`), so the Python-side validation is a safety net. Regen is real insurance against (1)–(2) and transient malformed outputs.

### 5.5 New exception type

```python
# src/jurist/agents/case_retriever.py
class RerankFailedError(Exception):
    """Rerank produced invalid output twice. Propagates to orchestrator,
    which emits run_failed { reason: 'case_rerank', detail: str(exc) }."""
```

Lives in the agent module (alongside `run`), not in `schemas.py` — it's not a data type, it's a runtime signal.

## 6. Orchestrator integration — `src/jurist/api/orchestrator.py`

Wrap the case_retriever pump in a try/except that mirrors the statute_retriever guard:

```python
try:
    case_final = await _pump(
        "case_retriever",
        case_retriever.run(case_in, ctx=ctx),
        run_id, buffer,
    )
except RerankFailedError as exc:
    logger.exception("run_failed id=%s reason=case_rerank: %s", run_id, exc)
    await buffer.put(TraceEvent(
        type="run_failed", run_id=run_id, ts=_now_iso(),
        data={"reason": "case_rerank", "detail": str(exc)},
    ))
    return
except Exception as exc:   # noqa: BLE001 — LLM 5xx / network / auth / unexpected
    logger.exception("run_failed id=%s reason=llm_error: %s", run_id, exc)
    await buffer.put(TraceEvent(
        type="run_failed", run_id=run_id, ts=_now_iso(),
        data={"reason": "llm_error", "detail": f"{type(exc).__name__}: {exc}"},
    ))
    return
case_out = CaseRetrieverOut.model_validate(case_final.data)
```

**Construction of `case_in` gains `question=question`** — one-line change on the existing `CaseRetrieverIn(...)` call.

Two `run_failed` reasons, rendered identically by the frontend's existing `run_failed` banner path (shipped in M0). No frontend changes.

## 7. API lifespan — `src/jurist/api/app.py`

Extend the existing KG fail-fast check with parallel gates for LanceDB presence + non-emptiness, then cold-load the Embedder before returning the lifespan.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # existing: KG
    if not settings.kg_path.exists():
        raise RuntimeError(
            f"KG missing at {settings.kg_path}. Run: uv run python -m jurist.ingest --refresh"
        )
    kg = load_kg(settings.kg_path)

    # NEW: LanceDB presence + non-emptiness
    if not settings.lance_path.exists():
        raise RuntimeError(
            f"LanceDB case index missing at {settings.lance_path}. "
            "Run: uv run python -m jurist.ingest.caselaw"
        )
    case_store = CaseStore(settings.lance_path)
    case_store.open_or_create()
    if case_store.row_count() == 0:
        raise RuntimeError(
            f"LanceDB at {settings.lance_path} is empty. Run: uv run python -m jurist.ingest.caselaw"
        )

    # NEW: Embedder cold-load (~5-10 s, one-time per process)
    logger.info("loading embedder %s (cold load ~5-10 s)", settings.embed_model)
    embedder = Embedder(model_name=settings.embed_model)

    llm = AsyncAnthropic(api_key=settings.anthropic_api_key)
    app.state.ctx = RunContext(kg=kg, llm=llm, case_store=case_store, embedder=embedder)
    yield
```

**Startup latency.** API cold-start rises from ~1 s (M2) to ~6–11 s (M3b). One-time per process; Embedder is ~1.1 GB RAM-resident after load. Dev hot-reload loops get slower but remain usable.

## 8. Configuration — `src/jurist/config.py`

New settings (values are defaults; env vars override):

```python
# M3b — case retriever
model_rerank: str = os.getenv(
    "JURIST_MODEL_RERANK", "claude-haiku-4-5-20251001"
)
caselaw_candidate_chunks: int = int(
    os.getenv("JURIST_CASELAW_CANDIDATE_CHUNKS", "150")
)
caselaw_candidate_eclis: int = int(
    os.getenv("JURIST_CASELAW_CANDIDATE_ECLIS", "20")
)
caselaw_rerank_snippet_chars: int = int(
    os.getenv("JURIST_CASELAW_RERANK_SNIPPET_CHARS", "400")
)
```

`RunContext` gains two fields:

```python
@dataclass(frozen=True)
class RunContext:
    kg: KnowledgeGraph
    llm: Any                  # AsyncAnthropic
    case_store: CaseStore     # NEW
    embedder: Embedder        # NEW
```

`.env.example` adds one-line docs for each new env var.

### 8.1 Defaults rationale

- **150 candidate chunks.** M3a corpus averages 7.8 chunks/case; 150 chunks statistically dedupes to ≥20 unique ECLIs with headroom for skew (clustering on highly relevant cases). Single LanceDB call; <200 ms over ~47k rows.
- **20 candidate ECLIs.** Parent spec §5.3's original "top-20" figure. 20 × ~500-char snippets ≈ 2–3 kilotokens of user-message payload — within Haiku's sweet spot.
- **400-char snippet.** ~60–80 Dutch words. Enough for Haiku to judge legal relevance; small enough to keep prompt compact. Tunable if empirically low recall.
- **Haiku 4.5.** Per parent §4 + decision #5: "3-of-20 rerank — small, cheap, fast." Env-var-configurable in case quality testing reveals weak reasons and we need Sonnet.

## 9. Mock clients for tests — `tests/fixtures/mock_llm.py`

Added alongside the existing `MockAnthropicClient` (streaming) for rerank tests:

```python
class MockMessagesClient:
    """Mocks AsyncAnthropic.messages.create for forced-tool, non-streaming calls.
    Returns a canned response from a queue; queued Exceptions simulate network errors."""
    def __init__(self, tool_inputs: list[dict | Exception]) -> None: ...
    async def create(self, **_kwargs) -> Any: ...      # returns a namespace with .content

class MockAnthropicForRerank:
    """Mirrors AsyncAnthropic's `.messages` attribute shape."""
    def __init__(self, tool_inputs: list[dict | Exception]) -> None:
        self.messages = MockMessagesClient(tool_inputs)
```

The agent code calls `ctx.llm.messages.create(...)` — identical surface for both mock and real. No `_is_mock()` heuristic needed (contrast with statute retriever's streaming path, which uses duck-typing between `next_turn` and `messages`).

## 10. Testing

### 10.1 Unit

**`tests/agents/test_case_retriever_tools.py`** — pure helper (no async, no mocks of Anthropic):
- `retrieve_candidates`: desc-sorted input preserved; group-by-ECLI keeps the first (best) chunk per ECLI; `eclis_limit` caps correctly; empty store → empty list; snippet truncation + ellipsis suffix.
- `build_rerank_tool_schema`: `enum` is exactly `candidate_eclis`; `minItems == maxItems == 3`; `uniqueItems` true; `reason.minLength == 20`; top-level `required == ["picks"]`.
- `build_rerank_user_message`: includes question, sub-questions, article labels + reasons, numbered candidates with ECLI/court/date/similarity/snippet.

**`tests/agents/test_case_retriever.py`** — async agent happy path. Fixtures: a mocked `Embedder` returning a fixed (1, 1024) vector; a `tmp_path`-backed `CaseStore` populated with 25 synthetic rows spread across 10 ECLIs; `MockAnthropicForRerank` returning a valid `{picks: [...]}` response with 3 real candidate ECLIs. Asserts:
- Event order is `agent_started`, `search_started`, N × `case_found` (N ≤ 10 after dedupe), `reranked`, `agent_finished`.
- Final payload validates as `CaseRetrieverOut` with 3 `CitedCase`s.
- Each `CitedCase.similarity` matches the best-chunk similarity from the mocked store.
- Each `CitedCase.reason` matches the Haiku mock input.

**`tests/agents/test_case_retriever_errors.py`** — error surfaces:
- Invalid first response (missing tool_use) → regen with advisory → valid → succeeds, one WARNING logged.
- Invalid first response + invalid second response → `RerankFailedError`.
- Corpus with <3 unique ECLIs → `RerankFailedError` raised **before** the Anthropic mock is called (use a mock that fails the test if invoked).
- Rerank output with duplicate ECLIs → treated as invalid → triggers regen.
- Rerank output with an ECLI not in the candidate set → invalid → regen.
- Rerank output with a reason shorter than 20 chars → invalid → regen.

**`tests/api/test_orchestrator.py`** — extend:
- Patch `case_retriever.run` to raise `RerankFailedError` → orchestrator emits `run_failed{reason:"case_rerank", detail:…}`; no `agent_finished` from case_retriever.
- Patch `case_retriever.run` to raise a generic `RuntimeError` → `run_failed{reason:"llm_error"}`.

**`tests/vectorstore/test_vectorstore.py`** — update the single assertion site consuming `query()`: unpack `(row, sim)` tuples; verify `sim` is in `(0, 1]` for a synthetic match and monotonically non-increasing across the returned list.

### 10.2 Integration — `tests/integration/test_m3b_case_retriever_e2e.py`

`RUN_E2E=1`-gated. Real `Embedder`, real LanceDB (assumes M3a ingest already ran on the host; skip with a clear message if `lance_path` is missing), real Haiku. Locked question as input.

Asserts:
- `CaseRetrieverOut.cited_cases` length == 3.
- Every returned ECLI exists in LanceDB (`case_store.contains_ecli`).
- Every similarity ∈ (0, 1].
- Every reason is ≥20 characters and contains at least one Dutch letter (rules out "" and garbage encodings).
- Every `url` matches `^https://uitspraken\.rechtspraak\.nl/details\?id=ECLI:`.
- Run completes in <30 s (not a hard cap; diagnostic on regressions).

### 10.3 What is NOT tested

- Relevance of top-3 against a gold standard (v2 scope — evaluation harness).
- Cross-question stability (v2 scope).
- bge-m3 query-time determinism (already verified by the M3a integration test; not re-asserted here).

## 11. Dependencies

**None added.** `sentence-transformers` and `lancedb` landed in M3a; `anthropic` in M2. `pyproject.toml` is unchanged.

## 12. Parent-spec amendments

A single commit precedes M3b implementation, editing `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`:

1. **§5.3 Implementation step 2** — replace "LanceDB cosine top-20 (no subject_uri filter — the keyword fence at ingest time ensures all rows are huurrecht-relevant)" with:

   > *LanceDB cosine top-`caselaw_candidate_chunks` chunks (default 150), group-by-ECLI keeping the best chunk per ECLI, take up to `caselaw_candidate_eclis` unique ECLIs (default 20). Rationale: M3a's observed ~7.8 chunks/case meant top-20 chunks collapsed to ~2–3 unique ECLIs, starving the rerank.*

2. **§5.3 `CaseRetrieverIn`** — add `question: str` field at the top of the model.

3. **§13 Configuration** — add the four new env vars (§8 of this doc).

4. **§15 Decisions log** — three new entries:
   - Candidate pool: top-150 chunks → group-by-ECLI → top-20 ECLIs, vs. parent-spec's literal top-20 chunks. Reason: M3a corpus statistics showed top-20 chunks collapse to ~2–3 ECLIs after ECLI-dedup.
   - Closed-set grounding on rerank via JSON-Schema `enum`. Reason: mirrors synthesizer's per-request `Literal[…]` pattern (decision #9) at the retrieval-output boundary as well as the answer boundary.
   - Rerank hard-fail with one regen, via `RerankFailedError` → `run_failed{reason:"case_rerank"}`. Reason: consistent with synthesizer's grounding philosophy; loud demo failure beats silent degradation.

The amendment is a prerequisite commit, not part of M3b's implementation commits. Lands on `m3b-case-retriever` as Task 0.

## 13. Out of scope / deferred

- **Streaming deltas during rerank.** Forced-tool, non-streaming call — no text to show. Could switch to `messages.stream` later if pre-tool prose becomes relevant.
- **Reranker diversity constraints** (e.g., force one case per decade or per instantie). No demand today; rerank prompt can be nudged via system message if needed.
- **Freshness weighting** on retrieval (leverage `CaseChunkRow.modified`). Parked in M3a's §13 as a v2 item.
- **Multi-rechtsgebied rerank**. The `CaselawProfile` registry from M3a supports future corpora; the retriever just queries the single configured index.
- **BM25 / hybrid retrieval**. Pure vector is strong enough for this corpus + rerank stage; hybrid is a v2 evaluation-harness call.
- **Caching of query embeddings**. Unique user questions → no cache hit ratio. Deferred.
- **Parallel agent execution** (statute + case in parallel). Parent spec §15 decision #6: sequential for trace clarity.
- **Sonnet on rerank by default.** Haiku is the spec choice; env var flips to Sonnet without code change.

## 14. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Haiku produces weak / generic Dutch reasons ("deze zaak is relevant") | Medium | Integration test asserts ≥20 chars; empirical review on locked question before declaring done. If weak, raise `minLength` in schema, or flip `JURIST_MODEL_RERANK` to Sonnet. |
| bge-m3 query embedding shifts between process restarts (CPU nondeterminism) | Low | Already asserted deterministic by M3a's integration test. Safe. |
| LanceDB cosine returns non-descending similarities (edge case on tied scores) | Low | `retrieve_candidates` relies on the desc-sort invariant. Test: if LanceDB ever breaks this, dedupe might keep the wrong chunk. Add explicit `sorted(...)` guard if flagged in testing. |
| Embedder cold-load fails at API start (HF cache corruption) | Low | `Embedder.__init__` raises; API refuses to start with a readable error. Operator re-runs ingest or clears HF cache. |
| >10% rerank regen rate in prod | Low | Logged per-regen WARNING; easy to grep. Triggers a Sonnet flip or a prompt revision. |
| API startup latency regression (Embedder load on every reload) | Low | One-time per process; dev `uvicorn --reload` tolerates it. Alternative: lazy-load on first query — rejected; fail-fast preferred. |
| Rerank prompt exceeds context (20 × 400-char snippet + statute context) | Very low | ~3–4 kilotokens total; Haiku 4.5 context is 200k. No concern. |
| Locked question yields <3 unique ECLIs (pathological) | Very low | Acceptance criterion #6 already demands ≥100 unique ECLIs in the corpus; huur-specific retrieval on M3a's 6,088 ECLIs essentially guarantees >20 matches. |

## 15. Acceptance criteria

M3b is done when:

1. Parent-spec amendment commit landed on `m3b-case-retriever` as the first commit (§12).
2. `case_retriever.run()` is no longer a fake; it runs the real pipeline (§2.1).
3. On the locked question, end-to-end via `python -m jurist.api` + the real frontend: `CaseRetrieverOut.cited_cases` has length 3; every ECLI exists in LanceDB; every similarity ∈ (0, 1]; every reason is a ≥20-char Dutch string.
4. Click a case citation in the UI → opens `https://uitspraken.rechtspraak.nl/details?id=ECLI:...` in a new tab.
5. With `data/lancedb/cases.lance` absent or empty, `python -m jurist.api` refuses to start and names the ingest command in the error message.
6. A pathological rerank (two consecutive malformed responses) surfaces as `run_failed{reason:"case_rerank"}` and a visible banner in the UI — not a silent cosine fallback.
7. `uv run pytest -v` green across all listed unit tests (§10.1).
8. `RUN_E2E=1 uv run pytest tests/integration/test_m3b_case_retriever_e2e.py` green (§10.2).
9. `uv run ruff check .` clean.
10. `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` reflects the §12 amendments; no stale references to "top-20 chunks".
11. CLAUDE.md updated: `case_retriever` moved from fake→real in the state table; M3b referenced as landed; startup latency note updated.

## 16. Decisions log (M3b-specific)

| # | Decision | Alternatives considered | Reason |
|---|---|---|---|
| 1 | Over-fetch 150 chunks → dedupe to 20 unique ECLIs | Parent-spec literal top-20 chunks; adaptive widening (20→40→80); score-threshold pool | M3a stats: avg 7.8 chunks/case ⇒ top-20 chunks collapses to ~2-3 ECLIs. Fixed over-fetch is predictable (one DB call) and statistically safe at the 150/20 ratio. |
| 2 | Embed concatenated sub-questions only (no enrichment) | Enrich with concepts; enrich with statute titles/body | bge-m3 handles short Dutch queries well; the LLM in rerank is better at reasoning about statute relevance textually than a vector is at blending heterogeneous signals. |
| 3 | Haiku 4.5 for rerank, env-var-configurable | Sonnet 4.6 locked; Opus | Parent spec §4 + decision #5: "3-of-20 rerank — small, cheap, fast." Forced-tool structured output, not agentic tool-loop reasoning. Env var allows flip to Sonnet if empirical quality demands it. |
| 4 | Closed-set grounding on rerank via JSON-Schema `enum` on `ecli` | Post-hoc validation only | Mirrors synthesizer's per-request `Literal[...]` (spec §15 decision #9). Schema-level enforcement blocks the easy hallucination path before generation. |
| 5 | One regen, then hard-fail (`RerankFailedError` → `run_failed{reason:"case_rerank"}`) | Soft-degrade to cosine-only top-3 with generic reasons; one-regen-then-soft-degrade hybrid | Consistent with synthesizer's grounding philosophy; loud demo failure beats silent degradation; `Literal` enum + forced tool should keep invalid outputs genuinely rare. |
| 6 | Agent module + pure helper (retrieval + schema/prompt builders) | Monolithic agent; symmetric M2-style tools module | Helper boundary gives two clean test surfaces (pure sync + async-with-mocks). Matches M3a's `caselaw.py`/`caselaw_fetch.py`/`caselaw_parser.py` split. M2's tools module is justified by a tool-loop executor with many methods; M3b has one LLM call. |
| 7 | Fail-fast on missing/empty LanceDB at API startup | Lazy-fail at first case query; soft-warn + lazy-fail | Matches M2's KG gate; no partial-demo state; ingest is a one-time per machine, so the gate almost never triggers. |
| 8 | `CaseStore.query()` returns `list[tuple[CaseChunkRow, float]]` | Add similarity as a field on CaseChunkRow; add a parallel `query_with_scores()` method | Similarity is a query-time artifact, not a storage property. Tuple-return is minimally invasive; one M3a test to update. |
| 9 | Add `question: str` to `CaseRetrieverIn` | Embed statute context into rerank prompt only, keep signature | Rerank benefits from the user's original wording (matters for Dutch intent); orchestrator already has `question` in scope; single-field signature change. |
| 10 | Non-streaming `messages.create` (not `run_tool_loop`) | Reuse `run_tool_loop` for symmetry with statute retriever | One forced-tool call, no iteration. Streaming adds no UX value for a structured-only output. Simpler code, no `_is_mock` heuristic needed (both real and mock share `.messages.create`). |
| 11 | `CaseCandidate` / `RerankPick` as `@dataclass`, not Pydantic; live in agent tools module | Pydantic models in `schemas.py` | Internal handoff types, never serialized. Keeping them out of `schemas.py` avoids polluting the Pydantic surface with in-process concerns. |
| 12 | Snippet truncation at 400 chars with trailing ellipsis | 250 / 500 / 800 chars; word-boundary trim | ~60-80 Dutch words gives Haiku enough legal context to judge relevance. 20 × 400 chars ≈ 2-3 kilotokens — comfortable for Haiku. Tunable via `JURIST_CASELAW_RERANK_SNIPPET_CHARS`. |

---

*End of spec.*
