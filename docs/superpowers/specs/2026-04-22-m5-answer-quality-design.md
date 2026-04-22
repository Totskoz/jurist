# M5 — Answer Quality + Graceful Refusal — Design

**Date:** 2026-04-22
**Status:** Approved. Implementation not yet started.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§5.1, §5.3, §5.4, §6.3, §11)
**Drives from:** `docs/discussions.md` §"M4 post-eval — external-review pass"
**Siblings:** `docs/superpowers/specs/2026-04-22-m4-decomposer-synthesizer-design.md`, `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md`, `docs/superpowers/specs/2026-04-21-m3b-case-retriever-design.md`
**Branch:** `m5-answer-quality`

---

## 1. Context and goals

M4 landed the full real-LLM agent chain with closed-set citation grounding. An
external-review pass (Claude + Gemini, fed one rendered answer) exposed four
answer-quality defects that the mechanical eval did not catch. See
`docs/discussions.md` §"M4 post-eval — external-review pass" for the full
triage. The three findings that are in-M5-scope are:

- **AQ1 — Procedure-routing muddle.** Synth stacks beding-route (7:248 lid 4 →
  Huurcommissie 4 mnd na ingang) and voorstel-route (7:253 bezwaar vóór
  ingang) as sequential steps in the `aanbeveling`, though they apply to
  mutually exclusive huurtypes.
- **AQ2 — EU-directive escalation blind spot.** Retrieved
  Rotterdam/Amsterdam rulings explicitly apply Richtlijn 93/13/EEG to
  conclude *algehele vernietiging*, but the synth only echoes the statutory
  *nietig voor het meerdere*. Material consumer-law consequence lost between
  retrieval and prose.
- **AQ3 — HR coverage gap.** Reviewer cited ECLI:NL:HR:2024:1780 as an
  important late-2024 HR arrest; we have 33 distinct HR ECLIs in
  `cases.lance` but not this one. Unknown whether 1780 exists (reviewer
  recollection unverified) — but the near-misses (1663, 1709, 1761, 1763 are
  indexed, 1780 is not) suggest the fence + subject filter is too tight.

Plus a fourth, generalisable finding added during brainstorming:

- **AQ8 — Graceful refusal.** System is corpus-scoped to huurrecht but its
  behaviour is not — on a non-huur question today the forced-tool synthesizer
  will still produce an answer over weak grounding. We want the pipeline to
  emit a *structured refusal* when retrievers signal low grounding OR the
  synthesizer judges retrieved material insufficient.

M5 also ships the first multi-question **eval suite** — the single-question
eval harness from M4 grows into a question manifest + rollup doc, so
before/after measurement is reproducible on any branch.

