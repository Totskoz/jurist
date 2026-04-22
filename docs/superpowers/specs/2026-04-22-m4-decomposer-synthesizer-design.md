# M4 — Decomposer + Synthesizer + Closed-Set Grounding — Design

**Date:** 2026-04-22
**Status:** Approved. Implementation not yet started.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§5.1, §5.4, §11 M4)
**Siblings:** `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md`, `docs/superpowers/specs/2026-04-21-m3b-case-retriever-design.md`
**Branch:** `m4-decomposer-synthesizer`

---

## 1. Context and goals

M3b shipped the case retriever. The only remaining fakes in the pipeline are the **decomposer** (M0: hardcoded thinking deltas + canned `DecomposerOut`) and the **synthesizer** (M0: token-streams `FAKE_ANSWER`). The validator stays a permanent stub per parent spec §5.5.

**M4 turns both fakes into real LLM agents** and ships the spec-mandated closed-set citation grounding (parent §5.4 + §15 decision #9). No orchestrator restructuring; no frontend work. One parent-spec amendment commit precedes implementation.

**Done when** (inherits parent §11 M4 + this spec's §6.3):

1. Parent-spec amendment commit landed on the branch (§5 of this doc).
2. `decomposer.run()` runs a real Haiku forced-tool call with one-regen-then-hard-fail.
3. `synthesizer.run()` streams Dutch reasoning as `agent_thinking`, calls a forced tool `emit_answer` with per-request `Literal[...]` enums on `article_id` / `bwb_id` / `ecli`, runs `verify_citations()` (whitespace-normalized strict substring), regenerates once on failure with a Dutch advisory, and hard-fails to `run_failed{reason:"citation_grounding"}` on persistent mismatch.
4. On the locked question, the structured answer renders; every citation resolves; clicking a citation navigates to the correct source document.
5. Grounding guard test green (schema enum equals candidate set; post-hoc catches unknown IDs; agent hard-fails on a scripted imagined-ID).
6. `uv run pytest -v` green across new unit tests. `RUN_E2E=1 uv run pytest tests/integration/test_m4_e2e.py` green. `uv run ruff check .` clean.
7. Parent spec amended; CLAUDE.md state table updated.

**In scope.** Two new real agents. One new pure-helper module (`synthesizer_tools.py`). Two `schemas.py` changes (`WetArtikelCitation` adds `article_id`; `CitedCase` adds `chunk_text`). One `case_retriever.py` + `case_retriever_tools.py` change to populate `chunk_text`. Three new exception types (`DecomposerFailedError`, `InvalidDecomposerOutput`, `CitationGroundingFailedError`). One new streaming mock (`MockStreamingClient`). Three new settings (`model_decomposer`, `model_synthesizer`, `synthesizer_max_tokens`). Parent-spec amendment (§5.1/5.3/5.4/6.3/11/13/15).

**Out of scope.** Validator (permanent stub). Frontend changes. Multi-rechtsgebied. Evaluation harness. Parallel agent execution. Opus routing (env-var flip only). Polish on citation UI. Streaming tool-input JSON to the UI.

## 2. Architecture

### 2.1 Pipeline (unchanged)

Orchestrator still chains decomposer → statute_retriever → case_retriever → synthesizer → validator_stub on one asyncio task. M4 replaces two agents in place; no sequencing, no event-protocol change.

### 2.2 File map

**Added:**
- `src/jurist/agents/synthesizer_tools.py` — pure sync helpers: `build_synthesis_tool_schema`, `build_synthesis_user_message`, `verify_citations`, `_normalize`, `_validate_attempt`, `_format_regen_advisory`, `FailedCitation` dataclass.
- `src/jurist/llm/prompts/synthesizer.system.md` — static Dutch system prompt template.
- `tests/agents/test_decomposer.py`
- `tests/agents/test_synthesizer_tools.py`
- `tests/agents/test_synthesizer.py`
- `tests/agents/test_synthesizer_grounding.py` (spec-mandated guard)
- `tests/integration/test_m4_e2e.py` (RUN_E2E-gated)

**Modified:**
- `src/jurist/agents/decomposer.py` — rewritten; real Haiku forced-tool call + inline regen helper.
- `src/jurist/agents/synthesizer.py` — rewritten; streaming `messages.stream()` for `agent_thinking`, forced-tool extraction, inline regen helper, post-hoc verify, synthetic `answer_delta` replay.
- `src/jurist/schemas.py` — `WetArtikelCitation` gains `article_id: str`; `CitedCase` gains `chunk_text: str`.
- `src/jurist/agents/case_retriever_tools.py` — `CaseCandidate` gains full-length `chunk_text` (separate from truncated `snippet`); `retrieve_candidates` fills both.
- `src/jurist/agents/case_retriever.py` — populates `CitedCase.chunk_text` from the best chunk's full text at assembly.
- `src/jurist/llm/prompts.py` — adds `render_synthesizer_system()` (file-based) and `render_decomposer_system()` (inline string).
- `src/jurist/api/orchestrator.py` — wraps decomposer pump in try/except catching `DecomposerFailedError` → `run_failed{reason:"decomposition"}` and generic `Exception` → `run_failed{reason:"llm_error"}`; wraps synthesizer pump in try/except catching `CitationGroundingFailedError` → `run_failed{reason:"citation_grounding"}` and generic `Exception` → `run_failed{reason:"llm_error"}`. Mirrors the existing statute / case guards.
- `src/jurist/config.py` — three new settings (§7.4).
- `tests/fixtures/mock_llm.py` — adds `MockStreamingClient` + `StreamScript` for the synthesizer's `messages.stream()` path.
- `src/jurist/fakes.py` — `FAKE_ANSWER`'s `WetArtikelCitation`s gain `article_id`; `FAKE_CASES`'s `CitedCase`s gain `chunk_text` so fixtures still validate.
- `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` — amendments per §5 of this doc.
- `.env.example` — documents the three new env vars.
- `CLAUDE.md` — state table: decomposer + synthesizer move from fake to real.

**Unchanged.** KG ingestion, caselaw ingestion, statute retriever, case retriever (beyond the `chunk_text` wire-through), validator stub, frontend (KGPanel, TracePanel, AnswerPanel, CitationLink, runStore), SSE transport, LanceDB, Embedder.

### 2.3 Concurrency

Each new agent runs on the single orchestrator task. One forced-tool call each; one potential regen call. All sync inside the async body outside Anthropic awaits.

### 2.4 New exception types

- `DecomposerFailedError` (in `decomposer.py`) — raised when the second decomposer attempt also fails. Orchestrator → `run_failed{reason:"decomposition"}`.
- `CitationGroundingFailedError` (in `synthesizer.py`) — raised when the second synthesizer attempt also fails `verify_citations`. Orchestrator → `run_failed{reason:"citation_grounding"}`.
- `InvalidDecomposerOutput` (in `decomposer.py`) — decomposer analog; raised by a single attempt on missing tool_use or Pydantic-invalid input; wrapped into `DecomposerFailedError` on second failure.

The synthesizer does **not** use an `InvalidSynthesisOutput` exception. Its attempt-level decision uses a pure sync helper `_validate_attempt(tool_input, input) → (failures, schema_ok)` (see §4.6). This keeps the control flow flat in the agent's `run()` body without needing to wrap-and-catch for a branch that already has both inputs (failure list + schema success flag) in hand.

## 3. Decomposer

### 3.1 Call shape

One non-streaming `ctx.llm.messages.create(...)` with `tool_choice={"type":"tool","name":"emit_decomposition"}`. Haiku 4.5, `max_tokens=1000`.

### 3.2 Tool schema (inline in `decomposer.py`)

```python
{
  "name": "emit_decomposition",
  "description": "Decomposeer een Nederlandse huurrecht-vraag in sub-vragen, concepten, en intentie.",
  "input_schema": {
    "type": "object",
    "properties": {
      "sub_questions": {"type": "array", "minItems": 1, "maxItems": 5,
                        "items": {"type": "string", "minLength": 5}},
      "concepts":      {"type": "array", "minItems": 1, "maxItems": 10,
                        "items": {"type": "string", "minLength": 2}},
      "intent":        {"type": "string",
                        "enum": ["legality_check", "calculation", "procedure", "other"]},
    },
    "required": ["sub_questions", "concepts", "intent"],
  },
}
```

### 3.3 System prompt (inline in `llm/prompts.py::render_decomposer_system()`)

```
Je bent een Nederlandse juridische assistent gespecialiseerd in huurrecht.
Je decomposeert huurrecht-vragen in 1–5 sub-vragen, 1–10 juridische
concepten (Nederlandse termen), en een intentie uit
{legality_check, calculation, procedure, other}.
Roep uitsluitend het hulpmiddel `emit_decomposition` aan. Geen vrije tekst.
```

Too short (~200 chars) for `cache_control: ephemeral` to pay off. No caching.

### 3.4 User message

```
Vraag: {question}

Decomposeer deze vraag via `emit_decomposition`.
```

### 3.5 Events

- `agent_started`
- `agent_finished{payload: DecomposerOut}`

No `agent_thinking` — "geen vrije tekst" in the system prompt suppresses it. TracePanel shows the decomposer step briefly and moves on; that is honest.

### 3.6 Invalid output (`InvalidDecomposerOutput`)

Raised when, in order of cheapest-first:

1. No `tool_use` block in response.
2. `tool_use.name != "emit_decomposition"`.
3. `DecomposerOut.model_validate(tool_use.input)` fails.

### 3.7 Regen

One attempt. Advisory addendum in Dutch tacked onto the user message:

```
Je vorige antwoord was ongeldig ({detail}). Roep `emit_decomposition` aan
met geldige velden.
```

Still failing → `raise DecomposerFailedError(detail)`.

## 4. Synthesizer

The load-bearing agent. Five sub-parts: call shape, tool schema, user message, post-hoc verify, event emission.

### 4.1 Call shape

`ctx.llm.messages.stream()` with forced tool `emit_answer`. The system prompt encourages a short pre-tool reasoning pass in Dutch; those text deltas flow live to `agent_thinking`. Sonnet 4.6, `max_tokens=8192`.

```python
async with ctx.llm.messages.stream(
    model=settings.model_synthesizer,
    system=[{"type": "text", "text": render_synthesizer_system(),
             "cache_control": {"type": "ephemeral"}}],
    tools=[build_synthesis_tool_schema(article_ids, bwb_ids, eclis)],
    tool_choice={"type": "tool", "name": "emit_answer"},
    messages=[{"role": "user", "content": user_message}],
    max_tokens=settings.synthesizer_max_tokens,
) as stream:
    async for event in stream:
        if event.type == "content_block_delta" and event.delta.type == "text_delta":
            yield ("thinking", event.delta.text)
    final = await stream.get_final_message()
tool_use = _extract_tool_use(final, "emit_answer")    # None if no tool_use block
yield ("tool", tool_use.input if tool_use is not None else None)
```

The `_stream_attempt()` helper is an async generator yielding internal `(kind, payload)` tuples — `("thinking", str)` during streaming, then one final `("tool", dict)`. The outer `run()` translates them into `TraceEvent`s.

### 4.2 Tool schema (`build_synthesis_tool_schema` in `synthesizer_tools.py`)

```python
{
  "name": "emit_answer",
  "description": "Genereer het gestructureerde Nederlandse antwoord met gegrondveste citaten.",
  "input_schema": {
    "type": "object",
    "properties": {
      "korte_conclusie": {"type": "string", "minLength": 40, "maxLength": 2000},
      "relevante_wetsartikelen": {
        "type": "array", "minItems": 1, "items": {
          "type": "object",
          "properties": {
            "article_id":    {"type": "string", "enum": article_ids},
            "bwb_id":        {"type": "string", "enum": bwb_ids},
            "article_label": {"type": "string", "minLength": 5},
            "quote":         {"type": "string", "minLength": 40, "maxLength": 500},
            "explanation":   {"type": "string", "minLength": 40, "maxLength": 2000},
          },
          "required": ["article_id", "bwb_id", "article_label", "quote", "explanation"],
        },
      },
      "vergelijkbare_uitspraken": {
        "type": "array", "minItems": 1, "items": {
          "type": "object",
          "properties": {
            "ecli":        {"type": "string", "enum": eclis},
            "quote":       {"type": "string", "minLength": 40, "maxLength": 500},
            "explanation": {"type": "string", "minLength": 40, "maxLength": 2000},
          },
          "required": ["ecli", "quote", "explanation"],
        },
      },
      "aanbeveling": {"type": "string", "minLength": 40, "maxLength": 2000},
    },
    "required": ["korte_conclusie", "relevante_wetsartikelen",
                 "vergelijkbare_uitspraken", "aanbeveling"],
  },
}
```

Both `article_id` and `bwb_id` carry `enum` (belt-and-braces; bwb_id is derivable from article_id but the dual enum blocks the model from mixing them up).

### 4.3 User message (`build_synthesis_user_message`)

```
Vraag: {question}

Relevante wetsartikelen (gebruik uitsluitend deze article_id's):
[1] article_id: {article_id}
    bwb_id: {bwb_id}
    label: {article_label}
    reden (van de KG-retriever): {reason}
    tekst:
    {body_text}

[2] ...

Relevante uitspraken (gebruik uitsluitend deze ECLI's):
[1] ecli: {ecli} | {court} | {date} | similarity {similarity:.2f}
    reden (van de rerank): {reason}
    chunk:
    {chunk_text}

[2] ...

Instructies:
1. Denk kort hardop in het Nederlands over welke bronnen je zult citeren.
2. Roep daarna `emit_answer` aan. Citeer uitsluitend uit de meegeleverde
   brontekst, verbatim (40–500 tekens per quote).
3. Elk citaat moet letterlijk voorkomen in de bijbehorende brontekst.
```

Article `body_text` and case `chunk_text` are both fully in-prompt. Quote-verification target is unambiguous.

### 4.4 Post-hoc verification (`verify_citations` in `synthesizer_tools.py`)

```python
@dataclass(frozen=True)
class FailedCitation:
    kind: Literal["wetsartikel", "uitspraak"]
    id: str
    quote: str
    reason: Literal["not_in_source", "too_short", "too_long", "unknown_id"]

def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()

def verify_citations(
    answer: StructuredAnswer,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
    *,
    min_quote_chars: int = 40,
    max_quote_chars: int = 500,
) -> list[FailedCitation]:
    failures: list[FailedCitation] = []
    by_article = {a.article_id: a for a in cited_articles}
    by_case    = {c.ecli: c for c in cited_cases}
    for wa in answer.relevante_wetsartikelen:
        article = by_article.get(wa.article_id)
        if article is None:
            failures.append(FailedCitation("wetsartikel", wa.article_id, wa.quote, "unknown_id"))
            continue
        if len(wa.quote) < min_quote_chars:
            failures.append(FailedCitation("wetsartikel", wa.article_id, wa.quote, "too_short"))
        elif len(wa.quote) > max_quote_chars:
            failures.append(FailedCitation("wetsartikel", wa.article_id, wa.quote, "too_long"))
        elif _normalize(wa.quote) not in _normalize(article.body_text):
            failures.append(FailedCitation("wetsartikel", wa.article_id, wa.quote, "not_in_source"))
    for uc in answer.vergelijkbare_uitspraken:
        case = by_case.get(uc.ecli)
        if case is None:
            failures.append(FailedCitation("uitspraak", uc.ecli, uc.quote, "unknown_id"))
            continue
        if len(uc.quote) < min_quote_chars:
            failures.append(FailedCitation("uitspraak", uc.ecli, uc.quote, "too_short"))
        elif len(uc.quote) > max_quote_chars:
            failures.append(FailedCitation("uitspraak", uc.ecli, uc.quote, "too_long"))
        elif _normalize(uc.quote) not in _normalize(case.chunk_text):
            failures.append(FailedCitation("uitspraak", uc.ecli, uc.quote, "not_in_source"))
    return failures
```

Length checks are belt-and-braces with the schema's `minLength`/`maxLength`. The `unknown_id` check is the safety net if a tampered tool_input bypasses the schema (as in the grounding guard test). The `not_in_source` check is the real work.

### 4.5 Regen advisory

```python
def _format_regen_advisory(failures: list[FailedCitation]) -> str:
    lines = [
        "Je vorige antwoord bevatte ongeldige citaten. De volgende `quote`-velden "
        "kwamen niet verbatim voor in de meegeleverde brontekst:"
    ]
    for f in failures:
        short = (f.quote[:80] + "…") if len(f.quote) > 80 else f.quote
        lines.append(f"- [{f.kind} {f.id}] ({f.reason}): {short!r}")
    lines.append(
        "\nKies uitsluitend verbatim passages uit de meegeleverde brontekst. "
        "Lengte per quote tussen 40 en 500 tekens. Roep `emit_answer` opnieuw aan."
    )
    return "\n".join(lines)
```

Appended to the user message on the regen call.

### 4.6 Regen loop

The regen sits in the agent's `run()` body rather than a helper, because both attempts need to yield `agent_thinking` events live from the caller's async generator. Helper boundary would require wrapping every attempt as its own async generator — more ceremony than clarity.

Control flow (pseudo-code; actual implementation owns the details):

```python
async def run(input: SynthesizerIn, *, ctx: RunContext) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_synthesizer_system()
    user   = build_synthesis_user_message(...)
    schema = build_synthesis_tool_schema(article_ids, bwb_ids, eclis)

    # Attempt 1 — stream thinking, collect tool_input
    tool_input: dict | None = None
    async for kind, payload in _stream_attempt(ctx.llm, system, user, schema):
        if kind == "thinking":
            yield TraceEvent(type="agent_thinking", data={"text": payload})
        else:
            tool_input = payload

    # Validate attempt 1 (schema + post-hoc)
    first_failures, schema_ok = _validate_attempt(tool_input, input)
    # _validate_attempt returns (failures, True) on success; (failures_or_empty, False) on schema/missing-tool.

    if first_failures or not schema_ok:
        advisory = (_format_regen_advisory(first_failures)
                    if first_failures
                    else "Je vorige antwoord miste een geldige `emit_answer`-aanroep. "
                         "Roep het hulpmiddel correct aan.")
        logger.warning("synthesizer attempt 1 invalid — retrying once")
        user_retry = user + "\n\n" + advisory

        tool_input = None
        async for kind, payload in _stream_attempt(ctx.llm, system, user_retry, schema):
            if kind == "thinking":
                yield TraceEvent(type="agent_thinking", data={"text": payload})
            else:
                tool_input = payload

        second_failures, schema_ok = _validate_attempt(tool_input, input)
        if second_failures or not schema_ok:
            raise CitationGroundingFailedError(
                f"citation grounding failed after retry: "
                f"{second_failures or 'schema_invalid'}"
            )

    answer = StructuredAnswer.model_validate(tool_input)

    # citation_resolved ×M, answer_delta ×many, agent_finished — §4.7
    ...
```

`_validate_attempt(tool_input, input)` is a sync helper in `synthesizer_tools.py` that returns `(failures, schema_ok)`:

- If `tool_input is None` (no tool_use block) → `([], False)`.
- If `StructuredAnswer.model_validate(tool_input)` raises → `([], False)`.
- Otherwise → `(verify_citations(answer, ...), True)`.

### 4.7 Event emission (outer `run()`)

Order:

1. `agent_started`
2. `agent_thinking` × N — attempt 1 pre-tool prose
3. *(on regen)* `agent_thinking` × M — attempt 2 pre-tool prose
4. `citation_resolved` × (len(relevante_wetsartikelen) + len(vergelijkbare_uitspraken)) — one per citation after successful `verify_citations`; `resolved_url` = `https://wetten.overheid.nl/{bwb_id}` / `https://uitspraken.rechtspraak.nl/details?id={ecli}`
5. `answer_delta` × many — synthetic replay of `korte_conclusie + each explanation + aanbeveling`, word-tokenized at ~20ms per token (mirrors M0 fake's `_tokenize`)
6. `agent_finished{payload: SynthesizerOut}`

The synthesizer **does not** emit `agent_thinking` between attempts 1 and 2 to mark the regen boundary — the stream just carries on. If desired for debugging, the regen logs a WARNING.

## 5. Parent-spec amendments

Prepended as Task 0 on the branch. Edits `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`.

1. **§5.1 Decomposer** — add: *"One regen with a Dutch advisory on the user message, then hard-fail to `DecomposerFailedError` → `run_failed{reason:"decomposition"}` — consistent with M3b rerank and synthesizer."*

2. **§5.3 CaseRetriever** — `CitedCase` adds `chunk_text: str`: *"Full text of the best chunk per ECLI (~500 words). Consumed by the synthesizer as quote-verification surface. Not the same as `snippet` (400-char excerpt used in the rerank prompt)."*

3. **§5.4 Synthesizer** —
   - `WetArtikelCitation`: add `article_id: str` above `bwb_id`; note both are per-request `Literal[...]` enums.
   - Grounding mechanism: *"NFC-normalize both sides, collapse all whitespace runs to single spaces, strict case-sensitive substring. Quote length bounds 40–500 characters, enforced in the tool schema and re-checked post-hoc."*
   - Regen advisory shape: *"Regen addendum lists the failing `(kind, id, quote, reason)` tuples in Dutch; `reason ∈ {not_in_source, too_short, too_long, unknown_id}`."*
   - Event emission: *"`agent_thinking` streams live from Sonnet's pre-tool reasoning (encouraged by the system prompt). `answer_delta` events are a post-tool-call synthetic replay of the structured fields in Dutch — word-tokenized. `citation_resolved` fires per verified citation after post-hoc verification passes."*

4. **§6.3 Event types** — ensure `run_failed.data.reason` documentation lists `"decomposition"` and `"citation_grounding"` alongside `"llm_error"` and `"case_rerank"`.

5. **§11 M4 Done-when** — tighten the grounding guard test description to cover three assertions: (a) tool schema's `article_id.enum` / `ecli.enum` equal the candidate set; (b) `verify_citations` returns `FailedCitation(reason="unknown_id")` on a tampered `StructuredAnswer`; (c) agent end-to-end with an imagined-ID twice produces `run_failed{reason:"citation_grounding"}`.

6. **§13 Configuration** — add three env vars:
   - `JURIST_MODEL_DECOMPOSER` default `claude-haiku-4-5-20251001`
   - `JURIST_MODEL_SYNTHESIZER` default `claude-sonnet-4-6`
   - `JURIST_SYNTHESIZER_MAX_TOKENS` default `8192`

7. **§15 Decisions log** — five new entries (§9 of this doc).

## 6. Testing

### 6.1 Pure helper tests — `tests/agents/test_synthesizer_tools.py`

Sync, no Anthropic mock.

- `build_synthesis_tool_schema`: `article_id.enum == article_ids`, `bwb_id.enum == bwb_ids`, `ecli.enum == eclis`; quote `minLength == 40`, `maxLength == 500`; both citation arrays `minItems == 1`; top-level `required` contains all four fields.
- `build_synthesis_user_message`: includes question, each article's `body_text` and `reason`, each case's `chunk_text` and `reason`, Dutch instructions; field order stable.
- `verify_citations` happy path: quotes that are verbatim slices of the bodies/chunks → `[]`.
- `verify_citations` failures:
  - quote not in source → `FailedCitation(reason="not_in_source")`
  - whitespace-only-differing quote → passes (normalization works)
  - NFC vs NFD unicode variants of the same string → passes
  - quote length 39 → `too_short`; 501 → `too_long`
  - tampered `article_id` not in `cited_articles` → `FailedCitation(reason="unknown_id")`, not `KeyError`
  - same for tampered `ecli`
- `_normalize`: idempotent; collapses `\n\n`, `\t`, doubled spaces; NFC-normalizes composed/decomposed umlauts; strips leading/trailing whitespace.

### 6.2 Decomposer tests — `tests/agents/test_decomposer.py`

Async, uses existing `MockAnthropicForRerank`.

- Happy path: valid `emit_decomposition` input → events `[agent_started, agent_finished]`, `DecomposerOut` fields correct.
- Missing `tool_use` in first response → regen → valid second → succeeds, one WARNING logged.
- Two consecutive invalids → `DecomposerFailedError`, no `agent_finished`.
- Pydantic-invalid input (e.g., empty `sub_questions`) → regen.
- Advisory present in second call's user message (assert via `mock.messages.calls[1]["messages"]`).

### 6.3 Synthesizer agent tests — `tests/agents/test_synthesizer.py`

Async, uses new `MockStreamingClient`.

Fixture addition in `tests/fixtures/mock_llm.py`:

```python
@dataclass
class StreamScript:
    text_deltas: list[str]              # prose emitted as content_block_delta events
    tool_input: dict | Exception        # final tool_use.input, or an exception from the stream

class MockStreamingClient:
    """Mimics AsyncAnthropic's .messages.stream() async-context-manager shape.
    Each .stream() call pops one StreamScript. If tool_input is an Exception
    *instance*, it is raised from inside the async-iteration (simulates a mid-
    stream failure). An Exception *class* raises TypeError at queue-pop time to
    surface a test-setup mistake (matches MockMessagesClient convention)."""

    def __init__(self, scripts: list[StreamScript]) -> None: ...
    messages: _Messages                   # exposes .stream(**kwargs) -> AsyncContextManager
    calls: list[dict[str, Any]]           # inspectable; one entry per .stream() call, kwargs snapshotted
```

Tests:

- Happy path: one script, Dutch text deltas + valid tool_input citing verbatim slices → events in order `[agent_started, agent_thinking ×N, citation_resolved ×M, answer_delta ×many, agent_finished]`; `SynthesizerOut.answer` validates.
- Pre-tool prose: one `agent_thinking` event per delta.
- `citation_resolved.resolved_url` correct for both kinds.
- `answer_delta` concatenation matches `korte_conclusie + each explanation + aanbeveling`.
- Regen path: first script's tool_input has a quote not in any `body_text` → advisory included in second call's user message → second script's tool_input passes → succeeds, WARNING logged, `mock.messages.stream.calls == 2`.
- Hard-fail path: both scripts fail verification → `CitationGroundingFailedError`, no `agent_finished`.
- No tool_use in first response → regen path (missing-tool is a valid regen trigger).

### 6.4 Grounding guard test — `tests/agents/test_synthesizer_grounding.py`

Spec-mandated. Three assertions:

1. **Schema enum equals candidate set:** `build_synthesis_tool_schema([A,B,C], [bwb1], [E1,E2])["input_schema"]["properties"]["relevante_wetsartikelen"]["items"]["properties"]["article_id"]["enum"] == [A, B, C]`; same for `ecli`.
2. **Post-hoc catches unknown ID (no KeyError):** build a `StructuredAnswer` whose `WetArtikelCitation.article_id = "IMAGINED/XYZ"`, not in the cited_articles dict. `verify_citations(...)` returns a `FailedCitation(reason="unknown_id")`. Same for tampered `ecli`.
3. **Agent end-to-end hard-fails on imagined-ID:** `MockStreamingClient` script with two imagined-ID tool_inputs in a row → `run()` raises `CitationGroundingFailedError`.

### 6.5 Orchestrator tests — `tests/api/test_orchestrator.py`

- Patch `decomposer.run` to raise `DecomposerFailedError` → orchestrator emits `run_failed{reason:"decomposition", detail}`; no subsequent `agent_finished` events.
- Patch `synthesizer.run` to raise `CitationGroundingFailedError` → `run_failed{reason:"citation_grounding", detail}`.
- Happy path tests continue to use the fake pipeline; no new full-pipeline integration test here.

### 6.6 Integration — `tests/integration/test_m4_e2e.py`

`RUN_E2E=1`-gated. Real Anthropic, real KG, real LanceDB, real Embedder. Locked question. Asserts:

- Run terminates via `run_finished`, not `run_failed`.
- `final_answer.relevante_wetsartikelen` non-empty; every `article_id` in `cited_articles`; every `quote` is `_normalize`-substring of the corresponding `body_text`.
- `final_answer.vergelijkbare_uitspraken` non-empty; every `ecli` in `cited_cases`; every `quote` is `_normalize`-substring of the corresponding `chunk_text`.
- `final_answer.korte_conclusie` and `aanbeveling` each ≥40 chars.
- Elapsed <90 s (diagnostic; not a hard cap).

### 6.7 Fixture updates

- `src/jurist/fakes.py::FAKE_ANSWER`: each `WetArtikelCitation` gains `article_id` (set to a real id from `FAKE_KG`).
- `src/jurist/fakes.py::FAKE_CASES`: each `CitedCase` gains `chunk_text` (~500-char fake chunk; `snippet` stays the first 400 chars for consistency).
- Any existing test that pattern-matches on `WetArtikelCitation` or `CitedCase` field names gets a one-line update.
- `tests/vectorstore/*` unchanged (LanceDB schema unchanged).

## 7. Configuration

### 7.1 New settings in `src/jurist/config.py`

```python
# M4 — decomposer + synthesizer
model_decomposer: str = os.getenv(
    "JURIST_MODEL_DECOMPOSER", "claude-haiku-4-5-20251001"
)
model_synthesizer: str = os.getenv(
    "JURIST_MODEL_SYNTHESIZER", "claude-sonnet-4-6"
)
synthesizer_max_tokens: int = int(
    os.getenv("JURIST_SYNTHESIZER_MAX_TOKENS", "8192")
)
```

### 7.2 No `RunContext` changes

Decomposer and synthesizer use only `ctx.llm`, already threaded.

### 7.3 No new dependencies

`anthropic`, `sentence-transformers`, `lancedb`, `pydantic`, `fastapi` are all already installed via M0–M3b. `pyproject.toml` is untouched.

### 7.4 `.env.example`

Adds one-line docs for the three env vars above.

## 8. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Sonnet paraphrases instead of copying verbatim | Medium | Explicit Dutch instruction "letterlijk uit de meegeleverde brontekst"; 40–500 char bounds; regen with failing-quote advisory. If >10% regen rate observed empirically, tighten system prompt or flip to Opus via env var. |
| LanceDB's best chunk per ECLI doesn't contain a citable passage | Low-Medium | `chunk_text` is ~500 words; the best chunk is by cosine the most relevant. If it fails on the locked question, expand to all chunks for that ECLI — spec amendment. |
| Pre-tool prose empty (Sonnet skips reasoning) | Low | TracePanel degrades silently. Not fatal; UX is still correct. Tune prompt if the demo feels flat. |
| `MockStreamingClient` drifts from real SDK | Low | Integration test (§6.6) covers real SDK. Unit tests cover mock; integration covers real. |
| Synthesizer prompt exceeds context | Very low | 3 articles × ~2-5kB body + 3 chunks × ~3kB ≈ 25kB user message; Sonnet 4.6 context 200k. |
| NFC normalization masks a real hallucination | Very low | NFC is standard; model output should already be NFC. Normalization catches encoding drift, not paraphrase. |
| Regen triggers infinite-retry behavior | Very low | Hard cap at one regen; second failure hard-fails. |
| M4 model IDs drift from availability | Low | Env-var-configurable; spec-fixed defaults match current `.env.example`. |

## 9. Decisions log (M4-specific)

| # | Decision | Alternatives | Reason |
|---|---|---|---|
| 1 | Single M4 milestone (decomposer + synthesizer) | M4a/M4b split mirroring M3a/M3b; synthesizer-only (leave decomposer fake) | M3 split was justified by genuine ingestion engineering; M4 has no such surface — two forced-tool calls, small decomposer delta. Parent spec §11 already orders it this way. |
| 2 | Synthesizer UX = hybrid streaming + synthetic replay | Non-streaming + replay only; streaming without replay (empty AnswerPanel during synth) | Only the hybrid has both panels behaving naturally. TracePanel shows real Sonnet reasoning; AnswerPanel fills in word-by-word. Synthetic replay mirrors the M0-established fake-UX contract. |
| 3 | `CitedCase` carries both `snippet` (400 chars, rerank prompt) and `chunk_text` (~500 words, synthesizer + verification) | Unify on one field; expand snippet to full chunk for rerank too; re-read `data/cases/<ecli>.xml` at synth time | Rerank prompt budget (20 × snippet ≈ 3kT) and synthesizer budget (3 × chunk ≈ 2kT) have distinct shapes; conflating them either inflates rerank or starves synthesizer. Re-reading XML adds a disk dependency with no benefit. |
| 4 | `WetArtikelCitation` carries both `article_id` and `bwb_id`, both closed-set enums | Keep `bwb_id` only (spec-faithful); replace `bwb_id` with `article_id` | `article_id` gives unambiguous post-hoc resolution (quote must appear in the specific article, not any article in the BWB). Additive change keeps frontend `CitationLink` unchanged. |
| 5 | Quote verification = NFC + whitespace-normalized + case-sensitive strict substring; 40–500 char bounds | Fuzzy (Levenshtein); strict byte match; case-insensitive; wider bounds | Preserves "verbatim" claim while tolerating reformatting. Bounds keep citations substantive without enabling "quote the whole article." |
| 6 | Decomposer mirrors synthesizer/rerank regen policy (one regen then hard-fail) | Zero regen (trust schema); deterministic fallback | Consistent pattern across the three forced-tool agents. Extra Haiku call on rare failure is cheap. Silent fallback contradicts M3b decision #5 (loud demo failure beats silent degradation). |
| 7 | Both `article_id` and `bwb_id` get closed-set enums (redundant) | Enum `article_id` only, derive `bwb_id` post-call | Belt-and-braces; blocks the model from mixing a valid `article_id` with a mismatched `bwb_id`. Costs nothing at schema-size; catches a pathological output shape. |
| 8 | Agent + pure-helper split for synthesizer, single-file for decomposer | Single-file for both; tools helper for both | Synthesizer has genuine sync helpers (schema, user message, verify) worth unit-testing without Anthropic mocks. Decomposer has one such helper (tool schema) too small to justify a module boundary. |
| 9 | Hardcoded quote-length bounds (40/500) | Env-var-configurable | Part of the grounding narrative, not ops config. Changing bounds would change the spec, not a runtime knob. |
| 10 | Synthesizer uses `messages.stream()` even though the tool-input itself isn't user-presentable | `messages.create()` (simpler) | Only `messages.stream()` lets pre-tool prose flow live. The tool-input is extracted via `get_final_message()`; the streaming is purely for `agent_thinking`. |
| 11 | `verify_citations` returns `FailedCitation(reason="unknown_id")` on out-of-set IDs instead of `KeyError` | Raise `KeyError` and let the agent catch it | Turns an invariant-violation into a regen-compatible signal. The grounding guard test relies on this shape. |
| 12 | Regen between attempts does not emit an `agent_thinking` separator | Emit a sentinel `agent_thinking` like "(retrying with advisory)" | Keeps the event stream honest: both attempts' prose is real Sonnet output. WARNING in server logs marks the regen for debugging. |

---

*End of spec.*
