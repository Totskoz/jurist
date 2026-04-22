# M5 — Answer Quality + Graceful Refusal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address three M4-review findings (AQ1 procedure-muddle, AQ2 EU-directive blind spot, AQ3 HR coverage gap) plus AQ8 graceful refusal. Add a manifest-driven eval suite. The full pipeline now (a) classifies huurtype and branches procedure recommendations on it, (b) escalates consumer-directive reasoning from retrieved cases, (c) refuses cleanly when retrieval signals insufficient grounding, and (d) has broader huur case coverage via fence expansion + a curated priority-ECLI top-up.

**Architecture:** Three closed-set additions: `DecomposerOut.huurtype_hypothese` (enum); `StatuteOut.low_confidence` + `CaseRetrieverOut.low_confidence` (booleans); `StructuredAnswer.kind ∈ {answer, insufficient_context}` (discriminated). Synthesizer gains three prompt rules (AQ1 routing, AQ2 escalation, AQ8 refusal) and an early-branch refusal path when both retrievers flag low confidence. Tool-schema uses JSON-Schema `if/then/else` for kind-dependent required fields. Fence expansion + `--priority-eclis` / `--refilter-cache` CLI flags let the existing ingest pipeline add missing HR arrests without re-fetching 19k XMLs. Eval harness reads a 5-question YAML manifest and writes pre/post rollup docs.

**Tech Stack:** Python 3.11, `anthropic` AsyncClient, `pydantic` v2, `lancedb`, `sentence-transformers` bge-m3, `pytest` + `pytest-asyncio`, `PyYAML` (already transitively installed). React + Zustand on the web side. No new runtime dependencies.

**Authoritative spec:** `docs/superpowers/specs/2026-04-22-m5-answer-quality-design.md`. When a task references a rule ("per §6.3"), read that section first — the spec is the source of truth for WHAT; this plan is HOW. Companion context lives in `docs/discussions.md` §"M4 post-eval — external-review pass".

**Preflight:**
- Working tree clean on `master`. M5 design spec already committed; parent-spec amendment is Task 0.
- `ANTHROPIC_API_KEY` in `.env` or the environment for Tasks 17, 21, 22, and the operator tasks (23-25). Unit tests run offline.
- `data/kg/huurrecht.json` (from M1) and `data/lancedb/cases.lance` (from M3a) must exist for the integration + operator tasks.
- bge-m3 already cached from M3a; no fresh download.
- `data/cases/*.xml` parse cache must exist for Task 24's `--refilter-cache` run. Check with `ls data/cases/ | head` — if empty, the original M3a ingest must be re-run first (not in M5 scope).
- Environment quirks: `uv` at `C:\Users\totti\.local\bin`; may need `export PATH="/c/Users/totti/.local/bin:$PATH"`. API port is 8766. Git LF→CRLF warnings are benign.

**Conventions:**
- One task ≈ one commit. Commit at the end after tests + `uv run ruff check .` pass.
- Test-first: failing test → see fail → implement → see pass → commit.
- `tests/fixtures/mock_llm.py` is the house mock convention; extend, don't parallel.
- Do NOT use `--no-verify` or bypass hooks. Fix the underlying issue and re-commit.
- Tasks 23-25 are **operator-local**: run the command, commit the output artefact. They land after all code tasks are green on the branch.

---

## Task 0: Amend parent spec for M5

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`

Prerequisite commit. Documents the schema additions (`huurtype_hypothese`, the two `low_confidence` flags, `kind` on `StructuredAnswer`), the new synthesizer prompt rules, the one new env var, and ten decision-log entries. Mirrors the M4 Task 0 cadence.

- [ ] **Step 1: Append huurtype field to §5.1 Decomposer schema**

Find the current `DecomposerOut` definition and replace with:

```python
class DecomposerOut(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: Literal["legality_check", "calculation", "procedure", "other"]
    huurtype_hypothese: Literal["sociale", "middeldure", "vrije", "onbekend"]  # M5: segment classification
```

Append after the existing **Implementation** paragraph of §5.1:

```markdown
M5 adds `huurtype_hypothese` so the synthesizer can present segment-specific procedure recommendations (AQ1). Prompt classifies on signal words; ambiguous → `"onbekend"`.
```

- [ ] **Step 2: Add `low_confidence` to §5.2 StatuteRetriever**

Find the current `StatuteOut` definition and replace with:

```python
class StatuteOut(BaseModel):
    cited_articles: list[CitedArticle]
    low_confidence: bool = False  # M5: True when <3 articles selected
```

Append after the existing **Implementation** paragraph:

```markdown
M5 derives `low_confidence = len(done.selected) < 3` post-loop. Feeds the synthesizer's early-branch refusal decision (AQ8).
```

- [ ] **Step 3: Add `low_confidence` to §5.3 CaseRetriever**

Find the current `CaseRetrieverOut` definition and replace with:

```python
class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]
    low_confidence: bool = False  # M5: True when all top-3 similarity < 0.55
```

Append after the existing **Implementation** paragraph:

```markdown
M5 sets `low_confidence = True` when the three reranked picks all have similarity `< settings.case_similarity_floor` (default `0.55`). Distinct from the existing `RerankFailedError` hard-fail (which still fires when `<3` unique ECLIs come back from LanceDB at all). Feeds AQ8.
```

- [ ] **Step 4: Rewrite §5.4 StructuredAnswer with kind discriminator**

Find `class StructuredAnswer` and replace with:

```python
class StructuredAnswer(BaseModel):
    kind: Literal["answer", "insufficient_context"]  # M5
    korte_conclusie: str                    # 40–2000 chars
    relevante_wetsartikelen: list[WetArtikelCitation]   # may be [] iff kind=="insufficient_context"
    vergelijkbare_uitspraken: list[UitspraakCitation]   # may be [] iff kind=="insufficient_context"
    aanbeveling: str                        # 40–2000 chars
    insufficient_context_reason: str | None = None   # required iff kind=="insufficient_context"
```

Append to §5.4 **Grounding mechanism** as a new bullet after the existing ones:

```markdown
- M5: when `kind == "insufficient_context"`, `verify_citations` is a no-op (empty lists have nothing to verify). The root Pydantic validator enforces: `kind=="answer"` requires non-empty citation lists and `insufficient_context_reason is None`; `kind=="insufficient_context"` requires a non-empty reason string.
```

Append to §5.4 **System prompt** a new bulleted section:

```markdown
- AQ1 (M5): on `huurtype_hypothese == "onbekend"` the `aanbeveling` must present beding-route and voorstel-route as alternatives ("Als ... Als ..."), never stacked; on known huurtype only the applicable path shows.
- AQ2 (M5): if any cited case's `chunk_text` contains `Richtlijn 93/13`, `oneerlijk beding`, or `algehele vernietiging`, the `korte_conclusie` must surface the fully-void consequence and the `aanbeveling` must flag the consumer-route option.
- AQ8 (M5): if the synth judges the retrieved material insufficient to answer, emit `kind="insufficient_context"` with empty lists and a Dutch `insufficient_context_reason` naming what was searched, what's missing, and which specialism (out of `{arbeidsrecht, verzekeringsrecht, burenrecht, consumentenrecht, familierecht}`) to suggest.
```

- [ ] **Step 5: Update §6.3 event types table**

Find the `run_finished` row:

```markdown
| `run_finished` | orchestrator | `{ final_answer: StructuredAnswer }` |
```

Replace with:

```markdown
| `run_finished` | orchestrator | `{ final_answer: StructuredAnswer }` — `final_answer.kind ∈ {"answer","insufficient_context"}` since M5. Frontend discriminates on `kind`. |
```

- [ ] **Step 6: Add M5 row to §11 Milestones**

After the M4 row:

```markdown
| M5 | AQ1 procedure routing, AQ2 EU escalation, AQ8 graceful refusal, AQ3 HR coverage expansion, eval suite | decomposer emits `huurtype_hypothese`; retrievers emit `low_confidence`; synth routes + escalates + refuses; fence expansion + priority-ECLI top-up; 5-question eval manifest with pre/post docs; frontend renders refusal variant |
```

- [ ] **Step 7: Add env var to §13 Configuration**

Find the env-var table and add a row (alphabetical):

```markdown
| `JURIST_CASE_SIMILARITY_FLOOR` | `0.55` | M5: cosine-similarity floor below which all three reranked cases trip `CaseRetrieverOut.low_confidence=True` |
```

- [ ] **Step 8: Append M5 decisions to §15 Decisions log**

Append ten rows after the existing list (use the same numbering continuation as §13 of the M5 spec):

```markdown
| M5-1 | Refusal is `StructuredAnswer.kind` variant, not new terminal event | New event churns SSE + frontend; data variant on `run_finished` is cheaper and honest |
| M5-2 | Both retriever `low_confidence` flags must be True to trip early-branch refusal | Single flag would refuse on borderline questions; the AND lets synth see the full corpus when one retriever still has signal |
| M5-3 | Synth can *also* emit `kind="insufficient_context"` on the normal path | Synth has final authority when retrieval looks confident-by-score but is actually off-topic |
| M5-4 | Tool schema uses JSON-Schema `if/then/else` for kind-dependent required | One tool name (`emit_answer`) vs two; keeps routing simple |
| M5-5 | `case_similarity_floor = 0.55` default, env-overridable | Derived from M4 eval distribution (on-topic ~0.71; off-topic ~0.3-0.5); env override without code change |
| M5-6 | `huurtype_hypothese` is four-way Literal, includes `onbekend` | Forces classification; honest "unknown" beats a missing optional field |
| M5-7 | AQ2 EU-escalation is prompt-only, not retrieval-stage | Signal is already in `chunk_text`; prompt rule has same effect at zero plumbing cost |
| M5-8 | Fence expansion + priority list, not subject-URI broadening | `civielRecht` parent explodes corpus ~5x with irrelevant content; fence was always the real precision |
| M5-9 | Priority ECLI list is a text file in git | Auditable; avoids the "what did we index last" reproducibility hole |
| M5-10 | Refusal prose uses the same `answer_delta` replay | Preserves UX contract; refusals feel first-class, not error screens |
```

- [ ] **Step 9: Lint + commit**

Run: `uv run ruff check .` — expect clean (doc-only change).

```bash
git add docs/superpowers/specs/2026-04-17-jurist-v1-design.md
git commit -m "docs(spec): amend parent spec for M5 — huurtype, low_confidence, kind, refusal"
```

---

## Task 1: Add `StructuredAnswer.kind` discriminator + root-validator

**Files:**
- Modify: `src/jurist/schemas.py`
- Modify: `tests/test_schemas.py`

Schema foundation. All later synth / fake / frontend changes depend on this landing first. Per §3.1 of the M5 spec.

- [ ] **Step 1: Write failing tests for `StructuredAnswer.kind`**

Append to `tests/test_schemas.py`:

```python
def test_structured_answer_kind_answer_requires_citations():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="relevante_wetsartikelen must be non-empty"):
        StructuredAnswer(
            kind="answer",
            korte_conclusie="x" * 50,
            relevante_wetsartikelen=[],
            vergelijkbare_uitspraken=[FAKE_ANSWER.vergelijkbare_uitspraken[0]],
            aanbeveling="y" * 50,
        )

def test_structured_answer_kind_answer_rejects_reason():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="insufficient_context_reason must be None"):
        StructuredAnswer(
            kind="answer",
            korte_conclusie="x" * 50,
            relevante_wetsartikelen=FAKE_ANSWER.relevante_wetsartikelen,
            vergelijkbare_uitspraken=FAKE_ANSWER.vergelijkbare_uitspraken,
            aanbeveling="y" * 50,
            insufficient_context_reason="nope",
        )

def test_structured_answer_kind_insufficient_requires_reason():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="insufficient_context_reason required"):
        StructuredAnswer(
            kind="insufficient_context",
            korte_conclusie="x" * 50,
            relevante_wetsartikelen=[],
            vergelijkbare_uitspraken=[],
            aanbeveling="y" * 50,
        )

def test_structured_answer_kind_insufficient_allows_empty_lists():
    a = StructuredAnswer(
        kind="insufficient_context",
        korte_conclusie="x" * 50,
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling="y" * 50,
        insufficient_context_reason="Vraag valt buiten huurrecht-corpus; verwijs naar burenrecht.",
    )
    assert a.kind == "insufficient_context"
    assert a.relevante_wetsartikelen == []
    assert a.insufficient_context_reason.startswith("Vraag valt")

def test_structured_answer_roundtrip_both_kinds():
    answer = FAKE_ANSWER.model_copy(update={"kind": "answer", "insufficient_context_reason": None})
    assert StructuredAnswer.model_validate(answer.model_dump()) == answer

    refusal = StructuredAnswer(
        kind="insufficient_context",
        korte_conclusie="x" * 50,
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling="y" * 50,
        insufficient_context_reason="r" * 50,
    )
    assert StructuredAnswer.model_validate(refusal.model_dump()) == refusal
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_schemas.py::test_structured_answer_kind_answer_requires_citations -v
```

Expected: FAIL with "unexpected keyword argument 'kind'" or similar (field doesn't exist yet).

- [ ] **Step 3: Implement the kind field + root-validator**

In `src/jurist/schemas.py`, find `class StructuredAnswer` and replace with:

```python
from pydantic import BaseModel, Field, model_validator