**Done when** (inherits parent §11 + this spec's §11):

1. Parent-spec amendment commit landed on the branch (§10 of this doc).
2. `DecomposerOut` carries `huurtype_hypothese`; synth prompt branches on it
   (AQ1) and escalates on EU-directive signals (AQ2).
3. `StatuteOut` and `CaseRetrieverOut` carry a `low_confidence: bool` flag;
   `StructuredAnswer` carries `kind: Literal["answer","insufficient_context"]`;
   synth emits `kind="insufficient_context"` when both retrievers flag low
   confidence, or when it judges grounding insufficient (AQ8).
4. Fence expansion and priority-ECLI top-up landed; `cases.lance` gains ≥5
   HR ECLIs with huur signal; an audit record documents whether
   ECLI:NL:HR:2024:1780 exists on rechtspraak.nl and whether it was
   recovered.
5. Eval suite at `scripts/eval_suite.py` runs a 5-question manifest; M5-pre
   and M5-post eval docs committed to `docs/evaluations/`; post doc shows
   the three required deltas (no procedure-stacking; EU mention when
   triggered; refusal on out-of-scope).
6. Frontend renders `kind="insufficient_context"` as a distinct state (no
   citation tables, reason banner).
7. `uv run pytest -v` green. `RUN_E2E=1 uv run pytest tests/integration/...`
   green. `uv run ruff check .` clean.
8. Parent spec amended; CLAUDE.md state table updated.

**In scope.** Two pydantic-schema extensions (`StructuredAnswer.kind`,
`huurtype_hypothese`). Two retriever-output extensions (`low_confidence`). Two
new synth prompt rules (AQ1, AQ2) plus one tool-schema extension (the `kind`
enum and refusal-mode field constraints). One ingest flag pair
(`--priority-eclis`, `--refilter-cache`). One fence-term expansion. One
curated priority-ECLI list (live-audit-generated). One eval-harness rewrite
(single-question → manifest-driven). One frontend refusal-state component.
Parent-spec amendment (§5.1/5.3/5.4/6.3/11/15).

**Out of scope.** Validator (still stub). AQ4 temporal corpus freshness. AQ5
ministeriële regeling ingest. AQ6 attributive-quote provenance. AQ7 direct
variability reduction. Opus routing. Multi-rechtsgebied. KG ingest changes.
SSE transport changes.

## 2. Architecture

### 2.1 Pipeline (mostly unchanged)

Orchestrator still chains decomposer → statute_retriever → case_retriever →
synthesizer → validator_stub on one asyncio task. M5 changes **payloads**
between stages and a few **prompts**; sequencing and the event protocol are
unchanged except for one new terminal-answer shape (§3.1).

Event flow on a refusal run (new):

```
run_started
  → decomposer (agent_started, agent_finished{DecomposerOut with huurtype_hypothese})
  → statute_retriever (... agent_finished{StatuteOut with low_confidence=True})
  → case_retriever (... agent_finished{CaseRetrieverOut with low_confidence=True})
  → synthesizer (agent_started, [0 citation_resolved],
                 answer_delta × short refusal prose, agent_finished)
  → validator_stub (... agent_finished{valid=true})
run_finished{final_answer: StructuredAnswer(kind="insufficient_context", ...)}
```

The refusal path is terminal via `run_finished` (with a refusal-kind answer) —
not `run_failed`. Hard failures (LLM errors, rerank collapse, citation
grounding persistent failure) still go through `run_failed`.

### 2.2 File map

**Added:**
- `src/jurist/ingest/priority_eclis.py` — pure helpers for loading a
  newline-separated ECLI file, de-duplicating against existing index, driving
  the 4-stage subset (fetch → parse → chunk → embed → write) for the
  priority set. Reuses existing fetchers; no new network code.
- `scripts/audit_hr_coverage.py` — one-shot live audit against
  rechtspraak.nl: lists late-2024 HR ECLIs with huur signal, diffs against
  current `cases.lance`, writes findings to
  `docs/evaluations/2026-04-22-m5-hr-audit.md` and populates
  `data/priority_eclis/huurrecht.txt`. Includes the live verification of
  reviewer-claimed ECLI:NL:HR:2024:1780 (exists or not; output fact written
  to audit doc).
- `data/priority_eclis/huurrecht.txt` — curated list, generated by the audit
  script above. Committed to git so ingest is reproducible.
- `scripts/eval_suite.py` — manifest-driven eval harness; replaces
  `scripts/eval_m4_run.py` (which is deleted).
- `tests/eval/questions.yaml` — M5 test-question manifest (§7).
- `src/jurist/agents/synthesizer_refusal.py` — pure helpers for the
  refusal path: `should_refuse(statute_out, case_out, synth_judgment) →
  bool`, `build_refusal_advisory(...)`, domain-fallback strings.
- `tests/agents/test_synthesizer_refusal.py` — unit tests for the helpers.
- `tests/agents/test_decomposer_huurtype.py` — unit tests for
  `huurtype_hypothese` classification.
- `tests/ingest/test_priority_eclis.py` — unit tests for the priority-list
  ingest helper.
- `tests/integration/test_m5_e2e.py` — RUN_E2E-gated; locked question
  post-M5 assertions (branching, no stacking, AQ2 mention).
- `tests/integration/test_m5_out_of_scope_e2e.py` — RUN_E2E-gated;
  burenrecht / autoverzekering questions → refusal.
- `docs/evaluations/2026-04-22-m5-suite-pre.md` — pre-merge baseline.
- `docs/evaluations/2026-04-22-m5-suite-post.md` — post-merge result.
- `docs/evaluations/2026-04-22-m5-hr-audit.md` — written by the audit
  script.

**Modified:**
- `src/jurist/schemas.py`:
  - `DecomposerOut` gains `huurtype_hypothese: Literal["sociale","middeldure","vrije","onbekend"]`.
  - `StatuteOut` gains `low_confidence: bool = False`.
  - `CaseRetrieverOut` gains `low_confidence: bool = False`.
  - `StructuredAnswer` gains `kind: Literal["answer","insufficient_context"]`
    and `insufficient_context_reason: str | None = None`.
  - Pydantic validator on `StructuredAnswer`: if
    `kind=="insufficient_context"` then `insufficient_context_reason` must be
    non-empty; conversely `kind=="answer"` implies
    `insufficient_context_reason is None`. Wetsartikelen/uitspraken lists
    may be empty iff `kind=="insufficient_context"`.
- `src/jurist/agents/decomposer.py` — emits the new field; prompt classifies.
- `src/jurist/llm/prompts.py::render_decomposer_system()` — adds huurtype
  classification rules to the Dutch prompt.
- `src/jurist/agents/decomposer.py` tool schema — extends
  `emit_decomposition` with the `huurtype_hypothese` enum property.
- `src/jurist/agents/statute_retriever.py` — sets `low_confidence=True` on
  `StatuteOut` when `done.selected` length `< 3`. No prompt change.
- `src/jurist/agents/case_retriever.py` — sets `low_confidence=True` when
  all top-3 post-rerank similarities are `< settings.case_similarity_floor`
  (default `0.55`). Distinct from the existing `RerankFailedError` hard-fail
  (which applies when `<3` unique ECLIs come back from LanceDB at all;
  unchanged).
- `src/jurist/agents/synthesizer.py` — refactored control flow:
  1. Early-branch: if `stat.low_confidence and case.low_confidence` →
     call refusal path (skip normal synth).
  2. Normal path: forced-tool call to `emit_answer` (tool schema now
     includes `kind` enum); on `kind=="insufficient_context"` returned,
     skip `verify_citations` and skip the synthetic `answer_delta`
     replay of explanations (replay korte_conclusie + reason +
     aanbeveling only). On `kind=="answer"`, existing flow.
- `src/jurist/llm/prompts/synthesizer.system.md` — adds AQ1 routing rule,
  AQ2 escalation rule, AQ8 refusal rule. Dutch.
- `src/jurist/agents/synthesizer_tools.py`:
  - `build_synthesis_tool_schema` accepts `allow_refusal: bool = True`;
    when True, adds `kind` and `insufficient_context_reason` properties
    with appropriate `anyOf` / conditional `required`.
  - `verify_citations` becomes a no-op (returns `[]`) when
    `answer.kind == "insufficient_context"`.
  - New `build_refusal_synthesis_corpus_block(question, domain="huurrecht")` —
    used by the early-branch refusal path (no corpus content to cite).
- `src/jurist/ingest/caselaw_profiles.py` — huurrecht fence expanded from
  `{huur, verhuur, woonruimte, huurcommissie}` to add `{huurverhoging,
  huurprijs, indexering, "oneerlijk beding", "onredelijk beding"}`.
- `src/jurist/ingest/caselaw.py`:
  - Adds `--priority-eclis <path>` flag → delegates to
    `priority_eclis.run_priority_ingest(...)`.
  - Adds `--refilter-cache` flag → skips list + fetch; re-runs stages 6-9
    over XML files already in `data/cases/*.xml`.
- `src/jurist/config.py` — adds `case_similarity_floor: float = 0.55`
  (env: `JURIST_CASE_SIMILARITY_FLOOR`).
- `src/jurist/api/orchestrator.py` — no control-flow change. The refusal
  path still terminates via the normal `agent_finished` → `run_finished`
  arc (refusal is data, not control).
- `src/jurist/fakes.py::FAKE_DECOMPOSER_OUT` — adds `huurtype_hypothese:
  "onbekend"` so existing fakes validate.
- `src/jurist/fakes.py::FAKE_ANSWER` — adds `kind: "answer",
  insufficient_context_reason: None`.
- `tests/test_schemas.py` — extended with `StructuredAnswer.kind`
  round-trip + root-validator tests, and `DecomposerOut.huurtype_hypothese`
  round-trip tests.
- `web/src/components/AnswerPanel.tsx` — renders refusal variant.
- `web/src/state/runStore.ts` — no state change (the refusal is a shape
  variant of `finalAnswer`, not a new field).
- `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` — §10 amendments.
- `.env.example` — documents `JURIST_CASE_SIMILARITY_FLOOR`.
- `CLAUDE.md` — reflects M5 behaviour.

**Deleted:**
- `scripts/eval_m4_run.py` — replaced by the manifest-driven harness.

**Unchanged.** KG ingestion, Embedder, LanceDB schema, `MockAnthropicClient`
and `MockStreamingClient`, the orchestrator's error-mapping, the statute
retriever's tool-use loop, `EventBuffer`, SSE transport, KGPanel, TracePanel,
CitationLink, runStore reducers (except shape inference on `finalAnswer`).

### 2.3 Concurrency

Unchanged. Single asyncio task. Refusal path is synchronous within the
synthesizer run; no new threads.

### 2.4 No new exception types

Refusal is normal data. The existing `CitationGroundingFailedError`,
`DecomposerFailedError`, `RerankFailedError` hierarchy covers the hard-fail
cases. AQ8 explicitly avoids adding a fourth.

## 3. StructuredAnswer — discriminated refusal

### 3.1 Schema

```python
class StructuredAnswer(BaseModel):
    kind: Literal["answer", "insufficient_context"]
    korte_conclusie: str = Field(..., min_length=40, max_length=2000)
    relevante_wetsartikelen: list[WetArtikelCitation] = Field(default_factory=list)
    vergelijkbare_uitspraken: list[UitspraakCitation]  = Field(default_factory=list)
    aanbeveling: str = Field(..., min_length=40, max_length=2000)
    insufficient_context_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _kind_matches_shape(self) -> "StructuredAnswer":
        if self.kind == "answer":
            if self.insufficient_context_reason is not None:
                raise ValueError("insufficient_context_reason must be None when kind='answer'")
            if not self.relevante_wetsartikelen:
                raise ValueError("relevante_wetsartikelen must be non-empty when kind='answer'")
            if not self.vergelijkbare_uitspraken:
                raise ValueError("vergelijkbare_uitspraken must be non-empty when kind='answer'")
        else:  # kind == "insufficient_context"
            if not self.insufficient_context_reason:
                raise ValueError("insufficient_context_reason required when kind='insufficient_context'")
            # Citation lists may be empty; if non-empty, still require schema validity.
        return self
```

The root validator enforces the invariant: `kind=="answer"` keeps M4's
existing requirements (non-empty citation lists); `kind=="insufficient_context"`
relaxes them and requires a reason string instead.

### 3.2 Refusal reason — shape

Free-text Dutch, 40-1000 chars. Typical structure (enforced by prompt, not
schema):

```
De vraag valt (grotendeels) buiten het bereik van dit systeem.
Gezocht in: huurrecht-corpus (BW Boek 7 Titeldeel 4, Uhw, rechtspraak 2023-).
Niet gevonden: directe bronnen over <domein>.
Suggest: <arbeidsrecht | verzekeringsrecht | burenrecht | ...>.
```

Prompt rules enforce the "gezocht / niet gevonden / suggest" structure;
the synth prompt owns the exact phrasing. The suggestion list is
hard-coded in the prompt (`arbeidsrecht`, `verzekeringsrecht`,
`burenrecht`, `consumentenrecht`, `familierecht`, `algemeen`
fallback) — closed set, no free generation of imaginary specialisms.

## 4. Decomposer changes (AQ1 signal)

### 4.1 Schema

```python
class DecomposerOut(BaseModel):
    sub_questions: list[str] = Field(..., min_length=1, max_length=5)
    concepts: list[str]      = Field(..., min_length=1, max_length=10)
    intent: Literal["legality_check", "calculation", "procedure", "other"]
    huurtype_hypothese: Literal["sociale", "middeldure", "vrije", "onbekend"]
```

### 4.2 Tool schema

Adds one property:
```python
"huurtype_hypothese": {
    "type": "string",
    "enum": ["sociale", "middeldure", "vrije", "onbekend"],
},
```
to the existing `emit_decomposition` tool. Added to `required`.

### 4.3 Prompt extension

Appended to the existing Dutch decomposer system prompt:

```
Classificeer huurtype_hypothese op basis van signaalwoorden in de vraag:
- "sociale" / "sociale huurwoning" / "gereguleerde huur" / "corporatiewoning" → "sociale"
- "middeldure huur" / "middenhuur" / "middensegment" → "middeldure"
- "vrije sector" / "geliberaliseerde huur" / "particuliere huurmarkt" → "vrije"
- Geen expliciet signaal → "onbekend"
Bij twijfel: "onbekend". Classificeer niet op basis van impliciete
aannames over huurprijs.
```

### 4.4 Tests

- Happy-path: one test per enum value, with a question carrying the expected
  signal word (e.g. "sociale huurwoning" → `sociale`).
- Ambiguous question ("Mijn verhuurder wil 15% verhogen, mag dat?") →
  `onbekend`.
- Prompt stability: the classification rules block is present in the rendered
  system prompt.

## 5. Retriever low-confidence signals

### 5.1 StatuteOut

```python
class StatuteOut(BaseModel):
    ...  # existing fields unchanged
    low_confidence: bool = False
```

Set to `True` when `done.selected` has fewer than 3 `CitedArticle`s. Captures
the "model gave up finding material" pattern. No prompt change to the statute
retriever; the signal is a post-loop derivation in `statute_retriever.run`.

### 5.2 CaseRetrieverOut

```python
class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]
    low_confidence: bool = False
```

Set to `True` when the final `cited_cases` has length `>= 3` but all three
cases' `similarity` is `< settings.case_similarity_floor` (default `0.55`
on bge-m3 cosine).