class StructuredAnswer(BaseModel):
    kind: Literal["answer", "insufficient_context"] = "answer"
    korte_conclusie: str = Field(..., min_length=40, max_length=2000)
    relevante_wetsartikelen: list[WetArtikelCitation] = Field(default_factory=list)
    vergelijkbare_uitspraken: list[UitspraakCitation] = Field(default_factory=list)
    aanbeveling: str = Field(..., min_length=40, max_length=2000)
    insufficient_context_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _kind_matches_shape(self) -> "StructuredAnswer":
        if self.kind == "answer":
            if self.insufficient_context_reason is not None:
                raise ValueError(
                    "insufficient_context_reason must be None when kind='answer'"
                )
            if not self.relevante_wetsartikelen:
                raise ValueError(
                    "relevante_wetsartikelen must be non-empty when kind='answer'"
                )
            if not self.vergelijkbare_uitspraken:
                raise ValueError(
                    "vergelijkbare_uitspraken must be non-empty when kind='answer'"
                )
        else:  # kind == "insufficient_context"
            if not self.insufficient_context_reason:
                raise ValueError(
                    "insufficient_context_reason required when kind='insufficient_context'"
                )
        return self
```

Keep `WetArtikelCitation`, `UitspraakCitation`, and other existing classes unchanged.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: all new tests PASS; existing tests PASS (the `kind="answer"` default keeps them compatible).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
git add src/jurist/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add StructuredAnswer.kind discriminator + root-validator"
```

---

## Task 2: Add `DecomposerOut.huurtype_hypothese`

**Files:**
- Modify: `src/jurist/schemas.py`
- Modify: `tests/test_schemas.py`

Per §4.1 of M5 spec.

- [ ] **Step 1: Write failing test**

Append to `tests/test_schemas.py`:

```python
def test_decomposer_out_huurtype_required():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DecomposerOut(
            sub_questions=["q1"],
            concepts=["c1"],
            intent="legality_check",
            # huurtype_hypothese missing
        )

def test_decomposer_out_huurtype_enum():
    out = DecomposerOut(
        sub_questions=["q1"],
        concepts=["c1"],
        intent="legality_check",
        huurtype_hypothese="onbekend",
    )
    assert out.huurtype_hypothese == "onbekend"

def test_decomposer_out_huurtype_rejects_invalid():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DecomposerOut(
            sub_questions=["q1"],
            concepts=["c1"],
            intent="legality_check",
            huurtype_hypothese="commercieel",  # not in enum
        )
```

- [ ] **Step 2: Run tests, see them fail**

```bash
uv run pytest tests/test_schemas.py::test_decomposer_out_huurtype_required -v
```

Expected: FAIL.

- [ ] **Step 3: Extend `DecomposerOut`**

In `src/jurist/schemas.py`, find `class DecomposerOut` and add the field:

```python
class DecomposerOut(BaseModel):
    sub_questions: list[str] = Field(..., min_length=1, max_length=5)
    concepts: list[str] = Field(..., min_length=1, max_length=10)
    intent: Literal["legality_check", "calculation", "procedure", "other"]
    huurtype_hypothese: Literal["sociale", "middeldure", "vrije", "onbekend"]  # M5 — AQ1
```

No default — forces the field to be present.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: new tests PASS. Existing tests that construct `DecomposerOut` without `huurtype_hypothese` will now FAIL — that's expected; they get fixed in Task 4.

- [ ] **Step 5: Lint + commit (tests broken expected)**

Don't commit yet if other tests still fail; continue to Task 3 first, then Task 4 fixes all fakes in one go. Skip this step's commit — next green commit happens after Task 4.

Actually, to keep one-task-one-commit discipline, commit what's green now using pytest exit code discipline:

```bash
uv run pytest tests/test_schemas.py -v
# new tests pass; two old tests fail due to missing huurtype — that's fine, Task 4 fixes them
uv run ruff check src/jurist/schemas.py
git add src/jurist/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add DecomposerOut.huurtype_hypothese enum field"
```

---

## Task 3: Add `low_confidence` flags to `StatuteOut` + `CaseRetrieverOut`

**Files:**
- Modify: `src/jurist/schemas.py`
- Modify: `tests/test_schemas.py`

Per §5.1 + §5.2 of M5 spec.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_schemas.py`:

```python
def test_statute_out_low_confidence_default_false():
    from jurist.schemas import StatuteOut
    out = StatuteOut(cited_articles=FAKE_STATUTE_OUT.cited_articles)
    assert out.low_confidence is False

def test_statute_out_low_confidence_explicit_true():
    from jurist.schemas import StatuteOut
    out = StatuteOut(cited_articles=FAKE_STATUTE_OUT.cited_articles, low_confidence=True)
    assert out.low_confidence is True

def test_case_retriever_out_low_confidence_default_false():
    from jurist.schemas import CaseRetrieverOut
    out = CaseRetrieverOut(cited_cases=FAKE_CASES)
    assert out.low_confidence is False

def test_case_retriever_out_low_confidence_explicit_true():
    from jurist.schemas import CaseRetrieverOut
    out = CaseRetrieverOut(cited_cases=FAKE_CASES, low_confidence=True)
    assert out.low_confidence is True
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/test_schemas.py::test_statute_out_low_confidence_default_false -v
```

Expected: FAIL with "unexpected keyword argument 'low_confidence'" or "extra keyword arguments are not permitted".

- [ ] **Step 3: Extend both schemas**

In `src/jurist/schemas.py`:

Find `class StatuteOut` and replace:

```python
class StatuteOut(BaseModel):
    cited_articles: list[CitedArticle]
    low_confidence: bool = False  # M5 — True when selected < 3
```

Find `class CaseRetrieverOut` and replace:

```python
class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]
    low_confidence: bool = False  # M5 — True when all top-3 similarity < threshold
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: the four new tests PASS. Existing tests using `StatuteOut(cited_articles=...)` continue to work (default False).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/jurist/schemas.py
git add src/jurist/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add low_confidence flags to StatuteOut + CaseRetrieverOut"
```

---

## Task 4: Update fakes + add `case_similarity_floor` config

**Files:**
- Modify: `src/jurist/fakes.py`
- Modify: `src/jurist/config.py`
- Modify: `.env.example`

Schemas changed, so the fixtures need the new fields. Also introduces the threshold setting that Task 6 consumes.

- [ ] **Step 1: Update `FAKE_DECOMPOSER_OUT`**

In `src/jurist/fakes.py`, find `FAKE_DECOMPOSER_OUT` and replace with:

```python
FAKE_DECOMPOSER_OUT = DecomposerOut(
    sub_questions=[
        "Welke wettelijke maxima gelden voor huurverhoging?",
        "Onder welke voorwaarden is een verhoging van 15% toegestaan?",
    ],
    concepts=[
        "huurprijs",
        "wettelijk maximum huurverhoging",
        "huurverhogingsbeding",
    ],
    intent="legality_check",
    huurtype_hypothese="onbekend",  # M5
)
```

- [ ] **Step 2: Update `FAKE_ANSWER`**

Find `FAKE_ANSWER` and add `kind="answer"` (default, but explicit for clarity):

```python
FAKE_ANSWER = StructuredAnswer(
    kind="answer",
    # ... existing fields unchanged ...
    insufficient_context_reason=None,
)
```

Keep all other fakes unchanged (StatuteOut/CaseRetrieverOut default `low_confidence=False` so no edit needed).

- [ ] **Step 3: Add the config setting**

In `src/jurist/config.py`, find the `class Settings` block and add after the existing M4 settings:

```python
    # M5 — case retriever low-confidence threshold
    case_similarity_floor: float = field(
        default_factory=lambda: float(os.getenv("JURIST_CASE_SIMILARITY_FLOOR", "0.55"))
    )
```

(If `config.py` uses plain `os.getenv(...)` at module level rather than `field(default_factory=...)`, follow the existing pattern. The existing M4 settings show the convention.)

- [ ] **Step 4: Update `.env.example`**

Append:

```bash
# M5 — case retriever low-confidence threshold (cosine floor below which all
# three reranked cases trip CaseRetrieverOut.low_confidence=True)
JURIST_CASE_SIMILARITY_FLOOR=0.55
```

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest -v
```

Expected: everything PASS. The schema tests from Tasks 1-3 pass; the fake-consuming tests in other files (fakes.py is imported by e.g. `tests/api/test_orchestrator.py`) validate with the new fields.

If any test fails: usually a `StatuteOut`/`CaseRetrieverOut` constructed somewhere without the defaults. Add `low_confidence=False` explicitly only if needed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check .
git add src/jurist/fakes.py src/jurist/config.py .env.example
git commit -m "feat(config+fakes): add case_similarity_floor; update fakes for M5 schemas"
```

---

## Task 5: Statute retriever emits `low_confidence`

**Files:**
- Modify: `src/jurist/agents/statute_retriever.py`
- Modify: `tests/agents/test_statute_retriever.py`

Per §5.1 of M5 spec.

- [ ] **Step 1: Write failing test**

Append to `tests/agents/test_statute_retriever.py`:

```python
@pytest.mark.asyncio
async def test_statute_retriever_low_confidence_true_when_selected_lt_3(
    mock_llm_statute_client_returning_2_articles,
    run_context_for_mock,
    fake_kg,
):
    from jurist.schemas import StatuteIn
    out_events = []
    async for ev in statute_retriever.run(
        StatuteIn(question="...", sub_questions=["..."], concepts=["..."]),
        ctx=run_context_for_mock,
    ):
        out_events.append(ev)
    final = out_events[-1]
    assert final.type == "agent_finished"
    out = StatuteOut.model_validate(final.data)
    assert len(out.cited_articles) == 2
    assert out.low_confidence is True

@pytest.mark.asyncio
async def test_statute_retriever_low_confidence_false_when_selected_ge_3(
    mock_llm_statute_client_returning_3_articles,
    run_context_for_mock,
    fake_kg,
):
    # ... same shape as above but with a mock that yields 3 articles via done.selected ...
    # Asserts out.low_confidence is False
    ...
```

The `mock_llm_statute_client_returning_N_articles` fixture goes in the same test file's `conftest.py` or inline — it scripts `MockAnthropicClient` to complete the tool loop with a `done` that has `selected=[...]` of length N. Model after existing happy-path fixture.

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_statute_retriever.py::test_statute_retriever_low_confidence_true_when_selected_lt_3 -v
```