The existing hard-fail path (`<3` unique ECLIs from LanceDB top-150 dedupe →
`RerankFailedError` → `run_failed{reason:"case_rerank"}`) is unchanged. That
failure is corpus-structural; `low_confidence=True` is retrieval-weak. Two
distinct signals for two distinct classes of insufficient grounding.

### 5.3 Threshold rationale

The 0.55 floor was chosen after reading M4 eval numbers: on the locked
question, all three reranked cases scored 0.71 cosine (well above 0.55) and
all six candidates in the top-20 scored above 0.60. On an out-of-scope
question, bge-m3 still returns nearest cosine neighbors, but those distances
spread into the 0.3-0.5 band. 0.55 is conservative — it will not trip on
genuine on-topic questions; it will trip on clearly off-topic ones. Made
env-configurable (`JURIST_CASE_SIMILARITY_FLOOR`) so future eval data can
retune without a code change.

### 5.4 Tests

- `statute_retriever.run` emits `StatuteOut(low_confidence=True)` when
  MockAnthropic is scripted to produce `done` with 1 or 2 articles; `False`
  with 3+.
- `case_retriever.run` emits `CaseRetrieverOut(low_confidence=True)` when
  all three reranked picks have similarity `< 0.55`; `False` when at least
  one is `>= 0.55`. Threshold read from `settings.case_similarity_floor`
  (tests monkeypatch to verify env-wire-up).

## 6. Synthesizer changes

The load-bearing work. Three distinct rule additions on the happy path, one
refusal branch.

### 6.1 Control flow

```python
async def run(input: SynthesizerIn, *, ctx: RunContext) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    # AQ8 — early-branch refusal
    if should_refuse(input.statute_out, input.case_out):
        # Streaming LLM call with a refusal-only prompt variant; no corpus,
        # no tool_choice enum for citation fields.
        refusal = await _stream_refusal(ctx.llm, input.question,
                                        input.statute_out, input.case_out)
        yield from _emit_refusal_events(refusal)
        yield TraceEvent(type="agent_finished",
                         data=SynthesizerOut(answer=refusal).model_dump())
        return

    # Normal path — AQ1 + AQ2 rules live in the system prompt; the
    # synth itself may still emit kind="insufficient_context" if it judges
    # the material insufficient despite retriever confidence.
    # ... existing M4 flow ...
```

### 6.2 `should_refuse` (pure helper, `synthesizer_refusal.py`)

```python
def should_refuse(stat: StatuteOut, case: CaseRetrieverOut) -> bool:
    return stat.low_confidence and case.low_confidence
```

Both must trip. A strong statute match with weak cases (or vice versa) stays
on the normal path — the synth sees the full corpus and can still produce an
answer. Refusal is the conjunction.

### 6.3 System prompt — three new rules

Appended to `synthesizer.system.md`:

```
## AQ1 — Procedure-routing per huurtype
Je ontvangt `huurtype_hypothese` ∈ {sociale, middeldure, vrije, onbekend}
in het vraagblok. In het `aanbeveling`-veld:
- "sociale": geef UITSLUITEND de sociale-sector-procedure (bezwaar vóór
  ingangsdatum; daarna Huurcommissie-toetsing op aanzegging van verhuurder
  via art. 7:253 BW).
- "middeldure": geef UITSLUITEND de middeldure-sector-procedure
  (Huurcommissie-verzoek binnen 4 maanden na ingangsdatum; art. 7:248 lid 4).
- "vrije": geef UITSLUITEND de vrije-sector-procedure (onderhandeling /
  kantonrechter; beperkte Huurcommissie-rol).
- "onbekend": presenteer BEIDE routes expliciet ALS ALTERNATIEVEN, niet
  als stapelbare stappen. Begin met een als-dan-structuur.

Stapel NOOIT art. 7:248 lid 4 en art. 7:253 in één procedureketen.

## AQ2 — EU-richtlijn-escalatie
Als een geciteerde uitspraak in `chunk_text` expliciet Richtlijn 93/13/EEG,
"oneerlijk beding", of "algehele vernietiging" toepast: vermeld in
`korte_conclusie` het gevolg "algehele vernietiging van het beding" als
mogelijkheid naast de statutaire "nietig voor het meerdere". Noteer in
`aanbeveling` de consumenten-route als optie voor huurders die een
professionele verhuurder tegenover zich hebben.

## AQ8 — Onvoldoende context
Als je oordeelt dat de meegeleverde wetsartikelen en uitspraken samen de
vraag niet substantieel kunnen onderbouwen — ook niet na goed lezen van
elk fragment — roep dan `emit_answer` aan met `kind="insufficient_context"`.
Vul `insufficient_context_reason` met: wat er is gezocht (bijv.
"huurrecht-corpus: BW Boek 7 Titel 4, Uhw, rechtspraak 2023-"), wat er
ontbreekt, en naar welk specialisme (uit {arbeidsrecht, verzekeringsrecht,
burenrecht, consumentenrecht, familierecht}) je zou verwijzen. Laat
`relevante_wetsartikelen` en `vergelijkbare_uitspraken` leeg. Geef een
korte `korte_conclusie` en een `aanbeveling` die de gebruiker naar een
geschikter kanaal stuurt.
```