Expected: FAIL (either AttributeError on `out.low_confidence` if the current code doesn't set it, or assertion error — depending on default).

- [ ] **Step 3: Wire `low_confidence` into the agent**

In `src/jurist/agents/statute_retriever.py`, find the final assembly of `StatuteOut`. It currently looks roughly like:

```python
out = StatuteOut(cited_articles=cited)
yield TraceEvent(type="agent_finished", data=out.model_dump())
```

Replace with:

```python
low_confidence = len(cited) < 3
out = StatuteOut(cited_articles=cited, low_confidence=low_confidence)
yield TraceEvent(type="agent_finished", data=out.model_dump())
```

No prompt change. No tool-loop change.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/agents/test_statute_retriever.py -v
```

Expected: PASS including both new tests. All existing tests still PASS (default False only flips when the tool loop returns `<3` articles, which existing happy-path tests do not).

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/statute_retriever.py tests/agents/test_statute_retriever.py
git commit -m "feat(statute_retriever): emit low_confidence=True when <3 articles selected"
```

---

## Task 6: Case retriever emits `low_confidence`

**Files:**
- Modify: `src/jurist/agents/case_retriever.py`
- Modify: `tests/agents/test_case_retriever.py`

Per §5.2 of M5 spec.

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_case_retriever.py`:

```python
@pytest.mark.asyncio
async def test_case_retriever_low_confidence_true_when_all_below_floor(
    embedder_fake, case_store_3_weak_candidates, mock_haiku_rerank, run_context_for_mock
):
    """All three reranked picks have similarity < 0.55 → low_confidence=True."""
    # Fixture setup yields 3 candidates with similarities [0.42, 0.38, 0.40].
    # Rerank returns those three.
    out_events = []
    async for ev in case_retriever.run(
        CaseRetrieverIn(question="off-topic", sub_questions=["?"], concepts=["?"],
                       cited_articles=[]),
        ctx=run_context_for_mock,
    ):
        out_events.append(ev)
    final = out_events[-1]
    out = CaseRetrieverOut.model_validate(final.data)
    assert len(out.cited_cases) == 3
    assert all(c.similarity < 0.55 for c in out.cited_cases)
    assert out.low_confidence is True

@pytest.mark.asyncio
async def test_case_retriever_low_confidence_false_when_any_above_floor(
    embedder_fake, case_store_3_mixed_candidates, mock_haiku_rerank, run_context_for_mock
):
    """At least one picked case ≥ 0.55 → low_confidence=False."""
    # Candidates have similarities [0.71, 0.52, 0.48] — top one is above floor.
    out_events = []
    async for ev in case_retriever.run(..., ctx=run_context_for_mock):
        out_events.append(ev)
    out = CaseRetrieverOut.model_validate(out_events[-1].data)
    assert out.low_confidence is False

@pytest.mark.asyncio
async def test_case_retriever_low_confidence_respects_env_override(
    monkeypatch, embedder_fake, case_store_3_mixed_candidates, mock_haiku_rerank,
    run_context_for_mock
):
    """Env var tunes the threshold."""
    monkeypatch.setenv("JURIST_CASE_SIMILARITY_FLOOR", "0.80")
    # reload settings — or pass threshold directly if case_retriever reads per-request
    import importlib, jurist.config
    importlib.reload(jurist.config)

    # Now with floor=0.80, even 0.71 is below → low_confidence=True
    out_events = []
    async for ev in case_retriever.run(..., ctx=run_context_for_mock):
        out_events.append(ev)
    out = CaseRetrieverOut.model_validate(out_events[-1].data)
    assert out.low_confidence is True
```

The fixtures `case_store_3_weak_candidates` and `case_store_3_mixed_candidates` are small shims that make `CaseStore.query(vec)` return a scripted list of `(CaseChunkRow, float)` tuples with controlled similarities. Pattern after existing `case_store_*` fixtures.

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/agents/test_case_retriever.py::test_case_retriever_low_confidence_true_when_all_below_floor -v
```

Expected: FAIL (out has no `low_confidence`, or it's always False).

- [ ] **Step 3: Wire the threshold read + computation**

In `src/jurist/agents/case_retriever.py`, near the top add:

```python
from jurist.config import settings
```

Find the final assembly of `CaseRetrieverOut` (after rerank + `_assemble_cited_cases`). Replace:

```python
out = CaseRetrieverOut(cited_cases=cited_cases)
```

with:

```python
floor = settings.case_similarity_floor
low_confidence = (
    len(cited_cases) >= 3
    and all(c.similarity < floor for c in cited_cases)
)
out = CaseRetrieverOut(cited_cases=cited_cases, low_confidence=low_confidence)
```

Note: the existing `<3` hard-fail path (`RerankFailedError`) is untouched — this only triggers on `>=3` cases all below the floor.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/agents/test_case_retriever.py -v
```

Expected: all PASS, including the three new tests.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/case_retriever.py tests/agents/test_case_retriever.py
git commit -m "feat(case_retriever): emit low_confidence=True when all top-3 similarity < floor"
```

---

## Task 7: Decomposer classifies `huurtype_hypothese`

**Files:**
- Modify: `src/jurist/agents/decomposer.py`
- Modify: `src/jurist/llm/prompts.py`
- Create: `tests/agents/test_decomposer_huurtype.py`

Per §4 of M5 spec.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_decomposer_huurtype.py`:

```python
"""M5 — decomposer huurtype_hypothese classification."""
import pytest
from tests.fixtures.mock_llm import MockAnthropicClient
from jurist.agents.decomposer import run as decomposer_run
from jurist.config import RunContext
from jurist.schemas import DecomposerOut, DecomposerIn


def _mock_client_with_huurtype(huurtype: str) -> MockAnthropicClient:
    """Scripts the mock to return a decomposer tool output with the given huurtype."""
    return MockAnthropicClient(turns=[{
        "content": [
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "emit_decomposition",
                "input": {
                    "sub_questions": ["Mag een huurverhoging X?"],
                    "concepts": ["huurprijs"],
                    "intent": "legality_check",
                    "huurtype_hypothese": huurtype,
                },
            }
        ]
    }])


@pytest.mark.asyncio
@pytest.mark.parametrize("question,expected", [
    ("Mijn sociale huurwoning kreeg een verhoging, mag dat?", "sociale"),
    ("Mijn middenhuurwoning kreeg een verhoging, mag dat?", "middeldure"),
    ("Ik huur in de vrije sector, mag de verhuurder verhogen?", "vrije"),
    ("Mijn verhuurder wil de huur verhogen, mag dat?", "onbekend"),
])
async def test_decomposer_emits_huurtype_hypothese(question, expected):
    ctx = RunContext(llm=_mock_client_with_huurtype(expected), kg=None, case_store=None, embedder=None)
    events = [ev async for ev in decomposer_run(DecomposerIn(question=question), ctx=ctx)]
    final = events[-1]
    assert final.type == "agent_finished"
    out = DecomposerOut.model_validate(final.data)
    assert out.huurtype_hypothese == expected


@pytest.mark.asyncio
async def test_decomposer_prompt_contains_huurtype_classification_rules():
    """Prompt stability: the Dutch classifier rules must be present."""
    from jurist.llm.prompts import render_decomposer_system
    prompt = render_decomposer_system()
    assert "huurtype_hypothese" in prompt
    assert "sociale" in prompt and "middeldure" in prompt and "vrije" in prompt
    assert "onbekend" in prompt


def test_decomposer_tool_schema_has_huurtype_enum():
    """Tool schema extends with the new enum property."""
    from jurist.agents.decomposer import _build_decomposer_tool_schema
    schema = _build_decomposer_tool_schema()
    props = schema["input_schema"]["properties"]
    assert "huurtype_hypothese" in props
    assert props["huurtype_hypothese"]["enum"] == ["sociale", "middeldure", "vrije", "onbekend"]
    assert "huurtype_hypothese" in schema["input_schema"]["required"]
```

If the existing decomposer inlines its tool schema (not a helper), extract a `_build_decomposer_tool_schema()` function first — the test references it.

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/agents/test_decomposer_huurtype.py -v
```

Expected: FAIL (tool schema doesn't have the field; prompt doesn't either).

- [ ] **Step 3: Extend the tool schema**

In `src/jurist/agents/decomposer.py`, find the `emit_decomposition` tool definition. It currently looks like:

```python
{
  "name": "emit_decomposition",
  ...
  "input_schema": {
    "type": "object",
    "properties": {
      "sub_questions": {...},
      "concepts": {...},
      "intent": {...},
    },
    "required": ["sub_questions", "concepts", "intent"],
  },
}
```

Refactor into a helper and add the new property:

```python
def _build_decomposer_tool_schema() -> dict:
    return {
        "name": "emit_decomposition",
        "description": "Decomposeer een Nederlandse huurrecht-vraag in sub-vragen, concepten, intentie, en huurtype-hypothese.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_questions": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "items": {"type": "string", "minLength": 5}
                },
                "concepts": {
                    "type": "array", "minItems": 1, "maxItems": 10,
                    "items": {"type": "string", "minLength": 2}
                },
                "intent": {
                    "type": "string",
                    "enum": ["legality_check", "calculation", "procedure", "other"]
                },
                "huurtype_hypothese": {
                    "type": "string",
                    "enum": ["sociale", "middeldure", "vrije", "onbekend"],
                },
            },
            "required": ["sub_questions", "concepts", "intent", "huurtype_hypothese"],
        },
    }
```

Use the helper at the agent's call site.

- [ ] **Step 4: Extend the system prompt**

In `src/jurist/llm/prompts.py`, find `render_decomposer_system` and append to its Dutch text:

```python
def render_decomposer_system() -> str:
    return (
        "Je bent een Nederlandse juridische assistent gespecialiseerd in huurrecht.\n"
        "Je decomposeert huurrecht-vragen in 1–5 sub-vragen, 1–10 juridische\n"
        "concepten (Nederlandse termen), en een intentie uit\n"
        "{legality_check, calculation, procedure, other}.\n"
        "Roep uitsluitend het hulpmiddel `emit_decomposition` aan. Geen vrije tekst.\n"
        "\n"
        "Classificeer huurtype_hypothese op basis van signaalwoorden in de vraag:\n"
        "- \"sociale\" / \"sociale huurwoning\" / \"gereguleerde huur\" / \"corporatiewoning\" → \"sociale\"\n"
        "- \"middeldure huur\" / \"middenhuur\" / \"middensegment\" → \"middeldure\"\n"
        "- \"vrije sector\" / \"geliberaliseerde huur\" / \"particuliere huurmarkt\" → \"vrije\"\n"
        "- Geen expliciet signaal → \"onbekend\"\n"
        "Bij twijfel: \"onbekend\". Classificeer niet op basis van impliciete\n"
        "aannames over huurprijs.\n"
    )
```

- [ ] **Step 5: Run tests — expect pass**

```bash
uv run pytest tests/agents/test_decomposer_huurtype.py tests/agents/test_decomposer.py -v
```

Expected: PASS on new tests. Existing decomposer tests (from M4) may fail because they script `MockAnthropicClient` to return a tool output without `huurtype_hypothese`. Fix: update those fixtures / scripts to include `"huurtype_hypothese": "onbekend"`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/decomposer.py src/jurist/llm/prompts.py tests/agents/test_decomposer_huurtype.py tests/agents/test_decomposer.py
git commit -m "feat(decomposer): classify huurtype_hypothese with Dutch signal-word rules"
```

---

## Task 8: Synthesizer refusal helpers (`synthesizer_refusal.py`)

**Files:**
- Create: `src/jurist/agents/synthesizer_refusal.py`
- Create: `tests/agents/test_synthesizer_refusal.py`

Pure helpers. No LLM. Per §6.2 + §3.2 of M5 spec.

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_synthesizer_refusal.py`:

```python
"""M5 — pure helpers for the synthesizer's refusal branch."""
import pytest
from jurist.agents.synthesizer_refusal import (
    should_refuse,
    ALLOWED_FALLBACK_DOMAINS,
)
from jurist.schemas import StatuteOut, CaseRetrieverOut
from jurist.fakes import FAKE_STATUTE_OUT, FAKE_CASES


def _stat(low: bool) -> StatuteOut:
    return FAKE_STATUTE_OUT.model_copy(update={"low_confidence": low})


def _case(low: bool) -> CaseRetrieverOut:
    return CaseRetrieverOut(cited_cases=FAKE_CASES, low_confidence=low)


@pytest.mark.parametrize("stat_low,case_low,expected", [
    (True,  True,  True),
    (True,  False, False),
    (False, True,  False),
    (False, False, False),
])
def test_should_refuse_truth_table(stat_low, case_low, expected):
    assert should_refuse(_stat(stat_low), _case(case_low)) is expected


def test_allowed_fallback_domains_is_closed_set():
    assert ALLOWED_FALLBACK_DOMAINS == {
        "arbeidsrecht",
        "verzekeringsrecht",
        "burenrecht",
        "consumentenrecht",
        "familierecht",
    }
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_synthesizer_refusal.py -v
```

Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Create the module**

Create `src/jurist/agents/synthesizer_refusal.py`:

```python
"""Pure helpers for the synthesizer's refusal branch (AQ8).

No LLM, no I/O. The agent module (`synthesizer.py`) calls `should_refuse`
to decide the early-branch and uses `ALLOWED_FALLBACK_DOMAINS` when
rendering the refusal prompt.
"""
from __future__ import annotations

from jurist.schemas import CaseRetrieverOut, StatuteOut

ALLOWED_FALLBACK_DOMAINS: frozenset[str] = frozenset({
    "arbeidsrecht",
    "verzekeringsrecht",
    "burenrecht",
    "consumentenrecht",
    "familierecht",
})


def should_refuse(stat: StatuteOut, case: CaseRetrieverOut) -> bool:
    """Early-branch refusal gate.

    Per M5 spec §6.2 / decision M5-2: both retrievers must flag low
    confidence for the pipeline to short-circuit a refusal. A strong
    match in either retriever keeps the synth on the normal path
    (where the synth itself can still self-judge a refusal).
    """
    return stat.low_confidence and case.low_confidence
```

Note: the comparison uses `frozenset` vs `set` in the test. Update the test assertion to use `set(ALLOWED_FALLBACK_DOMAINS)` or change the module constant to a plain `set[str]`. Pick one — the test as written uses `==` against a `set`, so `set(ALLOWED_FALLBACK_DOMAINS) == ...` works either way. Keep `frozenset` (immutable).

Edit the test to match:

```python
def test_allowed_fallback_domains_is_closed_set():
    assert set(ALLOWED_FALLBACK_DOMAINS) == {
        "arbeidsrecht",
        "verzekeringsrecht",
        "burenrecht",
        "consumentenrecht",
        "familierecht",
    }
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/agents/test_synthesizer_refusal.py -v
```

Expected: all 5 parametrized cases + domain test PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/synthesizer_refusal.py tests/agents/test_synthesizer_refusal.py
git commit -m "feat(synthesizer): add refusal helpers (should_refuse + fallback-domain set)"
```

---

## Task 9: `build_synthesis_tool_schema` with `allow_refusal`

**Files:**
- Modify: `src/jurist/agents/synthesizer_tools.py`
- Modify: `tests/agents/test_synthesizer_tools.py`

Per §6.4 of M5 spec.

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_synthesizer_tools.py`:

```python
def test_build_synthesis_tool_schema_has_kind_enum_when_allow_refusal():
    schema = build_synthesis_tool_schema(
        article_ids=["art/1"], bwb_ids=["BWB/1"], eclis=["ECLI:E:1"],
        allow_refusal=True,
    )
    props = schema["input_schema"]["properties"]
    assert "kind" in props
    assert set(props["kind"]["enum"]) == {"answer", "insufficient_context"}
    assert "insufficient_context_reason" in props


def test_build_synthesis_tool_schema_uses_if_then_else_for_conditional_required():
    schema = build_synthesis_tool_schema(
        article_ids=["art/1"], bwb_ids=["BWB/1"], eclis=["ECLI:E:1"],
        allow_refusal=True,
    )
    body = schema["input_schema"]
    assert "if" in body
    assert body["if"] == {"properties": {"kind": {"const": "answer"}}}
    assert set(body["then"]["required"]) >= {"relevante_wetsartikelen", "vergelijkbare_uitspraken"}
    assert "insufficient_context_reason" in body["else"]["required"]
    # Top-level required (unconditional):
    assert set(body["required"]) == {"kind", "korte_conclusie", "aanbeveling"}


def test_build_synthesis_tool_schema_backcompat_without_allow_refusal():
    """allow_refusal=False preserves the M4 shape."""
    schema = build_synthesis_tool_schema(
        article_ids=["art/1"], bwb_ids=["BWB/1"], eclis=["ECLI:E:1"],
        allow_refusal=False,
    )
    props = schema["input_schema"]["properties"]
    assert "kind" not in props
    assert "if" not in schema["input_schema"]
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py::test_build_synthesis_tool_schema_has_kind_enum_when_allow_refusal -v
```

Expected: FAIL with "unexpected keyword argument 'allow_refusal'".

- [ ] **Step 3: Extend `build_synthesis_tool_schema`**

In `src/jurist/agents/synthesizer_tools.py`, replace the function:

```python
def build_synthesis_tool_schema(
    article_ids: list[str],
    bwb_ids: list[str],
    eclis: list[str],
    *,
    allow_refusal: bool = True,
) -> dict:
    wet_item = {
        "type": "object",
        "properties": {
            "article_id":    {"type": "string", "enum": article_ids},
            "bwb_id":        {"type": "string", "enum": bwb_ids},
            "article_label": {"type": "string", "minLength": 5},
            "quote":         {"type": "string", "minLength": 40, "maxLength": 500},
            "explanation":   {"type": "string", "minLength": 40, "maxLength": 2000},
        },
        "required": ["article_id", "bwb_id", "article_label", "quote", "explanation"],
    }
    uit_item = {
        "type": "object",
        "properties": {
            "ecli":        {"type": "string", "enum": eclis},
            "quote":       {"type": "string", "minLength": 40, "maxLength": 500},
            "explanation": {"type": "string", "minLength": 40, "maxLength": 2000},
        },
        "required": ["ecli", "quote", "explanation"],
    }

    body: dict = {
        "type": "object",
        "properties": {
            "korte_conclusie": {"type": "string", "minLength": 40, "maxLength": 2000},
            "relevante_wetsartikelen": {"type": "array", "items": wet_item},
            "vergelijkbare_uitspraken": {"type": "array", "items": uit_item},
            "aanbeveling":     {"type": "string", "minLength": 40, "maxLength": 2000},
        },
    }

    if allow_refusal:
        body["properties"]["kind"] = {
            "type": "string",
            "enum": ["answer", "insufficient_context"],
        }
        body["properties"]["insufficient_context_reason"] = {
            "type": "string",
            "minLength": 40,
            "maxLength": 1000,
        }
        body["required"] = ["kind", "korte_conclusie", "aanbeveling"]
        body["if"] = {"properties": {"kind": {"const": "answer"}}}
        body["then"] = {
            "required": ["relevante_wetsartikelen", "vergelijkbare_uitspraken"],
            "properties": {
                "relevante_wetsartikelen": {"minItems": 1},
                "vergelijkbare_uitspraken": {"minItems": 1},
            },
        }
        body["else"] = {"required": ["insufficient_context_reason"]}
    else:
        body["properties"]["relevante_wetsartikelen"]["minItems"] = 1
        body["properties"]["vergelijkbare_uitspraken"]["minItems"] = 1
        body["required"] = [
            "korte_conclusie", "relevante_wetsartikelen",
            "vergelijkbare_uitspraken", "aanbeveling",
        ]

    return {
        "name": "emit_answer",
        "description": "Genereer het gestructureerde Nederlandse antwoord met gegrondveste citaten, of weiger met kind='insufficient_context'.",
        "input_schema": body,
    }
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all PASS, including existing schema tests and the three new ones.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer_tools): tool schema supports allow_refusal + if/then/else"
```

---

## Task 10: `verify_citations` no-ops on refusal kind

**Files:**
- Modify: `src/jurist/agents/synthesizer_tools.py`
- Modify: `tests/agents/test_synthesizer_tools.py`

Per §6.6 of M5 spec.

- [ ] **Step 1: Write failing test**

Append to `tests/agents/test_synthesizer_tools.py`:

```python
def test_verify_citations_noop_on_insufficient_context():
    answer = StructuredAnswer(
        kind="insufficient_context",
        korte_conclusie="Deze vraag valt buiten het huurrecht-corpus. " * 2,
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling="Raadpleeg een specialist arbeidsrecht. " * 2,
        insufficient_context_reason="Gezocht in huurrecht-corpus; niets relevants gevonden.",
    )
    # Even with empty cited_articles/cited_cases, no failures should surface.
    result = verify_citations(answer, cited_articles=[], cited_cases=[])
    assert result == []
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py::test_verify_citations_noop_on_insufficient_context -v
```

Expected: FAIL (function doesn't know about kind).

- [ ] **Step 3: Add the early-return**

In `src/jurist/agents/synthesizer_tools.py`, at the top of `verify_citations`:

```python
def verify_citations(
    answer: StructuredAnswer,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
    *,
    min_quote_chars: int = 40,
    max_quote_chars: int = 500,
) -> list[FailedCitation]:
    # M5 — refusal-kind answers have empty citation lists by construction;
    # nothing to verify. Keeps the synthesizer's control flow uniform.
    if answer.kind == "insufficient_context":
        return []
    # ... existing body unchanged ...
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer_tools): verify_citations no-ops on kind=insufficient_context"
```

---

## Task 11: Update `synthesizer.system.md` with three new rules

**Files:**
- Modify: `src/jurist/llm/prompts/synthesizer.system.md`

Per §6.3 of M5 spec. Docs-style change; no tests exercise prompt content directly but Task 13's agent tests verify integration.

- [ ] **Step 1: Read the current prompt**

```bash
cat src/jurist/llm/prompts/synthesizer.system.md
```

- [ ] **Step 2: Append three Dutch rule blocks**

At the end of the file, append:

```markdown

## AQ1 — Procedure-routing per huurtype

Je ontvangt `huurtype_hypothese` ∈ {sociale, middeldure, vrije, onbekend}
in het vraagblok. In het `aanbeveling`-veld:

- **"sociale"**: geef UITSLUITEND de sociale-sector-procedure (bezwaar vóór
  ingangsdatum; daarna Huurcommissie-toetsing op aanzegging van verhuurder
  via art. 7:253 BW).
- **"middeldure"**: geef UITSLUITEND de middeldure-sector-procedure
  (Huurcommissie-verzoek binnen 4 maanden na ingangsdatum; art. 7:248 lid 4).
- **"vrije"**: geef UITSLUITEND de vrije-sector-procedure (onderhandeling /
  kantonrechter; beperkte Huurcommissie-rol).
- **"onbekend"**: presenteer BEIDE routes expliciet ALS ALTERNATIEVEN, niet
  als stapelbare stappen. Begin met een als-dan-structuur
  ("Als uw woning sociaal/middelduur is: …. Als vrije sector: ….").

Stapel NOOIT art. 7:248 lid 4 en art. 7:253 in één procedureketen.

## AQ2 — EU-richtlijn-escalatie

Als een geciteerde uitspraak in `chunk_text` expliciet Richtlijn 93/13/EEG,
"oneerlijk beding", of "algehele vernietiging" toepast: vermeld in
`korte_conclusie` het gevolg *"algehele vernietiging van het beding"* als
mogelijkheid naast de statutaire *"nietig voor het meerdere"*. Noteer in
`aanbeveling` de consumenten-route als optie voor huurders die een
professionele verhuurder tegenover zich hebben.

## AQ8 — Onvoldoende context

Als je oordeelt dat de meegeleverde wetsartikelen en uitspraken samen de
vraag niet substantieel kunnen onderbouwen — ook niet na goed lezen van
elk fragment — roep dan `emit_answer` aan met `kind="insufficient_context"`.
Vul `insufficient_context_reason` met:
1. Wat er is gezocht (bijv. "huurrecht-corpus: BW Boek 7 Titel 4, Uhw,
   rechtspraak 2023-").
2. Wat er ontbreekt.
3. Naar welk specialisme (uit {arbeidsrecht, verzekeringsrecht, burenrecht,
   consumentenrecht, familierecht}) je zou verwijzen.

Laat `relevante_wetsartikelen` en `vergelijkbare_uitspraken` leeg. Geef een
korte `korte_conclusie` en een `aanbeveling` die de gebruiker naar een
geschikter kanaal stuurt.
```

- [ ] **Step 3: Run existing synth tests**

```bash
uv run pytest tests/agents/test_synthesizer.py -v
```

Expected: PASS. The prompt change is additive; existing MockStreamingClient scripts feed pre-canned tool outputs, so the new prompt rules don't break unit tests.

- [ ] **Step 4: Commit**

```bash
uv run ruff check .
git add src/jurist/llm/prompts/synthesizer.system.md
git commit -m "feat(synthesizer): add AQ1/AQ2/AQ8 Dutch prompt rules"
```

---

## Task 12: Synthesizer agent — early-branch refusal + kind-aware events

**Files:**
- Modify: `src/jurist/agents/synthesizer.py`
- Modify: `src/jurist/schemas.py` (ensure `SynthesizerIn` gets retriever outputs)

Per §6.1 + §6.5 + §6.7 of M5 spec.

- [ ] **Step 1: Extend `SynthesizerIn` with three optional M5 fields**

M4's `SynthesizerIn` (at `src/jurist/schemas.py`) currently has:

```python
class SynthesizerIn(BaseModel):
    question: str
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]
```

Add three **optional** fields so existing M4 tests keep working unchanged:

```python
class SynthesizerIn(BaseModel):
    question: str
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]
    # M5 additions — optional with safe defaults so M4 tests keep passing.
    decomposer_out: DecomposerOut | None = None
    statute_low_confidence: bool = False
    case_low_confidence: bool = False
```

Update the orchestrator call site:

```bash
grep -n "SynthesizerIn(" src/jurist/api/orchestrator.py
```

Replace the `SynthesizerIn(...)` construction in the orchestrator with:

```python
synth_in = SynthesizerIn(
    question=question,
    cited_articles=stat_out.cited_articles,
    cited_cases=case_out.cited_cases,
    decomposer_out=decomp_out,
    statute_low_confidence=stat_out.low_confidence,
    case_low_confidence=case_out.low_confidence,
)
```

- [ ] **Step 2: Write the early-branch refusal flow**

At the top of `src/jurist/agents/synthesizer.py`:

```python
from jurist.agents.synthesizer_refusal import should_refuse
```

Inside `run(...)`:

```python
async def run(input: SynthesizerIn, *, ctx: RunContext) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    # M5 AQ8 — early-branch refusal when both retrievers flag low confidence.
    if should_refuse(
        # Synthesize a minimal view for the helper:
        _StatuteView(low_confidence=input.statute_low_confidence),
        _CaseView(low_confidence=input.case_low_confidence),
    ):
        refusal_answer = await _stream_refusal_answer(ctx, input)
        async for ev in _emit_refusal_events(refusal_answer):
            yield ev
        return

    # ... existing M4 normal-path body ...
```

Define small adapter namedtuples near the top of the file:

```python
from collections import namedtuple
_StatuteView = namedtuple("_StatuteView", ["low_confidence"])
_CaseView = namedtuple("_CaseView", ["low_confidence"])
```

- [ ] **Step 3: Implement `_stream_refusal_answer` + `_emit_refusal_events`**

```python
async def _stream_refusal_answer(ctx: RunContext, input: SynthesizerIn) -> StructuredAnswer:
    """Single Sonnet streaming call with a refusal-only schema.

    Tool schema has kind fixed to 'insufficient_context' via a 1-element enum.
    No citation enums (empty lists are enforced).
    """
    refusal_schema = {
        "name": "emit_answer",
        "description": "Geef een beleefde weigering als de huurrecht-corpus de vraag niet ondersteunt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["insufficient_context"]},
                "korte_conclusie": {"type": "string", "minLength": 40, "maxLength": 2000},
                "relevante_wetsartikelen": {"type": "array", "items": {}, "maxItems": 0},
                "vergelijkbare_uitspraken": {"type": "array", "items": {}, "maxItems": 0},
                "aanbeveling": {"type": "string", "minLength": 40, "maxLength": 2000},
                "insufficient_context_reason": {
                    "type": "string", "minLength": 40, "maxLength": 1000
                },
            },
            "required": [
                "kind", "korte_conclusie", "aanbeveling", "insufficient_context_reason",
            ],
        },
    }
    user_msg = (
        f"Vraag: {input.question}\n\n"
        "De huurrecht-retrievers gaven te weinig relevante bronnen om deze "
        "vraag te onderbouwen. Roep `emit_answer` aan met `kind=\"insufficient_context\"` "
        "en benoem in `insufficient_context_reason` wat is gezocht, wat ontbreekt, "
        "en naar welk specialisme (uit {arbeidsrecht, verzekeringsrecht, burenrecht, "
        "consumentenrecht, familierecht}) je zou verwijzen."
    )
    async with ctx.llm.messages.stream(
        model=settings.model_synthesizer,
        system=[{"type": "text", "text": render_synthesizer_system()}],
        tools=[refusal_schema],
        tool_choice={"type": "tool", "name": "emit_answer"},
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    ) as stream:
        async for _event in stream:
            pass  # no pre-tool text expected; refusal is short
        final = await stream.get_final_message()

    tool_use = _extract_tool_use(final, "emit_answer")
    if tool_use is None:
        # Hard-fail: refusal path itself failed. Fall through as a manufactured
        # refusal so the pipeline terminates via run_finished, not run_failed.
        return StructuredAnswer(
            kind="insufficient_context",
            korte_conclusie=(
                "Deze vraag valt buiten het bereik van dit systeem. "
                "Het huurrecht-corpus bevat geen bronnen die de vraag onderbouwen."
            ),
            relevante_wetsartikelen=[],
            vergelijkbare_uitspraken=[],
            aanbeveling=(
                "Raadpleeg een specialist in een relevanter rechtsgebied "
                "(bijv. arbeidsrecht, verzekeringsrecht of burenrecht)."
            ),
            insufficient_context_reason=(
                "De synthesizer kon geen hulpmiddel-aanroep genereren; "
                "automatische fallback-weigering."
            ),
        )
    return StructuredAnswer.model_validate(tool_use.input)


async def _emit_refusal_events(answer: StructuredAnswer) -> AsyncIterator[TraceEvent]:
    # No citation_resolved events (empty lists).
    # Synthetic answer_delta replay of korte_conclusie + reason + aanbeveling.
    replay_text = (
        answer.korte_conclusie + "\n\n"
        + (answer.insufficient_context_reason or "") + "\n\n"
        + answer.aanbeveling
    )
    for token in _tokenize_for_replay(replay_text):
        yield TraceEvent(type="answer_delta", data={"delta": token})
        await asyncio.sleep(_TOKEN_SLEEP_S)
    yield TraceEvent(type="agent_finished", data=SynthesizerOut(answer=answer).model_dump())
```

Reuse existing `_tokenize_for_replay` and `_TOKEN_SLEEP_S` (word-level tokenizer from M4). If those names differ in the current file, match them.

- [ ] **Step 4: Normal-path kind branching**

On the normal path, after `_validate_attempt` succeeds and before emitting `citation_resolved` / `answer_delta`, branch on `answer.kind`:

```python
answer = StructuredAnswer.model_validate(tool_input)

if answer.kind == "insufficient_context":
    # Synth self-judged refusal on the normal path — no citations to resolve.
    async for ev in _emit_refusal_events(answer):
        yield ev
    return

# ... existing citation_resolved + answer_delta loop ...
```

- [ ] **Step 5: Surface `huurtype_hypothese` in the user message**

In `build_synthesis_user_message` (or inline), prepend to the existing user-message body:

```python
"Vraag: {question}\n"
"Huurtype-hypothese (van decomposer): {huurtype}\n"
"\n"
"Relevante wetsartikelen ..."
```

Pass `huurtype=input.decomposer_out.huurtype_hypothese` from `synthesizer.run` through to the builder.

- [ ] **Step 6: Switch the synth to `allow_refusal=True`**

Where the synth builds its tool schema on the normal path:

```python
schema = build_synthesis_tool_schema(
    article_ids=[a.article_id for a in input.cited_articles],
    bwb_ids=list({a.bwb_id for a in input.cited_articles}),
    eclis=[c.ecli for c in input.cited_cases],
    allow_refusal=True,
)
```

- [ ] **Step 7: Run unit tests**

```bash
uv run pytest tests/agents/test_synthesizer.py tests/agents/test_synthesizer_tools.py tests/agents/test_synthesizer_grounding.py -v
```

Existing tests should mostly pass. Some may need an `allow_refusal=False` flip or an extra `kind="answer"` in their `MockStreamingClient` tool outputs — update inline. Expect minor test edits; they are the cost of the schema change.

- [ ] **Step 8: Commit**

```bash
uv run ruff check .
git add src/jurist/agents/synthesizer.py src/jurist/schemas.py src/jurist/api/orchestrator.py tests/agents/test_synthesizer.py tests/agents/test_synthesizer_grounding.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer): early-branch refusal + kind-aware events + huurtype passthrough"
```

---

## Task 13: Synthesizer tests — refusal variants + AQ1/AQ2 spec guards

**Files:**
- Modify: `tests/agents/test_synthesizer.py`
- Create: `tests/agents/test_synthesizer_m5_rules.py`

Per §6.8 of M5 spec. Three new test files' worth of behaviour; one new file to keep scope clear.

- [ ] **Step 1: Early-branch refusal — write failing test**

Look at the top of `tests/agents/test_synthesizer.py` to confirm the existing helpers: `_ctx(client)` (line 90), `_valid_tool_input()`, `_articles()`, `_cases()`. Reuse those. Also import `FAKE_DECOMPOSER_OUT` from `jurist.fakes` for the `decomposer_out` field.

Append to `tests/agents/test_synthesizer.py`:

```python
from jurist.fakes import FAKE_DECOMPOSER_OUT  # top of file, if not already imported

@pytest.mark.asyncio
async def test_synthesizer_early_branch_refusal_when_both_retrievers_low_confidence():
    """Both retrievers low_confidence → synth never calls normal-path; emits refusal answer."""
    refusal_input = {
        "kind": "insufficient_context",
        "korte_conclusie": "Deze vraag valt buiten het huurrecht-corpus. " * 2,
        "relevante_wetsartikelen": [],
        "vergelijkbare_uitspraken": [],
        "aanbeveling": "Raadpleeg een specialist burenrecht. " * 2,
        "insufficient_context_reason": "Gezocht in huurrecht-corpus; niets relevants gevonden.",
    }
    client = MockStreamingClient([StreamScript(text_deltas=[], tool_input=refusal_input)])
    ctx = _ctx(client)

    synth_in = SynthesizerIn(
        question="Mijn auto is stuk, wie betaalt?",
        cited_articles=[],  # empty lists + low_confidence=True mirror real retriever output
        cited_cases=[],
        decomposer_out=FAKE_DECOMPOSER_OUT,
        statute_low_confidence=True,
        case_low_confidence=True,
    )
    events = [ev async for ev in synthesizer.run(synth_in, ctx=ctx)]

    # Event shape: agent_started → answer_delta × N → agent_finished. No citation_resolved.
    types = [e.type for e in events]
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert "citation_resolved" not in types
    assert types.count("answer_delta") > 0

    final = StructuredAnswer.model_validate(events[-1].data["answer"])
    assert final.kind == "insufficient_context"
    assert final.relevante_wetsartikelen == []
    assert final.vergelijkbare_uitspraken == []