### 6.4 Tool schema extension

`build_synthesis_tool_schema(article_ids, bwb_ids, eclis, *, allow_refusal=True)`:

- Adds `kind` to properties with `enum: ["answer", "insufficient_context"]`.
- Adds `insufficient_context_reason` as nullable string.
- Uses JSON-Schema `if / then / else`:
  ```json
  "if": {"properties": {"kind": {"const": "answer"}}},
  "then": {"required": ["relevante_wetsartikelen",
                        "vergelijkbare_uitspraken"]},
  "else": {"required": ["insufficient_context_reason"]}
  ```
- `required` at top level: `["kind", "korte_conclusie", "aanbeveling"]`.

The per-request `enum` on `article_id`/`bwb_id`/`ecli` stays; it only binds
**if** the answer emits citations. On a refusal the lists are empty so the
enum is vacuous.

### 6.5 Refusal LLM call variant

For the early-branch refusal (both retrievers flagged), the synth fires a
single Sonnet call with:
- A shorter system prompt (refusal-only template, no citation schema).
- A user message with just the question + the refusal-domain guidance.
- `tool_choice={"type":"tool","name":"emit_answer"}` still; but the tool
  schema is the **refusal variant** (lists not required; `kind` fixed to
  `"insufficient_context"` via the `enum: ["insufficient_context"]` only).

This keeps the streaming `answer_delta` replay mechanism intact — the
frontend sees a short Dutch refusal stream just like it sees a short Dutch
conclusion.

### 6.6 Post-hoc verification

`verify_citations` gets a one-line early-return:

```python
def verify_citations(answer, ...):
    if answer.kind == "insufficient_context":
        return []   # nothing to verify
    # ... existing body ...
```

On the happy path this is unreachable (lists are empty) but defensive.

### 6.7 Events

Refusal-kind run emits:
- `agent_started`
- (`agent_thinking` × short, if Sonnet pre-reasons)
- `answer_delta` × ~100-200 (refusal prose is shorter than a full answer)
- `agent_finished{SynthesizerOut(answer=StructuredAnswer(kind="insufficient_context", ...))}`
- No `citation_resolved` events.

Answer-kind run emits the M4 shape unchanged.

### 6.8 Tests

- `should_refuse` truth table: 4 combinations of `low_confidence`.
- Tool-schema conditional: `kind="answer"` input requires lists,
  `kind="insufficient_context"` input requires reason.
- Synth agent, early-branch: MockAnthropic scripted to produce a
  `kind="insufficient_context"` tool output; verify no
  `citation_resolved`, verify `answer_delta` replay matches
  `korte_conclusie + reason + aanbeveling`.
- Synth agent, normal path → self-judged refusal: scripted to produce
  `kind="insufficient_context"` despite retrievers being confident; verify
  `verify_citations` still bypassed; verify `run_finished` (not
  `run_failed`).
- Grounding unaffected on happy path: existing tests pass unchanged.

## 7. Eval suite

### 7.1 Manifest

`tests/eval/questions.yaml`:

```yaml
- id: Q1
  question: Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?
  expect_kind: answer
  assertions:
    - decomposer.huurtype_hypothese == "onbekend"
    - aanbeveling matches regex "Als .+ (is|betreft):.+Als .+:"
    - if any(c.chunk_text contains "Richtlijn 93/13" for c in cited_cases):
        korte_conclusie contains "algehele vernietiging" or aanbeveling contains "oneerlijk beding"

- id: Q2
  question: Mijn sociale huurwoning kreeg per 1 juli een verhoging van 10%, kan dat?
  expect_kind: answer
  assertions:
    - decomposer.huurtype_hypothese == "sociale"
    - aanbeveling does not contain "vrije sector"
    - aanbeveling references "art. 7:253" or "huurcommissie"

- id: Q3
  question: Ik heb een conflict met mijn buurman over geluidsoverlast, wat zijn mijn opties?
  expect_kind: insufficient_context
  assertions:
    - insufficient_context_reason contains "huurrecht"
    - aanbeveling contains "burenrecht"

- id: Q4
  question: Mijn auto is stuk, moet de autoverzekering de reparatie dekken?
  expect_kind: insufficient_context
  assertions:
    - insufficient_context_reason mentions scope
    - aanbeveling contains one of "verzekeringsrecht", "consumentenrecht"

- id: Q5
  question: Kan ik een huurverhoging aanvechten als het beding in mijn contract vaag is geformuleerd?
  expect_kind: answer
  assertions:
    - len(cited_cases) >= 1
    - korte_conclusie contains "oneerlijk beding" or "Richtlijn 93/13" or "algehele vernietiging"
```