```

- [ ] **Step 2: Run — expect pass (Task 12 made it green)**

```bash
uv run pytest tests/agents/test_synthesizer.py::test_synthesizer_early_branch_refusal_when_both_retrievers_low_confidence -v
```

If fail: usually a fixture-plumbing issue. Trace `run_context_with_mock_stream` and `fake_decomposer_out`.

- [ ] **Step 3: Self-judged refusal — write + run**

Append to `test_synthesizer.py`:

```python
@pytest.mark.asyncio
async def test_synthesizer_self_judged_refusal_when_retrievers_confident():
    """Retrievers confident but synth emits kind=insufficient_context → no citation_resolved."""
    refusal_input = {
        "kind": "insufficient_context",
        "korte_conclusie": "x" * 50,
        "relevante_wetsartikelen": [],
        "vergelijkbare_uitspraken": [],
        "aanbeveling": "y" * 50,
        "insufficient_context_reason": "z" * 50,
    }
    client = MockStreamingClient([StreamScript(text_deltas=[], tool_input=refusal_input)])
    ctx = _ctx(client)

    synth_in = SynthesizerIn(
        question="Mag de huur met 15% omhoog?",
        cited_articles=_articles(),
        cited_cases=_cases(),
        decomposer_out=FAKE_DECOMPOSER_OUT,
        statute_low_confidence=False,
        case_low_confidence=False,
    )
    events = [ev async for ev in synthesizer.run(synth_in, ctx=ctx)]
    types = [e.type for e in events]
    assert "citation_resolved" not in types
    final = StructuredAnswer.model_validate(events[-1].data["answer"])
    assert final.kind == "insufficient_context"
```

Run:

```bash
uv run pytest tests/agents/test_synthesizer.py -v
```

Expected: PASS.

- [ ] **Step 4: AQ1 + AQ2 spec guard — create new file**

Create `tests/agents/test_synthesizer_m5_rules.py`:

```python
"""M5 spec-guard tests — AQ1 procedure routing + AQ2 EU escalation.

These are promptless unit tests: they assert that the system prompt and the
post-hoc verification path both support the M5 rules. They do NOT assert that
the live Sonnet model obeys the rules (that's integration scope).
"""
import re
from jurist.llm.prompts import render_synthesizer_system


def test_synthesizer_system_prompt_contains_aq1_routing_rules():
    prompt = render_synthesizer_system()
    assert "huurtype_hypothese" in prompt
    assert "sociale" in prompt and "middeldure" in prompt and "vrije" in prompt and "onbekend" in prompt
    assert re.search(r"Stapel NOOIT.*7:248.*7:253", prompt)


def test_synthesizer_system_prompt_contains_aq2_escalation_rule():
    prompt = render_synthesizer_system()
    assert "Richtlijn 93/13" in prompt
    assert "algehele vernietiging" in prompt
    assert "consumenten-route" in prompt or "consumentenroute" in prompt


def test_synthesizer_system_prompt_contains_aq8_refusal_rule():
    prompt = render_synthesizer_system()
    assert "insufficient_context" in prompt
    assert "insufficient_context_reason" in prompt
    # Closed-set domains
    for d in ["arbeidsrecht", "verzekeringsrecht", "burenrecht", "consumentenrecht", "familierecht"]:
        assert d in prompt
```

Run:

```bash
uv run pytest tests/agents/test_synthesizer_m5_rules.py -v
```

Expected: all PASS if Task 11's prompt edits landed correctly.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add tests/agents/test_synthesizer.py tests/agents/test_synthesizer_m5_rules.py
git commit -m "test(synthesizer): refusal variants + AQ1/AQ2/AQ8 prompt spec guards"
```

---

## Task 14: Fence term expansion in caselaw profiles

**Files:**
- Modify: `src/jurist/ingest/caselaw_profiles.py`
- Modify: `tests/ingest/test_caselaw_profiles.py` (create if not present)

Per §8.1 of M5 spec.

- [ ] **Step 1: Write failing tests**

Create or append `tests/ingest/test_caselaw_profiles.py`:

```python
"""M5 — fence expansion for huurrecht profile."""
from jurist.ingest.caselaw_profiles import PROFILES


def test_huurrecht_fence_contains_m5_additions():
    profile = PROFILES["huurrecht"]
    terms = set(t.lower() for t in profile.keyword_terms)
    # M4 baseline
    assert "huur" in terms
    assert "verhuur" in terms
    assert "woonruimte" in terms
    assert "huurcommissie" in terms
    # M5 additions
    assert "huurverhoging" in terms
    assert "huurprijs" in terms
    assert "indexering" in terms
    assert "oneerlijk beding" in terms
    assert "onredelijk beding" in terms


def test_fence_accepts_sample_m5_text():
    """A chunk mentioning 'oneerlijk beding' but not 'huur' should now pass."""
    from jurist.ingest.caselaw_profiles import passes_fence
    text = "Het beding is oneerlijk en wordt vernietigd op grond van Richtlijn 93/13/EEG."
    assert passes_fence(text, PROFILES["huurrecht"]) is True


def test_fence_rejects_clearly_off_topic():
    """Sanity — car-insurance text should not pass the huurrecht fence."""
    from jurist.ingest.caselaw_profiles import passes_fence
    text = "De verzekerde auto was bij een aanrijding betrokken en de WAM-verzekeraar wees dekking af."
    assert passes_fence(text, PROFILES["huurrecht"]) is False
```

If `passes_fence` doesn't exist as a reusable helper, expose it (refactor from inline usage in `caselaw.py`):

```python
def passes_fence(text: str, profile: CaselawProfile) -> bool:
    body = text.lower()
    return any(term.lower() in body for term in profile.keyword_terms)
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/ingest/test_caselaw_profiles.py -v
```

Expected: FAIL (M5 terms not in profile; possibly `passes_fence` doesn't exist).

- [ ] **Step 3: Extend the profile + add helper**

In `src/jurist/ingest/caselaw_profiles.py`:

```python
PROFILES: dict[str, CaselawProfile] = {
    "huurrecht": CaselawProfile(
        subject_uri="http://psi.rechtspraak.nl/rechtsgebieden#civielRecht_verbintenissenrecht",
        keyword_terms=[
            # M4 baseline
            "huur", "verhuur", "woonruimte", "huurcommissie",
            # M5 additions — AQ3
            "huurverhoging", "huurprijs", "indexering",
            "oneerlijk beding", "onredelijk beding",
        ],
    ),
}


def passes_fence(text: str, profile: CaselawProfile) -> bool:
    """Case-insensitive whole-substring match against any profile term.

    Multi-word terms (e.g. 'oneerlijk beding') are matched as a single
    contiguous substring; whole-token boundaries are not required.
    """
    body = text.lower()
    return any(term.lower() in body for term in profile.keyword_terms)
```

If `caselaw.py` had its own inline fence logic, replace it with a call to `passes_fence` to keep one implementation.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/ingest/test_caselaw_profiles.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/ingest/caselaw_profiles.py src/jurist/ingest/caselaw.py tests/ingest/test_caselaw_profiles.py
git commit -m "feat(caselaw_profiles): expand huurrecht fence + extract passes_fence helper"
```

---

## Task 15: `priority_eclis.py` — curated-list ingest helper

**Files:**
- Create: `src/jurist/ingest/priority_eclis.py`
- Create: `tests/ingest/test_priority_eclis.py`

Per §8.2 of M5 spec.

- [ ] **Step 1: Write failing tests**

Create `tests/ingest/test_priority_eclis.py`:

```python
"""M5 — priority-ECLI curated-list ingest."""
from pathlib import Path
import pytest
from jurist.ingest.priority_eclis import load_eclis, run_priority_ingest


def test_load_eclis_parses_text_file(tmp_path):
    p = tmp_path / "huurrecht.txt"
    p.write_text("ECLI:NL:HR:2024:1761\n# a comment\n\nECLI:NL:HR:2024:1763\n")
    eclis = load_eclis(p)
    assert eclis == ["ECLI:NL:HR:2024:1761", "ECLI:NL:HR:2024:1763"]


def test_load_eclis_rejects_invalid_lines(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("not-an-ecli\nECLI:NL:HR:2024:1761\n")
    with pytest.raises(ValueError, match="invalid ECLI"):
        load_eclis(p)


@pytest.mark.asyncio
async def test_run_priority_ingest_idempotent(tmp_path, case_store_populated, embedder_fake, fetch_xml_fake):
    """Running twice on the same list adds the rows once."""
    p = tmp_path / "priority.txt"
    p.write_text("ECLI:NL:HR:2024:9001\n")

    result_1 = await run_priority_ingest(
        p, lance_path=case_store_populated.lance_path,
        cache_dir=tmp_path / "cache", embedder=embedder_fake,
        fetch=fetch_xml_fake,
    )
    result_2 = await run_priority_ingest(
        p, lance_path=case_store_populated.lance_path,
        cache_dir=tmp_path / "cache", embedder=embedder_fake,
        fetch=fetch_xml_fake,
    )
    assert result_1.written > 0
    assert result_2.written == 0  # dedupe
```

Fixtures `fetch_xml_fake`, `case_store_populated`, `embedder_fake` live in `tests/conftest.py` or `tests/ingest/conftest.py`. Model after existing M3a fixtures.

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/ingest/test_priority_eclis.py -v
```

Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Create the module**

Create `src/jurist/ingest/priority_eclis.py`. The existing helpers live at
`jurist.ingest.caselaw_fetch.fetch_content`, `jurist.ingest.caselaw_parser.parse_case`,
and `jurist.ingest.splitter.split` — the module reuses them directly:

```python
"""M5 — priority-ECLI curated-list ingest (AQ3).

Bypasses the list/fence stages of the regular caselaw ingest. Fetches
ECLIs by name, parses, chunks, embeds, and writes to LanceDB. Idempotent
via existing (ecli, chunk_idx) dedupe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jurist.embedding import Embedder
from jurist.ingest.caselaw_fetch import fetch_content
from jurist.ingest.caselaw_parser import ParseError, parse_case
from jurist.ingest.splitter import split
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore

_ECLI_RE = re.compile(r"^ECLI:NL:[A-Z]+:\d{4}:\d+$")


@dataclass(frozen=True)
class PriorityIngestResult:
    fetched: int
    parsed: int
    chunked: int
    embedded: int
    written: int


def load_eclis(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _ECLI_RE.match(line):
            raise ValueError(f"invalid ECLI on line {raw!r}")
        out.append(line)
    return out


def run_priority_ingest(
    eclis_path: Path,
    *,
    lance_path: Path,
    cache_dir: Path,
    embedder: Embedder,
    target_words: int = 500,
    overlap_words: int = 50,
) -> PriorityIngestResult:
    """Fetch → parse → chunk → embed → write for each ECLI in the list.

    No fence — priority list is curated. No subject filter either. Each
    ECLI's XML is cached to {cache_dir}/{ecli}.xml for resume/audit.
    Synchronous (sequential): priority lists are small (~20-30 ECLIs).
    """
    eclis = load_eclis(eclis_path)
    cache_dir.mkdir(parents=True, exist_ok=True)

    store = CaseStore(lance_path)
    store.open_or_create()

    fetched = parsed = chunked = embedded = written = 0
    for ecli in eclis:
        if store.contains_ecli(ecli):
            continue
        try:
            xml_path = fetch_content(ecli, cache_dir=cache_dir)
        except Exception:
            continue
        fetched += 1

        try:
            meta = parse_case(xml_path.read_bytes())
        except ParseError:
            continue
        parsed += 1

        chunks = split(meta.body, target_words=target_words, overlap_words=overlap_words)
        chunked += len(chunks)
        if not chunks:
            continue

        vectors = embedder.encode(chunks)
        embedded += len(vectors)

        rows = [
            CaseChunkRow(
                ecli=ecli,
                chunk_idx=i,
                court=meta.court,
                date=meta.date,
                zaaknummer=meta.zaaknummer,
                subject_uri=meta.subject_uri,
                modified=meta.modified,
                text=chunk,
                embedding=list(vec),
                url=meta.url,
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
        ]
        store.add_rows(rows)
        written += len(rows)

    return PriorityIngestResult(
        fetched=fetched, parsed=parsed, chunked=chunked,
        embedded=embedded, written=written,
    )
```

If `CaseMeta` doesn't expose `body` as a single attribute — confirm by reading
`caselaw_parser.CaseMeta` (§11 of the M3a spec); adapt the field access. The
exact `CaseChunkRow` field names match `src/jurist/schemas.py::CaseChunkRow`.

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/ingest/test_priority_eclis.py -v
```

Expected: PASS (the two load_eclis tests green without fixtures; the idempotency test needs the fixtures in Step 1 to be implemented — if not, mark it `@pytest.mark.skip("fixtures WIP")` and keep it in the plan for Task 24's operator verification).

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/ingest/priority_eclis.py tests/ingest/test_priority_eclis.py
git commit -m "feat(ingest): add priority_eclis.py curated-list ingest helper"
```

---

## Task 16: `caselaw.py` CLI flags — `--priority-eclis` + `--refilter-cache`

**Files:**
- Modify: `src/jurist/ingest/caselaw.py`
- Modify: `src/jurist/ingest/__main__.py` (if CLI args are routed there)
- Modify: `tests/ingest/test_caselaw_cli.py` (create if not present)

Per §8.4 of M5 spec.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/ingest/test_caselaw_cli.py`:

```python
"""M5 — CLI flags for priority + refilter-cache ingest modes."""
import subprocess, sys
from pathlib import Path


def test_caselaw_help_mentions_m5_flags():
    result = subprocess.run(
        [sys.executable, "-m", "jurist.ingest.caselaw", "--help"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--priority-eclis" in result.stdout
    assert "--refilter-cache" in result.stdout


def test_caselaw_priority_eclis_requires_existing_file(tmp_path):
    missing = tmp_path / "nope.txt"
    result = subprocess.run(
        [sys.executable, "-m", "jurist.ingest.caselaw",
         "--priority-eclis", str(missing)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/ingest/test_caselaw_cli.py -v
```

Expected: FAIL.

- [ ] **Step 3: Extend the argparse in caselaw.py**

In `src/jurist/ingest/caselaw.py` (or wherever the CLI lives), find `argparse` setup and add:

```python
parser.add_argument(
    "--priority-eclis",
    type=Path,
    default=None,
    help="Path to a text file of ECLIs to fetch + ingest bypassing list/fence stages. "
         "Idempotent. Reuses the fetch cache.",
)
parser.add_argument(
    "--refilter-cache",
    action="store_true",
    help="Skip list + fetch; re-run fence → chunk → embed → write over "
         "previously-parsed XMLs in data/cases/. Adds only delta chunks.",
)
```

In the main dispatcher, branch on these:

```python
if args.priority_eclis is not None:
    if not args.priority_eclis.exists():
        parser.error(f"--priority-eclis path does not exist: {args.priority_eclis}")
    from jurist.ingest.priority_eclis import run_priority_ingest
    result = asyncio.run(run_priority_ingest(
        args.priority_eclis,
        lance_path=settings.lance_path,
        cache_dir=settings.cases_cache_dir,
        embedder=Embedder(),
    ))
    log.info("priority ingest complete: %s", result)
    return

if args.refilter_cache:
    result = run_refilter_cache(
        cache_dir=settings.cases_cache_dir,
        lance_path=settings.lance_path,
        profile=PROFILES["huurrecht"],
        embedder=Embedder(),
    )
    log.info("refilter-cache complete: %s", result)
    return

# ... existing full-run logic ...
```

Implement `run_refilter_cache` next to the existing `run_ingest` in `caselaw.py`:

```python
def run_refilter_cache(
    *,
    cache_dir: Path,
    lance_path: Path,
    profile: CaselawProfile,
    embedder: Embedder,
    target_words: int = 500,
    overlap_words: int = 50,
) -> dict:
    """M5 — re-run fence/chunk/embed/write over already-cached XMLs.

    Skips list + fetch entirely. Emits stats dict. Expected runtime:
    ~2-4h on a 16 GB host depending on delta size.
    """
    from jurist.ingest.caselaw_parser import ParseError, parse_case
    from jurist.ingest.caselaw_profiles import passes_fence
    from jurist.ingest.splitter import split

    store = CaseStore(lance_path); store.open_or_create()
    counts = {
        "scanned": 0, "parsed": 0, "passed_fence": 0,
        "chunked": 0, "embedded": 0, "written": 0,
    }
    for xml_path in sorted(cache_dir.glob("*.xml")):
        counts["scanned"] += 1
        ecli = xml_path.stem
        if store.contains_ecli(ecli):
            continue
        try:
            meta = parse_case(xml_path.read_bytes())
        except ParseError:
            continue
        counts["parsed"] += 1

        if not passes_fence(meta.body, profile):
            continue
        counts["passed_fence"] += 1

        chunks = split(meta.body, target_words=target_words, overlap_words=overlap_words)
        counts["chunked"] += len(chunks)
        if not chunks:
            continue

        vectors = embedder.encode(chunks)
        counts["embedded"] += len(vectors)

        rows = [
            CaseChunkRow(
                ecli=ecli,
                chunk_idx=i,
                court=meta.court,
                date=meta.date,
                zaaknummer=meta.zaaknummer,
                subject_uri=meta.subject_uri,
                modified=meta.modified,
                text=chunk,
                embedding=list(vec),
                url=meta.url,
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
        ]
        store.add_rows(rows)
        counts["written"] += len(rows)
    return counts
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/ingest/test_caselaw_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add src/jurist/ingest/caselaw.py src/jurist/ingest/__main__.py tests/ingest/test_caselaw_cli.py
git commit -m "feat(ingest): add --priority-eclis + --refilter-cache CLI flags"
```

---

## Task 17: `audit_hr_coverage.py` — live rechtspraak.nl audit

**Files:**
- Create: `scripts/audit_hr_coverage.py`

One-shot, operator-run. Not a pytest target. Per §8.3 of M5 spec.

- [ ] **Step 1: Create the script**

Create `scripts/audit_hr_coverage.py`:

```python
"""M5 — live rechtspraak.nl audit for HR coverage gap (AQ3).

Purpose:
1. Query rechtspraak.nl for HR decisions with verbintenissenrecht subject,
   modified >= 2024-07-01.
2. Fetch each, apply the M5-expanded huur fence, collect signal-passing ECLIs.
3. Diff against current cases.lance HR ECLI set.
4. Verify whether ECLI:NL:HR:2024:1780 exists on rechtspraak.nl at all.
5. Write findings to docs/evaluations/2026-04-22-m5-hr-audit.md.
6. Write the priority list to data/priority_eclis/huurrecht.txt.

Run: ANTHROPIC_API_KEY not needed. Only rechtspraak.nl is touched.

Usage:  uv run python scripts/audit_hr_coverage.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from jurist.config import settings
from jurist.ingest.caselaw_fetch import fetch_content, list_eclis
from jurist.ingest.caselaw_parser import ParseError, parse_case
from jurist.ingest.caselaw_profiles import PROFILES, passes_fence
from jurist.vectorstore import CaseStore


REPORT_PATH = Path("docs/evaluations/2026-04-22-m5-hr-audit.md")
PRIORITY_LIST_PATH = Path("data/priority_eclis/huurrecht.txt")
TARGET_ECLI_FROM_REVIEWER = "ECLI:NL:HR:2024:1780"
SEARCH_URL = (
    "https://data.rechtspraak.nl/uitspraken/zoeken"
    "?subject=civielRecht_verbintenissenrecht"
    "&date=2024-07-01"    # modified >= this date; adjust param as per rechtspraak API
    "&max=1000"
    "&instantie=ECLI:NL:HR"
)


def fetch_candidate_eclis() -> list[str]:
    """Delegate to caselaw_fetch.list_eclis with an instantie filter.

    list_eclis signature (see src/jurist/ingest/caselaw_fetch.py:44) accepts
    subject, modified_from, and a max pagination cap. We add an HR-only
    instantie filter via its kwargs if supported, else post-filter the result.
    """
    all_eclis = list(list_eclis(
        subject="civielRecht_verbintenissenrecht",
        modified_from="2024-07-01",
        max_results=10_000,
    ))
    # Post-filter to HR only (instantie filter may or may not be exposed;
    # post-filter is always safe).
    return [e for e in all_eclis if e.startswith("ECLI:NL:HR:")]


def verify_ecli_exists(ecli: str) -> bool:
    """HEAD or GET https://data.rechtspraak.nl/uitspraken/content?id={ecli}"""
    url = f"https://data.rechtspraak.nl/uitspraken/content?id={urllib.parse.quote(ecli)}"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return False


def main() -> int:
    # 1. Existing HR ECLIs in index
    store = CaseStore(settings.lance_path); store.open_or_create()
    import pandas as pd
    df = store._table.search().where("ecli LIKE 'ECLI:NL:HR:%'", prefilter=True).limit(100000).select(['ecli']).to_pandas()
    existing = set(df['ecli'].tolist())

    # 2. Candidate HR ECLIs from live rechtspraak.nl
    candidates = fetch_candidate_eclis()

    # 3. Fence-filter candidates by fetching + applying huur fence
    profile = PROFILES['huurrecht']
    to_add: list[str] = []
    for ecli in candidates:
        if ecli in existing:
            continue
        try:
            xml_path = fetch_content(ecli, cache_dir=Path("data/cases"))
            meta = parse_case(xml_path.read_bytes())
        except (ParseError, Exception):
            continue
        if passes_fence(meta.body, profile):
            to_add.append(ecli)

    # 4. Specifically verify the reviewer's claimed ECLI
    target_exists = verify_ecli_exists(TARGET_ECLI_FROM_REVIEWER)
    if target_exists and TARGET_ECLI_FROM_REVIEWER not in existing and TARGET_ECLI_FROM_REVIEWER not in to_add:
        to_add.append(TARGET_ECLI_FROM_REVIEWER)

    # 5. Write priority list
    PRIORITY_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRIORITY_LIST_PATH.write_text(
        "# M5 curated huur-HR priority list — generated by scripts/audit_hr_coverage.py\n"
        f"# Generated at: {datetime.utcnow().isoformat()}Z\n"
        + "\n".join(to_add)
        + "\n",
        encoding="utf-8",
    )

    # 6. Write audit report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# M5 HR coverage audit — 2026-04-22",
        "",
        f"**Existing HR ECLIs in `cases.lance`:** {len(existing)}",
        f"**Candidate HR ECLIs from live rechtspraak.nl (≥ 2024-07-01, verbintenissenrecht):** {len(candidates)}",
        f"**Candidates passing M5-expanded huur fence:** {len(to_add)}",
        "",
        f"**Reviewer-claimed ECLI `{TARGET_ECLI_FROM_REVIEWER}` exists on rechtspraak.nl:** {target_exists}",
        "",
        "## New ECLIs on priority list",
        *[f"- {e}" for e in to_add],
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {PRIORITY_LIST_PATH} ({len(to_add)} ECLIs)")
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Fill in `fetch_candidate_eclis` following the pattern in `caselaw.py::list_eclis`. This is the only non-trivial part — read that function, then adapt.

- [ ] **Step 2: Dry-run the script against the current index (no writes yet)**

Actually — the script DOES write files; that's the point. But the test here is only "it runs without traceback". Commit the script now; operator task 23 will run it for real.

```bash
uv run python scripts/audit_hr_coverage.py --help 2>&1 | head -5
```

If argparse wasn't added: the script will just print "wrote ...". Don't run it for real yet.

- [ ] **Step 3: Commit**

```bash
uv run ruff check scripts/audit_hr_coverage.py
git add scripts/audit_hr_coverage.py
git commit -m "feat(scripts): add audit_hr_coverage.py for AQ3 priority-list generation"
```

---

## Task 18: Eval manifest + `eval_suite.py`

**Files:**
- Create: `tests/eval/questions.yaml`
- Create: `scripts/eval_suite.py`
- Delete: `scripts/eval_m4_run.py`

Per §7 of M5 spec.

- [ ] **Step 1: Create the manifest**

Create `tests/eval/questions.yaml`:

```yaml
# M5 eval manifest — driven by scripts/eval_suite.py.
#
# Each entry:
#   id: short stable identifier (used for output dir name)
#   question: the exact question string
#   expect_kind: "answer" | "insufficient_context"
#   assertions: list of DSL expressions (see scripts/eval_suite.py::AssertionRunner)

- id: Q1
  question: |
    Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?
  expect_kind: answer
  assertions:
    - decomposer.huurtype_hypothese == "onbekend"
    - contains(answer.aanbeveling, "Als ") and count_contains(answer.aanbeveling, "Als ") >= 2
    - not (contains(answer.aanbeveling, "7:248 lid 4") and contains(answer.aanbeveling, "7:253"))

- id: Q2
  question: |
    Mijn sociale huurwoning kreeg per 1 juli een verhoging van 10%, kan dat?
  expect_kind: answer
  assertions:
    - decomposer.huurtype_hypothese == "sociale"
    - not contains(answer.aanbeveling, "vrije sector")
    - contains(answer.aanbeveling, "7:253") or contains(answer.aanbeveling, "huurcommissie")

- id: Q3
  question: |
    Ik heb een conflict met mijn buurman over geluidsoverlast, wat zijn mijn opties?
  expect_kind: insufficient_context
  assertions:
    - contains(answer.insufficient_context_reason, "huurrecht")
    - contains(answer.aanbeveling, "burenrecht")

- id: Q4
  question: |
    Mijn auto is stuk, moet de autoverzekering de reparatie dekken?
  expect_kind: insufficient_context
  assertions:
    - len(answer.insufficient_context_reason) >= 40
    - contains(answer.aanbeveling, "verzekeringsrecht") or contains(answer.aanbeveling, "consumentenrecht")

- id: Q5
  question: |
    Kan ik een huurverhoging aanvechten als het beding in mijn contract vaag is geformuleerd?
  expect_kind: answer
  assertions:
    - len(answer.vergelijkbare_uitspraken) >= 1
    - contains(answer.korte_conclusie, "oneerlijk") or contains(answer.korte_conclusie, "Richtlijn 93/13") or contains(answer.korte_conclusie, "algehele vernietiging")
```

- [ ] **Step 2: Create the harness**

Create `scripts/eval_suite.py`:

```python
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
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer


MANIFEST = Path("tests/eval/questions.yaml")
OUT_DIR = Path("out/m5-eval")


def contains(text: str | None, substr: str) -> bool:
    return bool(text) and substr in text


def count_contains(text: str | None, substr: str) -> int:
    return 0 if not text else text.count(substr)


class AssertionRunner:
    """Fixed-vocabulary DSL. Not a general-purpose evaluator."""
    ALLOWED = {"contains": contains, "count_contains": count_contains, "len": len}

    def __init__(self, answer: dict, decomposer: dict) -> None:
        self.ns = {"answer": _DotDict(answer), "decomposer": _DotDict(decomposer), **self.ALLOWED}

    def check(self, expr: str) -> bool:
        # Restrict builtins — block attribute access except via _DotDict.
        return bool(eval(expr, {"__builtins__": {}}, self.ns))


class _DotDict(dict):
    def __getattr__(self, k):
        v = self[k] if k in self else None
        if isinstance(v, dict):
            return _DotDict(v)
        return v


async def run_single(q: dict) -> dict:
    buf = EventBuffer(max_history=10_000)
    task = asyncio.create_task(run_question(q["question"], buf))
    events = []
    async for ev in buf.subscribe():
        events.append(ev.model_dump())
    await task

    final = next((e for e in reversed(events) if e["type"] == "run_finished"), None)
    answer = final["data"]["final_answer"] if final else {}
    decomposer = next(
        (e["data"] for e in events
         if e["type"] == "agent_finished" and e.get("agent") == "decomposer"),
        {},
    )

    return {
        "id": q["id"],
        "question": q["question"].strip(),
        "expect_kind": q["expect_kind"],
        "actual_kind": answer.get("kind", "unknown"),
        "wall_seconds": sum(1 for _ in events) * 0,  # derived from first/last timestamps
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
    header = f"# M5 eval suite — {label} ({datetime.utcnow().isoformat()}Z)\n\n"
    table = ["| id | expect | actual | assertions | wall |",
             "|----|--------|--------|------------|------|"]
    for r in results:
        asserts_ok = sum(1 for a in r["assertions"] if a["result"])
        asserts_total = len(r["assertions"])
        kind_ok = "✓" if r["actual_kind"] == r["expect_kind"] else "✗"
        table.append(
            f"| {r['id']} | {r['expect_kind']} | {r['actual_kind']} {kind_ok} | "
            f"{asserts_ok}/{asserts_total} | — |"
        )
    per_q = []
    for r in results:
        per_q.append(f"\n## {r['id']} — {r['question']}\n")
        per_q.append(f"Expected kind: `{r['expect_kind']}`, actual: `{r['actual_kind']}`\n")
        per_q.append("\nAssertions:\n")
        for a in r["assertions"]:
            mark = "✓" if a["result"] else "✗"
            per_q.append(f"- {mark} `{a['expr']}`")
    return header + "\n".join(table) + "\n" + "\n".join(per_q) + "\n"


async def _amain(label: str) -> int:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for q in manifest:
        r = await run_single(q)
        q_dir = OUT_DIR / r["id"]; q_dir.mkdir(exist_ok=True)
        (q_dir / "trace.jsonl").write_text(
            "\n".join(json.dumps(e) for e in r["events"]), encoding="utf-8",
        )
        (q_dir / "summary.json").write_text(
            json.dumps({k: v for k, v in r.items() if k != "events"}, indent=2), encoding="utf-8",
        )
        results.append(r)

    report_path = Path(f"docs/evaluations/2026-04-22-m5-suite-{label}.md")
    report_path.write_text(render_summary_md(results, label), encoding="utf-8")

    passed = sum(1 for r in results if r["actual_kind"] == r["expect_kind"]
                 and all(a["result"] for a in r["assertions"]))
    print(f"passed {passed}/{len(results)}; report: {report_path}")
    return 0 if passed == len(results) else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--label", choices=["pre", "post"], required=True)
    args = p.parse_args()
    return asyncio.run(_amain(args.label))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Delete `eval_m4_run.py`**

```bash
git rm scripts/eval_m4_run.py
```

- [ ] **Step 4: Smoke-check the manifest parses**

```bash
uv run python -c "import yaml; print(len(yaml.safe_load(open('tests/eval/questions.yaml'))))"
```

Expected: `5`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check scripts/eval_suite.py
git add scripts/eval_suite.py tests/eval/questions.yaml
git add -u  # picks up the rm of eval_m4_run.py
git commit -m "feat(eval): manifest-driven eval_suite.py; delete eval_m4_run.py"
```

---

## Task 19: Frontend — `InsufficientContextBanner` + AnswerPanel kind discrimination

**Files:**
- Create: `web/src/components/InsufficientContextBanner.tsx`
- Modify: `web/src/components/AnswerPanel.tsx`
- Modify: `web/src/types/answer.ts` (or wherever `StructuredAnswer` is typed)

Per §9 of M5 spec.

- [ ] **Step 1: Extend the frontend type**

In `web/src/types/answer.ts` (or wherever `StructuredAnswer` is defined), replace:

```ts
export type StructuredAnswer = {
  korte_conclusie: string
  relevante_wetsartikelen: WetArtikelCitation[]
  vergelijkbare_uitspraken: UitspraakCitation[]
  aanbeveling: string
}
```

with:

```ts
export type StructuredAnswerBase = {
  korte_conclusie: string
  relevante_wetsartikelen: WetArtikelCitation[]
  vergelijkbare_uitspraken: UitspraakCitation[]
  aanbeveling: string
}
export type StructuredAnswer =
  | (StructuredAnswerBase & { kind: "answer"; insufficient_context_reason: null })
  | (StructuredAnswerBase & { kind: "insufficient_context"; insufficient_context_reason: string })
```

- [ ] **Step 2: Create the banner component**

Create `web/src/components/InsufficientContextBanner.tsx`:

```tsx
import type { StructuredAnswer } from "../types/answer"

type Props = Extract<StructuredAnswer, { kind: "insufficient_context" }>

export function InsufficientContextBanner(props: Props) {
  return (
    <div className="p-4 border border-amber-400 bg-amber-50 rounded">
      <h3 className="text-amber-900 font-semibold mb-2">
        Geen voldoende bronnen voor deze vraag
      </h3>
      <p className="text-amber-900">{props.korte_conclusie}</p>
      <p className="text-amber-800 text-sm mt-2 italic">
        {props.insufficient_context_reason}
      </p>
      <p className="text-amber-900 mt-3">{props.aanbeveling}</p>
    </div>
  )
}
```

- [ ] **Step 3: Add kind-guard to AnswerPanel**

In `web/src/components/AnswerPanel.tsx`, at the top of the render body:

```tsx
import { InsufficientContextBanner } from "./InsufficientContextBanner"

// ... inside the component ...
if (finalAnswer && finalAnswer.kind === "insufficient_context") {
  return <InsufficientContextBanner {...finalAnswer} />
}
// ... existing answer rendering ...
```

- [ ] **Step 4: Typecheck**

```bash
cd web && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Dev smoke**

```bash
cd web && npm run dev &
# In another shell: load http://localhost:5173 and ensure the app still builds.
# Manual smoke only; no automated FE test in this task.
```

- [ ] **Step 6: Commit**

```bash
cd web && git add -u src/ && cd ..
git add web/src/components/InsufficientContextBanner.tsx
git commit -m "feat(web): add InsufficientContextBanner + discriminate AnswerPanel on kind"
```

---

## Task 20: Integration test — M5 locked question

**Files:**
- Create: `tests/integration/test_m5_e2e.py`

RUN_E2E-gated. Per §11.4 of M5 spec.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_m5_e2e.py`:

```python
"""M5 — end-to-end against real Anthropic + real KG + real LanceDB.

Gated by RUN_E2E=1. Asserts AQ1 branching and no procedure-stacking on the
locked question.
"""
import os
import re
import pytest
from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer


@pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="RUN_E2E=1 required")
@pytest.mark.asyncio
async def test_m5_locked_question_has_branching_and_no_stacking():
    import asyncio
    question = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
    buf = EventBuffer(max_history=10_000)
    task = asyncio.create_task(run_question(question, buf))
    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    await task

    final = next(e for e in reversed(events) if e.type == "run_finished")
    answer = final.data["final_answer"]

    assert answer["kind"] == "answer"

    decomp = next(e.data for e in events if e.type == "agent_finished" and e.agent == "decomposer")
    assert decomp["huurtype_hypothese"] == "onbekend"

    # Branching structure in aanbeveling
    aanbeveling = answer["aanbeveling"]
    als_count = len(re.findall(r"\bAls ", aanbeveling))
    assert als_count >= 2, f"expected ≥2 'Als' branches, got {als_count}: {aanbeveling!r}"

    # No procedure stacking
    assert not (
        "7:248 lid 4" in aanbeveling and "7:253" in aanbeveling
    ), f"procedure stacking detected: {aanbeveling!r}"
```

- [ ] **Step 2: Run (requires ANTHROPIC_API_KEY + data)**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m5_e2e.py -v
```

Expected: PASS. If assertion fails, the synth's AQ1 rule isn't firing — inspect `out/` dump or adjust the prompt, then re-run.

- [ ] **Step 3: Commit**

```bash
uv run ruff check tests/integration/test_m5_e2e.py
git add tests/integration/test_m5_e2e.py
git commit -m "test(integration): M5 locked-question e2e — branching + no stacking"
```

---

## Task 21: Integration test — out-of-scope refusal

**Files:**
- Create: `tests/integration/test_m5_out_of_scope_e2e.py`

Per §11.4 of M5 spec.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_m5_out_of_scope_e2e.py`:

```python
"""M5 — out-of-scope question returns structured refusal via run_finished."""
import os
import asyncio
import pytest
from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer


@pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="RUN_E2E=1 required")
@pytest.mark.asyncio
async def test_out_of_scope_burenrecht_refusal():
    question = "Ik heb een conflict met mijn buurman over geluidsoverlast, wat zijn mijn opties?"
    buf = EventBuffer(max_history=10_000)
    task = asyncio.create_task(run_question(question, buf))
    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    await task

    # Terminal must be run_finished, not run_failed
    assert events[-1].type == "run_finished", f"got {events[-1].type}"

    answer = events[-1].data["final_answer"]
    assert answer["kind"] == "insufficient_context"
    assert answer["relevante_wetsartikelen"] == []
    assert answer["vergelijkbare_uitspraken"] == []

    reason = answer["insufficient_context_reason"]
    assert "huurrecht" in reason.lower()

    # The aanbeveling should suggest burenrecht
    assert "burenrecht" in answer["aanbeveling"].lower()
```

- [ ] **Step 2: Run**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m5_out_of_scope_e2e.py -v
```

Expected: PASS. If `run_failed` terminates instead, one of the retrievers / decomposer is throwing on the off-topic question — inspect the event stream and add a domain-specific prompt hint to the decomposer to handle "not huur at all" gracefully.

- [ ] **Step 3: Commit**

```bash
uv run ruff check tests/integration/test_m5_out_of_scope_e2e.py
git add tests/integration/test_m5_out_of_scope_e2e.py
git commit -m "test(integration): M5 out-of-scope question → insufficient_context refusal"
```

---

## Task 22: Update CLAUDE.md for M5

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the "What this project is" paragraph**

Find and extend the "Current state:" paragraph. Append after the existing M4 narrative:

```markdown

M5 adds segment-aware procedure routing, EU-directive escalation, graceful refusal, and a broader huur case coverage. Decomposer emits `huurtype_hypothese`; statute/case retrievers emit `low_confidence`; synthesizer emits `StructuredAnswer.kind ∈ {answer, insufficient_context}`. Fence expansion (`huurverhoging`, `huurprijs`, `indexering`, `oneerlijk beding`, `onredelijk beding`) + curated priority-ECLI top-up improve HR surface on huur questions. Five-question eval suite (`scripts/eval_suite.py`) runs against `tests/eval/questions.yaml` and emits `docs/evaluations/2026-04-22-m5-suite-{pre,post}.md`.
```

- [ ] **Step 2: Update "What's fake vs. real after M5" table**

Find the M4 table and replace with:

```markdown
### What's fake vs. real after M5

| Component | State | Notes |
|---|---|---|
| `decomposer` | **Real** — Haiku forced-tool `emit_decomposition`, emits `huurtype_hypothese`, one-regen-then-hard-fail | — |
| `statute_retriever` | **Real** — Sonnet tool-use loop over 218-node KG (5 tools); emits `low_confidence` when `<3` selected | — |
| `case_retriever` | **Real** — bge-m3 + LanceDB top-150→20 ECLIs + Haiku rerank to 3; emits `low_confidence` when all top-3 similarity `<0.55` | — |
| `synthesizer` | **Real** — Sonnet streaming `messages.stream()`; early-branch refusal when both retrievers flag low-confidence; forced-tool `emit_answer` with `allow_refusal=True` schema; per-request `Literal[...]` enums on `article_id`/`bwb_id`/`ecli` (when `kind="answer"`); post-hoc `verify_citations` (skipped when `kind="insufficient_context"`); one-regen-then-hard-fail to `run_failed{citation_grounding}` | — |
| `validator_stub` | Permanent stub — always returns `valid=True` | — (real validator is v2) |
```

- [ ] **Step 3: Update "Commands" section**

Add near the other eval/audit commands:

```markdown
- Run eval suite: `uv run python scripts/eval_suite.py --label {pre|post}` — manifest-driven; writes `docs/evaluations/2026-04-22-m5-suite-{pre,post}.md`.
- Run HR coverage audit: `uv run python scripts/audit_hr_coverage.py` — emits audit doc + priority list.
- Priority-ECLI ingest: `uv run python -m jurist.ingest.caselaw --priority-eclis data/priority_eclis/huurrecht.txt`.
- Refilter-cache ingest: `uv run python -m jurist.ingest.caselaw --refilter-cache`.
```

- [ ] **Step 4: Update the "Environment quirks" event-count note**

Find the "Full run emits ~700 events" line and amend it:

```markdown
- Full run emits ~700 events on the locked huur question post-M5 (similar ceiling to M4). Refusal runs (out-of-scope questions) emit ~150-250 events (no `citation_resolved`, shorter `answer_delta` replay).
```

- [ ] **Step 5: Commit**

```bash
uv run ruff check .  # doc-only; runs clean
git add CLAUDE.md
git commit -m "docs(claude): reflect M5 — huurtype, low_confidence, refusal kind, eval suite"
```

---

## Task 23: [OPERATOR] Run HR coverage audit + commit priority list

**Precondition:** Task 17 (`audit_hr_coverage.py`) committed. Working tree clean on the M5 branch.

**Run:**

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
mkdir -p data/priority_eclis docs/evaluations
uv run python scripts/audit_hr_coverage.py
```

**Expected outputs:**
- `data/priority_eclis/huurrecht.txt` populated with the ECLIs that passed the expanded fence.
- `docs/evaluations/2026-04-22-m5-hr-audit.md` with counts + finding on ECLI:NL:HR:2024:1780.

**Commit:**

```bash
git add data/priority_eclis/huurrecht.txt docs/evaluations/2026-04-22-m5-hr-audit.md
git commit -m "data: commit M5 priority-ECLI list + HR coverage audit"
```

If the audit reveals the reviewer-claimed ECLI doesn't exist, keep it out of the priority list — the audit doc records that fact, which is more valuable than fabricating coverage.

---

## Task 24: [OPERATOR] Run `--priority-eclis` + `--refilter-cache`

**Precondition:** Task 23 committed. `data/cases/*.xml` parse cache exists (from M3a).

**Run the priority ingest:**

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run python -m jurist.ingest.caselaw \
    --priority-eclis data/priority_eclis/huurrecht.txt -v 2>&1 | tee /tmp/m5-priority.log
```

Expected stdout: per-ECLI fetch → parse → chunk → embed → write lines; final summary line.

**Run the refilter-cache:**

```bash
uv run python -m jurist.ingest.caselaw --refilter-cache -v 2>&1 | tee /tmp/m5-refilter.log
```

Expected: scans the ~19.8k XMLs in `data/cases/`, filters with expanded fence, adds delta chunks. Runtime 2-4h on a 16GB machine.

**Verify:**

```bash
uv run python -c "
from jurist.vectorstore import CaseStore
from jurist.config import settings
store = CaseStore(settings.lance_path); store.open_or_create()
print('rows:', store.row_count())
tbl = store._table
df = tbl.search().where(\"ecli LIKE 'ECLI:NL:HR:%'\", prefilter=True).limit(100000).select(['ecli']).to_pandas()
print('distinct HR ECLIs:', df['ecli'].nunique())
"
```

Expected: distinct HR ECLIs increased by ≥5 vs pre-M5 (33).

**No commit required** — `data/lancedb/cases.lance/` is git-ignored. Paste the verify output into a comment on whatever review this M5 branch is attached to.

---

## Task 25: [OPERATOR] Run eval suite pre + post

**Precondition:** Tasks 1-22 committed. Task 24 completed (data delta applied locally).

**Step 1: Pre run on master (baseline).**

```bash
git stash        # set aside any working-tree
git checkout master
export PATH="/c/Users/totti/.local/bin:$PATH"
# The eval_suite.py from M5 doesn't exist on master; skip pre via M4 flavour:
# On master, run the existing scripts/eval_m4_run.py on Q1 only, copy summary/answer into docs/evaluations/2026-04-22-m5-suite-pre.md manually.
# If master has no suite harness, the pre doc is "baseline = M4 eval from docs/evaluations/2026-04-22-m4-e2e-run.md" — link to it.
```

**Practical approach:** The *pre* baseline is the existing M4 eval doc; write a thin `docs/evaluations/2026-04-22-m5-suite-pre.md` that points to `2026-04-22-m4-e2e-run.md` as the pre-baseline for Q1 and notes that Q2-Q5 were not run on master. This is honest — the suite didn't exist pre-M5.

```bash
git checkout m5-answer-quality    # back to M5 branch
git stash pop                     # restore worktree
cat > docs/evaluations/2026-04-22-m5-suite-pre.md << 'EOF'
# M5 eval suite — pre-merge baseline

**Pre-M5, only Q1 (locked question) was evaluated.** See `2026-04-22-m4-e2e-run.md` for that run. Q2–Q5 are new M5 questions; they had no baseline on master. Post-merge data at `2026-04-22-m5-suite-post.md`.
EOF
git add docs/evaluations/2026-04-22-m5-suite-pre.md
git commit -m "docs(eval): M5 suite pre-baseline marker (points to M4 eval doc)"
```

**Step 2: Post run on M5 branch.**

```bash
uv run python scripts/eval_suite.py --label post
```

Expected outputs:
- `out/m5-eval/{Q1,Q2,Q3,Q4,Q5}/*.json`
- `docs/evaluations/2026-04-22-m5-suite-post.md`

Verify the post doc shows all 5 questions with kind matching and assertions passing (✓). If any fail, don't commit yet — fix the underlying behaviour and re-run.

**Step 3: Commit post doc.**

```bash
git add docs/evaluations/2026-04-22-m5-suite-post.md
git commit -m "docs(eval): M5 suite post-run — 5 questions across answer + refusal kinds"
```

---

## Task 26: Final acceptance check

**Files:** none — verification only.

- [ ] **Step 1: Unit tests green**

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run pytest -v 2>&1 | tail -40
```

Expected: "passed" line; zero failures.

- [ ] **Step 2: Integration tests green (RUN_E2E=1)**

```bash
RUN_E2E=1 uv run pytest tests/integration/ -v 2>&1 | tail -30
```

Expected: all four integration tests PASS (M3b, M4, M5 locked, M5 out-of-scope).

- [ ] **Step 3: Ruff clean**

```bash
uv run ruff check .
```

Expected: "All checks passed!"

- [ ] **Step 4: Data verification**

```bash
uv run python -c "
from jurist.vectorstore import CaseStore
from jurist.config import settings
store = CaseStore(settings.lance_path); store.open_or_create()
tbl = store._table
df = tbl.search().where(\"ecli LIKE 'ECLI:NL:HR:%'\", prefilter=True).limit(100000).select(['ecli']).to_pandas()
print('M5 HR count:', df['ecli'].nunique())
"
```

Expected: ≥38 (was 33 pre-M5 — task 24 added ≥5).

- [ ] **Step 5: Spec + CLAUDE.md coherent**

```bash
grep -n "M5" CLAUDE.md | head -20
grep -n "kind\|huurtype_hypothese\|low_confidence\|insufficient_context" docs/superpowers/specs/2026-04-17-jurist-v1-design.md | head
```

Expected: both files mention M5 additions; no inconsistencies with the current code.

- [ ] **Step 6: Merge to master**

At this point the branch is ready. Either open a PR (`gh pr create`) or merge directly per the project's cadence.

```bash
git log --oneline master..m5-answer-quality | head -30
```

Expected: ~26 commits, one per task.

---

*End of plan.*