### 7.2 Harness

`scripts/eval_suite.py`:
- Loads the manifest.
- For each question, runs the full pipeline via the same entry point as
  the API (`run_question`), drains events, assembles a per-question
  summary (kind, wall time, event count, final answer shape, pass/fail per
  assertion).
- Writes per-question artifacts to `out/m5-eval/{id}/{trace.jsonl, answer.md, summary.json}`.
- Writes a suite rollup to `docs/evaluations/2026-04-22-m5-suite-{pre,post}.md`.
- Exit code: 0 if all assertions pass and all expect_kind match; else non-zero.

### 7.3 Assertion DSL

The manifest's `assertions` are Python-expression strings with a small
allowed namespace (`answer`, `decomposer`, `cited_cases`, `re.search`,
helpers like `contains`). Implementation: a sandboxed `eval()` with
`__builtins__: {}`. Not a production-grade DSL — this is interview-scope.

### 7.4 Pre-vs-post discipline

**Pre-merge:** Run the suite on `master` (the M4 branch). Commit
`docs/evaluations/2026-04-22-m5-suite-pre.md`. This freezes the baseline.

**Post-merge (M5):** Run on the M5 branch. Commit
`docs/evaluations/2026-04-22-m5-suite-post.md`. Diff the two:
- Q1 pre has stacked procedure → Q1 post has branching.
- Q1 post may have Richtlijn 93/13 mention (subject to retrieval).
- Q2 is a new question; pre will likely produce a confident but wrong
  recommendation (expected); post enforces the sociale-only path.
- Q3/Q4 pre will produce hallucinated-ish answers over thin grounding;
  post refuses cleanly.
- Q5 pre likely cites Rotterdam/Amsterdam but doesn't mention EU; post
  should.

The post doc's opening table contains a side-by-side of pre vs post per
assertion.

## 8. HR coverage — fence + priority list (AQ3)

### 8.1 Fence expansion

`src/jurist/ingest/caselaw_profiles.py`:

```python
"huurrecht": CaselawProfile(
    subject_uri="http://psi.rechtspraak.nl/rechtsgebieden#civielRecht_verbintenissenrecht",
    keyword_terms=[
        "huur", "verhuur", "woonruimte", "huurcommissie",
        # M5 additions:
        "huurverhoging", "huurprijs", "indexering",
        "oneerlijk beding", "onredelijk beding",
    ],
),
```

Multi-word terms use whole-token case-insensitive matching (the fence
already lowercases case-insensitively; the matcher is refactored to accept
multi-word terms via `" ".join(tokens)` contains check on the lowercased
body text).

### 8.2 Priority-ECLI ingest path

`src/jurist/ingest/priority_eclis.py` exposes:

```python
def run_priority_ingest(
    eclis_path: Path,
    lance_path: Path,
    cache_dir: Path,
    embedder: Embedder,
    *,
    skip_fence: bool = True,  # priority ECLIs bypass fence
) -> PriorityIngestResult:
    """Fetch → parse → chunk → embed → write for a curated ECLI list.
    Idempotent via existing (ecli, chunk_idx) dedupe in CaseStore.
    Returns counts: fetched, parsed, chunked, embedded, written."""
```

The 20-30 ECLIs on the priority list run sequentially (no pool; small
volume doesn't need parallelism). Fetching respects the same backoff as
the bulk ingest.

### 8.3 Audit script

`scripts/audit_hr_coverage.py` one-shot:
1. Query rechtspraak.nl for HR decisions modified ≥ 2024-07-01 with
   subject civielRecht_verbintenissenrecht.
2. Fetch + parse each. Apply a broader huur-signal check (the expanded
   fence terms).
3. Diff against current `cases.lance` HR ECLIs.
4. Specifically check: does ECLI:NL:HR:2024:1780 exist on rechtspraak.nl?
   - If 200 OK and valid XML: include in priority list.
   - If 404: write "reviewer-cited ECLI does not exist on rechtspraak.nl"
     to the audit doc and close the item.
5. Write findings to `docs/evaluations/2026-04-22-m5-hr-audit.md`
   (numbers + interpretation).
6. Write the priority list to `data/priority_eclis/huurrecht.txt`.

### 8.4 Refilter-cache mode

`uv run python -m jurist.ingest.caselaw --refilter-cache`:
- Skip list + fetch stages entirely.
- Iterate over `data/cases/*.xml` (the existing parse cache).
- Re-run fence with expanded terms.
- For any ECLI that now passes (previously parsed but previously filtered
  out), run chunk + embed + write.
- Idempotent: existing `(ecli, chunk_idx)` pairs skip.

Expected runtime: ~2-4 hours on the 16GB host (embedding-bound on the delta;
delta should be 10-25% of full corpus — measured via profile before running
the full re-embed). If the delta looks larger than expected, stop and
investigate before committing.

**Operator task, not CI.** `data/lancedb/cases.lance/` is a git-ignored
artefact (the project's fresh-clone bootstrap runs the full ingest). The
refilter-cache run is a **one-time local operation** after the code changes
land. The eval-suite pre/post runs also happen locally. Only the code +
priority list + audit doc + eval summary docs are committed to git.

### 8.5 Verification

After fence expansion + priority top-up:
- `uv run python -m jurist.ingest.caselaw --refilter-cache` runs clean.
- `scripts/audit_hr_coverage.py --verify` reports the distinct HR ECLI
  count in `cases.lance` increased by ≥5.
- The audit doc is committed and readable.

## 9. Frontend (minimal)

`web/src/components/AnswerPanel.tsx` gets a kind-guard:

```tsx
if (finalAnswer.kind === "insufficient_context") {
  return <InsufficientContextBanner
    reason={finalAnswer.insufficient_context_reason}
    korteConclusie={finalAnswer.korte_conclusie}
    aanbeveling={finalAnswer.aanbeveling}
  />
}
// ... existing answer rendering ...
```

`InsufficientContextBanner` shows:
- Dutch header "Geen voldoende bronnen voor deze vraag"
- `korte_conclusie` body
- `insufficient_context_reason` styled differently (muted)
- `aanbeveling` as the call-to-action
- No citation tables, no "bekijk bron" links.

`runStore` unchanged — `finalAnswer` is already of type `StructuredAnswer`;
TypeScript discriminates on `kind`.

No changes to KGPanel or TracePanel. Even on a refusal, the event stream
honestly shows what the pipeline tried.

## 10. Parent-spec amendments

Prepended as Task 0 on the branch. Edits
`docs/superpowers/specs/2026-04-17-jurist-v1-design.md`.

1. **§5.1 Decomposer** — `DecomposerOut` adds `huurtype_hypothese` (enum);
   prompt now classifies.
2. **§5.3 CaseRetriever** — `CaseRetrieverOut` adds `low_confidence: bool`;
   hard-fail path unchanged.
3. **§5.4 Synthesizer** — `StructuredAnswer` adds `kind` +
   `insufficient_context_reason`; three new prompt rules (AQ1, AQ2, AQ8);
   tool schema uses conditional `required`; `verify_citations` no-ops on
   refusal kind.
4. **§5.2 StatuteRetriever** — `StatuteOut` adds `low_confidence: bool`;
   set when `done.selected` length < 3.
5. **§6.3 Event types** — `run_finished.data.final_answer` may carry a
   refusal-kind answer. Frontend discriminates on `kind`.
6. **§11 M5** — new milestone row: "AQ1/AQ2/AQ8 prompt work; AQ3 corpus
   expansion; eval suite."
7. **§13 Configuration** — adds `JURIST_CASE_SIMILARITY_FLOOR` (default
   `0.55`).
8. **§15 Decisions log** — ten new entries (§13 of this doc).

## 11. Testing

### 11.1 Pure-helper tests

- `test_synthesizer_refusal.py`: `should_refuse` truth table;
  `build_refusal_advisory` Dutch output structure.
- `test_synthesizer_tools.py`: schema-with-refusal validates both kinds
  under `if/then/else`; `verify_citations` no-ops on refusal.
- `test_schemas.py`: `StructuredAnswer` root-validator catches:
  `kind="answer"` + empty lists; `kind="insufficient_context"` +
  non-empty reason; serialization round-trip for both kinds.
- `test_priority_eclis.py`: `run_priority_ingest` is idempotent; dedupe
  against existing rows works.
- `test_caselaw_profiles.py`: new fence terms accept previously-rejected
  sample chunks; existing terms still match.

### 11.2 Agent tests

- `test_decomposer_huurtype.py` — four happy-path tests (one per enum
  value), one ambiguous → onbekend, one prompt-stability test.
- `test_statute_retriever.py` (additions) — `low_confidence=True` when
  `done.selected` has 1 or 2 articles; `False` at 3+.
- `test_case_retriever.py` (additions) — `low_confidence=True` when all
  three similarities `< 0.55`; `False` when at least one `>=`.
- `test_synthesizer.py` (additions) — early-branch refusal emits correct
  event sequence; self-judged refusal (retrievers confident but synth
  says insufficient) still terminates via `run_finished`.

### 11.3 Grounding-guard test (existing, extended)

`test_synthesizer_grounding.py` adds an assertion:
- Tool schema with `allow_refusal=True` has both enum-locked citations
  (when `kind="answer"`) AND the refusal-conditional shape.

### 11.4 Integration — RUN_E2E

- `test_m5_e2e.py` — the locked question with M5 code. Assertions:
  - `kind=="answer"`.
  - `huurtype_hypothese=="onbekend"`.
  - `aanbeveling` contains branching ("Als ... Als ...").
  - No procedure-stacking (negative regex on
    "7:248 lid 4.{0,50}7:253" and vice versa).
- `test_m5_out_of_scope_e2e.py` — out-of-scope question (e.g. the
  burenrecht question from Q3). Assertions:
  - `kind=="insufficient_context"`.
  - `insufficient_context_reason` non-empty and contains "huurrecht".
  - Citation lists empty.
  - `run_finished` (not `run_failed`).

### 11.5 Eval suite

`scripts/eval_suite.py` on the manifest is itself a test artifact —
the CI gate (if any) is the post eval doc passing all assertions.

## 12. Configuration

### 12.1 New settings in `config.py`

```python
# M5 — low-confidence threshold
case_similarity_floor: float = float(
    os.getenv("JURIST_CASE_SIMILARITY_FLOOR", "0.55")
)
```

### 12.2 `.env.example`

Adds one-line doc for `JURIST_CASE_SIMILARITY_FLOOR`.

### 12.3 No new deps

All work in existing libraries.

## 13. Decisions log (M5-specific)

| # | Decision | Alternatives | Reason |
|---|---|---|---|
| 1 | Refusal is a `StructuredAnswer.kind` variant, not a new terminal event | New `run_refused` terminal event; `run_failed{reason:"insufficient_context"}` | Refusal is **not** a failure — the pipeline ran correctly and its output is "the system doesn't have enough context." Adding a new terminal event churns the SSE protocol and the frontend state machine; a data variant on the existing `run_finished` is cheaper and more honest. |
| 2 | Both retriever `low_confidence` flags must be True to trip the early-branch refusal | Either flag trips it; weighted combination; synth-only judgment | Early-branch refusal skips the real Sonnet call entirely (cost/latency saving). Requiring both signals means: a strong statute match + weak cases (or vice versa) still reaches the synth, which can decide itself. Avoids refusing too eagerly on borderline questions. |
| 3 | Synth can *also* emit `kind="insufficient_context"` on the normal path | Synth always trusts retrievers; refusal only via early-branch | Gives the synth final authority when the retrieved material looks confident by score but is actually off-topic (a known failure mode of semantic retrieval). Costs nothing extra — just a prompt rule. |
| 4 | Tool schema uses JSON-Schema `if/then/else` for kind-dependent required fields | Two separate tool definitions (`emit_answer` / `emit_refusal`); always-required fields with nullable | Anthropic's tool-use supports draft-2020 JSON-Schema; `if/then/else` keeps one tool name. Two-tool variants require more prompt engineering to route; always-nullable fields lose enum enforcement. |
| 5 | Similarity threshold 0.55 hard-coded-ish default, env-overridable | Adaptive (per-question calibration); higher / lower default | Default value derived from M4 eval distribution; env override is for future retuning without code changes. Adaptive thresholds are out of scope (would need calibration harness). |
| 6 | `huurtype_hypothese` is four-way Literal including `onbekend`, not optional | Optional field; boolean "is sociaal" | Forces the decomposer to classify, rather than silently omit. `onbekend` is honest; a missing field can mean "forgot to emit" or "couldn't classify". Dutch LLMs are known to skip optional fields. |
| 7 | AQ2 EU-escalation is prompt-only, not retrieval-stage | Detect in case retriever and pass an `eu_signal` flag; add a retrieval tag | The signal is in `chunk_text`, which the synth already sees in its user message. A prompt rule has the same effect at zero pipeline-surface cost. If eval data shows prompt compliance < ~80%, revisit (could become a retriever-emitted signal in v2). |
| 8 | Fence expansion + priority list, not a subject-URI broadening | Drop subject filter entirely; switch to `civielRecht` (parent of verbintenissenrecht) | `civielRecht` parent explodes the corpus ~5x with mostly-irrelevant content (contract disputes, aansprakelijkheid). The fence was always the real precision mechanism; expanding *that* is surgically correct. |
| 9 | Priority list is a text file committed to git | Pulled live each ingest; Python literal | Text file is auditable and diff-visible in PRs. Live-pulled would re-introduce the "what exactly did we index" reproducibility hole that AQ3 is trying to close. |
| 10 | Refusal prose goes through the same `answer_delta` replay | Skip the replay; emit a terminal `refusal_delta` event | Preserves the UX contract (TracePanel fills progressively, AnswerPanel has "typing" effect). Refusals should feel like first-class answers, not error screens. |

## 14. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Synth doesn't follow AQ1 branching rule despite prompt | Medium | Integration test asserts regex match for "Als …" structure. If observed compliance < 80%, consider validator enforcement (moves AQ1 to kind="insufficient_context" if stacking detected). |
| Synth doesn't follow AQ2 EU-escalation rule | Medium | Q5 in eval suite is the sentinel. If compliance < 80%, make the case retriever emit an `eu_signal: bool` on `CaseRetrieverOut` (post-hoc grep on chunk_text) and have the synth prompt consume it directly — stronger than relying on the synth to notice. |
| `0.55` threshold too low or too high | Low-Medium | Q1-Q5 eval exercise the distribution. If Q3 passes `low_confidence=False` (case retriever finds nonsense cosine-close matches), raise threshold. Env-configurable. |
| Refusal prose gets verbose and misses the point | Low | System prompt enforces the "gezocht / niet gevonden / suggest" structure and caps `korte_conclusie` at 2000 chars. |
| Refilter-cache misses cases because parse-cache is incomplete | Low | Fall back to re-fetch for any ECLI not in the parse cache. Audit script reports any fetch gap. |
| ECLI:NL:HR:2024:1780 doesn't exist on rechtspraak.nl | Medium | The audit script explicitly verifies. If 404, we write that fact to discussions.md — reviewer hallucination, useful data. |
| Adding AQ1/AQ2/AQ8 together makes the prompt too long → Sonnet behavior degrades | Low | Prompt is ~3KB; Sonnet 4.6 handles ~100x that. Monitor for regression on the M4 e2e tests (which must remain green). |
| Frontend refusal-state component breaks on malformed finalAnswer | Low | TypeScript discriminates on `kind`; exhaustive switch; unit test covers both kinds via Storybook fixture. |

## 15. Acceptance gate

Before merging `m5-answer-quality` to master:

- All new + existing unit tests green under `uv run pytest -v`.
- `RUN_E2E=1 uv run pytest tests/integration/` green for:
  `test_m3b_case_retriever_e2e.py`, `test_m4_e2e.py`, `test_m5_e2e.py`,
  `test_m5_out_of_scope_e2e.py`.
- `uv run ruff check .` clean.
- `scripts/audit_hr_coverage.py` has run; audit doc committed;
  priority list committed.
- `scripts/eval_suite.py` has run on both `master` and the M5 branch;
  both suite docs committed; post-doc diff meets all manifest
  assertions.
- HR ECLI count in `cases.lance` increased by ≥5 distinct ECLIs
  (measured by the audit script).
- CLAUDE.md updated to reflect M5 behaviour (new decomposer field; new
  synth prompt rules; refusal path; eval suite).
- Parent spec amended (§10 of this doc).

---

*End of spec.*
