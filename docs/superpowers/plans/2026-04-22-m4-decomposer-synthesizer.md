# M4 — Decomposer + Synthesizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the M0 fake decomposer + synthesizer into real Claude-powered agents. Decomposer: Haiku forced-tool `emit_decomposition`, one regen then hard-fail. Synthesizer: Sonnet streaming `messages.stream()` for live Dutch reasoning (`agent_thinking`), forced-tool `emit_answer` with per-request `Literal[...]` enums on `article_id`/`bwb_id`/`ecli`, post-hoc whitespace-normalized quote verification (40–500 char bounds), regen-once-then-hard-fail to `run_failed{reason:"citation_grounding"}`. Preserve the M0 UX contract via synthetic `answer_delta` replay after the tool call returns.

**Architecture:** Two forced-tool agents, one new pure-helper module for the synthesizer (`synthesizer_tools.py`), one new streaming mock (`MockStreamingClient`). Three closed-set enforcement layers for synthesis: (1) JSON-Schema `enum` on IDs → SDK rejects out-of-set, (2) Pydantic `StructuredAnswer.model_validate` → catches schema-bypass attempts, (3) `verify_citations()` strict-substring check → catches quote hallucination. One regen with a Dutch advisory that enumerates failed citations; second failure hard-fails. Schema grows: `WetArtikelCitation` adds `article_id`, `CitedCase` adds `chunk_text` (the full best-chunk text used as the quote-verification surface). No frontend work, no orchestrator restructuring beyond adding two try/except blocks mirroring M3b's pattern.

**Tech Stack:** Python 3.11, `anthropic` AsyncClient (streaming + non-streaming), `pydantic`, `pytest` + `pytest-asyncio`. No new runtime dependencies.

**Authoritative spec:** `docs/superpowers/specs/2026-04-22-m4-decomposer-synthesizer-design.md`. When a task references a rule ("per §4.4"), read that section before implementing — the spec is the source of truth for WHAT; this plan is HOW.

**Preflight:**
- Working tree clean on `master`. The M4 design spec (`2026-04-22-m4-...`) is already committed; the parent-spec amendment is Task 0 of this plan.
- `ANTHROPIC_API_KEY` must be set in `.env` or the environment for the integration test (Task 17) and manual smoke tests; unit tests run offline.
- `data/kg/huurrecht.json` and `data/lancedb/cases.lance` must exist (from M1 + M3a) for the integration test and manual API smoke; unit tests create their own fixtures.
- bge-m3 is already cached in `~/.cache/huggingface/hub/` from M3a; no fresh download.
- Environment quirks (CLAUDE.md): `uv` at `C:\Users\totti\.local\bin` may need `export PATH="/c/Users/totti/.local/bin:$PATH"`. API port is 8766. Git LF→CRLF warnings on commit are benign.

**Conventions across all tasks:**
- One task ≈ one commit. Commit at the end of each task after tests pass and `uv run ruff check .` is clean.
- Test-first: write failing test → see it fail → implement → see it pass → commit.
- `tests/fixtures/mock_llm.py` is the house convention for LLM mocks — this plan extends it rather than adding parallel files.
- Do NOT use `--no-verify` or bypass pre-commit hooks. If a hook fails, diagnose and re-commit.

---

## Task 0: Amend parent spec for M4

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`

Prerequisite commit. Documents the schema changes (article_id on `WetArtikelCitation`, chunk_text on `CitedCase`), the regen policy on the decomposer, the grounding specifics, the three new env vars, and five decision-log entries. Follows the pattern M3b established (`3ae94f6 docs(spec): amend parent spec for M3b`).

- [ ] **Step 1: Append regen policy to §5.1 Decomposer**

Find the decomposer's **Implementation** paragraph and append after "Haiku. System prompt marked cacheable.":

```markdown
One regen with a Dutch advisory appended to the user message on first failure, then hard-fail to `DecomposerFailedError` → `run_failed{reason:"decomposition"}`. Consistent with M3b rerank and M4 synthesizer.
```

- [ ] **Step 2: Add `chunk_text` to `CitedCase` in §5.3**

Grep for the current definition:

```bash
grep -n "class CitedCase" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
```

Replace:

```python
class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str                    # ISO 8601
    snippet: str
    similarity: float
    reason: str                  # from the Haiku rerank pass
    url: str                     # uitspraken.rechtspraak.nl/...
```

with:

```python
class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str                    # ISO 8601
    snippet: str                 # 400-char excerpt; rerank-prompt context
    similarity: float
    reason: str                  # from the Haiku rerank pass
    chunk_text: str              # M4: full best-chunk text (~500 words); synthesizer quote-verification surface
    url: str                     # uitspraken.rechtspraak.nl/...
```

- [ ] **Step 3: Add `article_id` to `WetArtikelCitation` in §5.4**

Replace:

```python
class WetArtikelCitation(BaseModel):
    bwb_id: str                  # per-request Literal over cited_articles
    article_label: str
    quote: str                   # verbatim excerpt from the article text
    explanation: str
```

with:

```python
class WetArtikelCitation(BaseModel):
    article_id: str              # M4: per-request Literal over cited_articles — unambiguous post-hoc resolver
    bwb_id: str                  # per-request Literal over cited_articles — belt-and-braces
    article_label: str
    quote: str                   # verbatim excerpt (NFC + whitespace-normalized substring of article body_text); 40–500 chars
    explanation: str
```

- [ ] **Step 4: Tighten §5.4 Grounding mechanism**

Find the **Grounding mechanism** bullet list and replace the second bullet:

```markdown
- After generation, every citation is resolved against the KG / vector store to confirm both the ID exists and the `quote` appears in the source text.
```

with:

```markdown
- After generation, `verify_citations()` (a) confirms each `article_id`/`ecli` is in the candidate set (catches schema-bypass), and (b) confirms each `quote` appears in the source text — NFC-normalize both sides, collapse whitespace runs to single spaces, strict case-sensitive substring. Quote length bounds 40–500 characters, enforced in the tool schema and re-checked post-hoc. Quotes for uitspraken verify against `CitedCase.chunk_text` (the full best-chunk text, not the 400-char `snippet`).
```

- [ ] **Step 5: Update §6.3 event types table**

Find the `run_failed` row:

```markdown
| `run_failed` | orchestrator | `{ reason, detail }` |
```

Replace with:

```markdown
| `run_failed` | orchestrator | `{ reason, detail }` — `reason ∈ {"llm_error", "case_rerank", "decomposition", "citation_grounding"}` |
```

- [ ] **Step 6: Tighten §11 M4 Done-when**

Find the current M4 "Grounding guard test" paragraph:

```markdown
- Grounding guard test (unit-level on the synthesizer): given `cited_articles = [A, B, C]` and a prompt that attempts to steer toward an imagined citation `D`, the per-request `Literal` enum blocks it at schema-validation time; the synthesizer produces a valid output or, after one regeneration still failing, the run emits `run_failed { reason: "citation_grounding" }` and the UI shows the error. No silent hallucination in either path.
```

Replace with:

```markdown
- Grounding guard test (`tests/agents/test_synthesizer_grounding.py`) asserts three layers: (a) `build_synthesis_tool_schema(...)`'s `article_id.enum` and `ecli.enum` equal exactly the candidate set; (b) `verify_citations()` fed a tampered `StructuredAnswer` whose IDs are out of set returns `FailedCitation(reason="unknown_id")`, not `KeyError`; (c) agent end-to-end with a mock that produces imagined-ID tool_inputs twice in a row raises `CitationGroundingFailedError` (→ `run_failed{reason:"citation_grounding"}` at the orchestrator level). No silent success.
```

- [ ] **Step 7: Add three env vars to §13**

After the `JURIST_CASELAW_RERANK_SNIPPET_CHARS` line, append:

```markdown
- `JURIST_MODEL_DECOMPOSER` — default `claude-haiku-4-5-20251001`. Forced-tool structured output; small task, small model.
- `JURIST_MODEL_SYNTHESIZER` — default `claude-sonnet-4-6`. Dutch structured generation with closed-set citations.
- `JURIST_SYNTHESIZER_MAX_TOKENS` — default `8192`. Budget for reasoning prose + structured output combined.
```

- [ ] **Step 8: Add five rows to §15 decisions log**

Append after row #18:

```markdown
| 19 | Synthesizer UX = streaming `messages.stream()` for live `agent_thinking` + synthetic `answer_delta` replay after tool-call returns | Non-streaming + replay only; real-tool-JSON streaming; no replay (empty AnswerPanel during synth) | Only hybrid keeps both panels behaving naturally. Real tool-input JSON isn't user-presentable; replay mirrors M0 UX contract. |
| 20 | `WetArtikelCitation` carries both `article_id` and `bwb_id`; both closed-set enums | Keep `bwb_id` only (spec-faithful); replace `bwb_id` with `article_id` | `article_id` gives unambiguous post-hoc resolution — quote must appear in the specific article, not any article in the BWB. Additive keeps frontend `CitationLink` unchanged. |
| 21 | Quote verification = NFC + whitespace-normalized + case-sensitive strict substring; 40–500 char bounds | Fuzzy (Levenshtein); strict byte match; case-insensitive | Preserves "verbatim" claim while tolerating LLM reformatting. Bounds keep citations substantive without "quote the whole article." |
| 22 | Decomposer mirrors synthesizer/rerank regen policy (one regen then hard-fail) | Zero regen (trust schema); deterministic fallback | Consistent across the three forced-tool agents. Silent fallback contradicts decision #18 philosophy. |
| 23 | `verify_citations()` returns `FailedCitation(reason="unknown_id")` on out-of-set IDs, not `KeyError` | Raise KeyError; assert IDs pre-verify | Makes the helper robust to schema-bypass (grounding guard test); turns an invariant into a regen-compatible signal. |
```

- [ ] **Step 9: Verify edits**

```bash
grep -n "chunk_text" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "article_id: str" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "JURIST_MODEL_SYNTHESIZER" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "test_synthesizer_grounding" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "unknown_id" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
```

Expected: each grep returns at least one hit.

- [ ] **Step 10: Commit**

```bash
git add docs/superpowers/specs/2026-04-17-jurist-v1-design.md
git commit -m "docs(spec): amend parent spec for M4 — article_id, chunk_text, grounding specifics, env vars, decisions #19-23"
```

---

## Task 1: Config settings + .env.example

**Files:**
- Modify: `src/jurist/config.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

Three new settings; no `RunContext` change (decomposer + synthesizer use only `ctx.llm`).

- [ ] **Step 1: Write failing test**

Edit `tests/test_config.py`. Append after the existing tests:

```python
def test_m4_settings_defaults():
    from jurist.config import settings

    assert settings.model_decomposer == "claude-haiku-4-5-20251001"
    assert settings.model_synthesizer == "claude-sonnet-4-6"
    assert settings.synthesizer_max_tokens == 8192
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py::test_m4_settings_defaults -v
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'model_decomposer'`.

- [ ] **Step 3: Add settings to config.py**

Edit `src/jurist/config.py`. After the `# M3b — case retriever` block (ending with `caselaw_rerank_snippet_chars`), append inside `Settings`:

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

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_config.py::test_m4_settings_defaults -v
```

Expected: PASS.

- [ ] **Step 5: Update .env.example**

Append to `.env.example`:

```bash

# --- M4: decomposer + synthesizer -------------------------------------

# Decomposer model. Small structured-output task.
# JURIST_MODEL_DECOMPOSER=claude-haiku-4-5-20251001

# Synthesizer model. Dutch structured generation with closed-set citations.
# JURIST_MODEL_SYNTHESIZER=claude-sonnet-4-6

# Budget for synthesizer reasoning prose + structured output combined.
# Tool-input payload is typically ≤2kT; thinking can add another 1-2kT.
# JURIST_SYNTHESIZER_MAX_TOKENS=8192
```

- [ ] **Step 6: Commit**

```bash
git add src/jurist/config.py .env.example tests/test_config.py
git commit -m "feat(config): M4 settings — model_decomposer, model_synthesizer, synthesizer_max_tokens"
```

---

## Task 2: Schema changes — `WetArtikelCitation.article_id` + `CitedCase.chunk_text`

**Files:**
- Modify: `src/jurist/schemas.py`
- Modify: `src/jurist/fakes.py`
- Test: `tests/test_schemas.py` (create if absent; else extend)

Two additive fields. Updates the fakes so existing tests still construct valid Pydantic instances.

- [ ] **Step 1: Write failing test**

Create `tests/test_schemas.py` (or extend). Add:

```python
"""Regression tests for M4 schema additions."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurist.schemas import CitedCase, WetArtikelCitation


def test_wetartikel_citation_requires_article_id():
    # article_id is required — missing it raises ValidationError.
    with pytest.raises(ValidationError, match="article_id"):
        WetArtikelCitation(
            bwb_id="BWBR0005290",
            article_label="Boek 7, Artikel 248",
            quote="a" * 40,
            explanation="b" * 40,
        )


def test_wetartikel_citation_accepts_article_id():
    cit = WetArtikelCitation(
        article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        bwb_id="BWBR0005290",
        article_label="Boek 7, Artikel 248",
        quote="a" * 40,
        explanation="b" * 40,
    )
    assert cit.article_id.endswith("/Artikel248")


def test_cited_case_requires_chunk_text():
    with pytest.raises(ValidationError, match="chunk_text"):
        CitedCase(
            ecli="ECLI:NL:HR:2020:1234",
            court="Hoge Raad",
            date="2020-09-11",
            snippet="...",
            similarity=0.8,
            reason="Leidende uitspraak.",
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
        )


def test_cited_case_accepts_chunk_text():
    case = CitedCase(
        ecli="ECLI:NL:HR:2020:1234",
        court="Hoge Raad",
        date="2020-09-11",
        snippet="...",
        similarity=0.8,
        reason="Leidende uitspraak.",
        chunk_text="full chunk body " * 50,
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
    )
    assert len(case.chunk_text) > 400
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: FAIL on every test — `article_id` / `chunk_text` not on models.

- [ ] **Step 3: Add fields to schemas**

Edit `src/jurist/schemas.py`. Replace the `CitedCase` class:

```python
class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str
    snippet: str
    similarity: float
    reason: str
    chunk_text: str              # M4: full best-chunk text; synthesizer quote-verification surface
    url: str
```

Replace the `WetArtikelCitation` class:

```python
class WetArtikelCitation(BaseModel):
    article_id: str              # M4: fully-qualified; closed-set enum
    bwb_id: str
    article_label: str
    quote: str
    explanation: str
```

- [ ] **Step 4: Update fakes for the new fields**

Edit `src/jurist/fakes.py`. Find each `CitedCase(` in `FAKE_CASES` and add `chunk_text=` before `url=`. Use a synthetic ~600-char chunk body so the fixture stays realistic.

Replace the three FAKE_CASES entries with:

```python
FAKE_CASES: list[CitedCase] = [
    CitedCase(
        ecli="ECLI:NL:HR:2020:1234",
        court="Hoge Raad",
        date="2020-09-11",
        snippet="De verhuurder mag de huur niet eenzijdig met een hoger percentage ...",
        similarity=0.87,
        reason="Leidende uitspraak over maximale huurverhoging bij gereguleerde huur.",
        chunk_text=(
            "De verhuurder mag de huur niet eenzijdig met een hoger percentage "
            "verhogen dan het door de minister vastgestelde maximum. Een "
            "voorstel dat dit maximum overschrijdt, is in beginsel niet "
            "toegestaan bij gereguleerde huur. De huurder kan binnen zes weken "
            "bezwaar maken bij de verhuurder, en vervolgens het geschil "
            "voorleggen aan de Huurcommissie. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
    ),
    CitedCase(
        ecli="ECLI:NL:RBAMS:2022:5678",
        court="Rechtbank Amsterdam",
        date="2022-03-14",
        snippet="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
        similarity=0.81,
        reason="Feitelijk zeer vergelijkbaar — huurder bezwaart succesvol tegen 15% verhoging.",
        chunk_text=(
            "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig. "
            "De verhuurder heeft onvoldoende onderbouwd waarom een verhoging "
            "van deze omvang gerechtvaardigd is. De rechtbank wijst het "
            "voorstel af en oordeelt dat de huurder niet gehouden is de "
            "verhoogde huur te betalen. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
    ),
    CitedCase(
        ecli="ECLI:NL:GHARL:2023:9012",
        court="Gerechtshof Arnhem-Leeuwarden",
        date="2023-06-22",
        snippet="Bij geliberaliseerde huur geldt een andere norm, maar de redelijkheid ...",
        similarity=0.74,
        reason="Relevant voor onderscheid gereguleerd / geliberaliseerd.",
        chunk_text=(
            "Bij geliberaliseerde huur geldt een andere norm, maar de "
            "redelijkheid blijft leidend. Een percentage dat in gereguleerde "
            "huur ontoelaatbaar zou zijn, kan in geliberaliseerde huur "
            "verdedigbaar zijn mits de huurovereenkomst dit toelaat en de "
            "verhoging aansluit bij marktniveau. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:GHARL:2023:9012",
    ),
]
```

Replace the two `WetArtikelCitation` entries in `FAKE_ANSWER.relevante_wetsartikelen` — add `article_id=` using the existing M0 article paths:

```python
    relevante_wetsartikelen=[
        WetArtikelCitation(
            article_id=_A248,
            bwb_id=BWB_BW7,
            article_label="Boek 7, Artikel 248",
            quote="De verhuurder kan tot aan het tijdstip dat ...",
            explanation=(
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse huurverhoging "
                "voor te stellen binnen de wettelijke kaders."
            ),
        ),
        WetArtikelCitation(
            article_id=_UHW10,
            bwb_id=BWB_UHW,
            article_label="Uhw, Artikel 10",
            quote="Het puntenstelsel bepaalt ...",
            explanation=(
                "Stelt het maximale percentage vast via het puntenstelsel; "
                "15% ligt daar ruim boven voor gereguleerde huur."
            ),
        ),
    ],
```

- [ ] **Step 5: Run schema tests to verify pass**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: PASS on all four.

- [ ] **Step 6: Run full suite to catch fallout**

```bash
uv run pytest -v
```

Expected: all green. If any test that pattern-matches `WetArtikelCitation` or `CitedCase` field names fails, update it one-line at a time to include the new fields.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/schemas.py src/jurist/fakes.py tests/test_schemas.py
git commit -m "feat(schemas): M4 — WetArtikelCitation.article_id, CitedCase.chunk_text"
```

---

## Task 3: `CaseCandidate.chunk_text` + thread through `case_retriever`

**Files:**
- Modify: `src/jurist/agents/case_retriever_tools.py`
- Modify: `src/jurist/agents/case_retriever.py`
- Modify: `tests/agents/test_case_retriever_tools.py`
- Modify: `tests/agents/test_case_retriever.py`

The `CaseCandidate` dataclass currently carries only the 400-char `snippet` and is what the case retriever hands to rerank. For M4 the synthesizer needs the **full best-chunk text** as its quote-verification surface. Separate the two concerns.

- [ ] **Step 1: Add failing tests for the helper**

Edit `tests/agents/test_case_retriever_tools.py`. Append:

```python
def test_candidate_carries_full_chunk_text(tmp_path):
    """CaseCandidate.chunk_text is the full row text; .snippet is the truncated version."""
    from jurist.agents.case_retriever_tools import retrieve_candidates
    from jurist.schemas import CaseChunkRow
    from jurist.vectorstore import CaseStore

    class _FixedEmbedder:
        def encode(self, texts, *, batch_size=32):
            import numpy as np
            return np.zeros((len(texts), 1024), dtype=np.float32)

    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()

    long_body = "paragraaf " * 200          # ~1800 chars; well over snippet_chars
    vec = [0.0] * 1024
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:TEST:1",
        chunk_idx=0,
        court="Rb Test", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text=long_body,
        embedding=vec,
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:TEST:1",
    )])

    cands = retrieve_candidates(
        store=store, embedder=_FixedEmbedder(),
        query="huurverhoging",
        chunks_top_k=10, eclis_limit=5, snippet_chars=400,
    )

    assert len(cands) == 1
    c = cands[0]
    assert c.chunk_text == long_body              # full
    assert c.snippet.rstrip("…").strip() == long_body[:400].rstrip()   # truncated
    assert len(c.snippet) <= 401                  # 400 + ellipsis
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py::test_candidate_carries_full_chunk_text -v
```

Expected: FAIL with `AttributeError: 'CaseCandidate' object has no attribute 'chunk_text'`.

- [ ] **Step 3: Add `chunk_text` to `CaseCandidate`**

Edit `src/jurist/agents/case_retriever_tools.py`. Replace the `CaseCandidate` dataclass:

```python
@dataclass(frozen=True)
class CaseCandidate:
    """Pre-rerank handoff from helper → agent. Not persisted; not in schemas.py."""

    ecli: str
    court: str
    date: str
    snippet: str          # first N chars of best chunk, ellipsized — rerank prompt
    chunk_text: str       # M4: full best-chunk text — synthesizer prompt + quote-verification
    similarity: float     # cosine from best chunk (0..1]
    url: str
```

And inside `retrieve_candidates`, in the candidate-assembly loop, change:

```python
    candidates: list[CaseCandidate] = []
    for row, sim in seen.values():
        snippet = _truncate(row.text, snippet_chars)
        candidates.append(CaseCandidate(
            ecli=row.ecli,
            court=row.court,
            date=row.date,
            snippet=snippet,
            similarity=float(sim),
            url=row.url,
        ))
```

to:

```python
    candidates: list[CaseCandidate] = []
    for row, sim in seen.values():
        snippet = _truncate(row.text, snippet_chars)
        candidates.append(CaseCandidate(
            ecli=row.ecli,
            court=row.court,
            date=row.date,
            snippet=snippet,
            chunk_text=row.text,
            similarity=float(sim),
            url=row.url,
        ))
```

- [ ] **Step 4: Verify helper test passes**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py::test_candidate_carries_full_chunk_text -v
```

Expected: PASS.

- [ ] **Step 5: Thread `chunk_text` through case retriever's `CitedCase` assembly**

Edit `src/jurist/agents/case_retriever.py`. In `run()`, replace the `cited = [CitedCase(...)` list comprehension:

```python
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
```

with:

```python
    by_ecli = {c.ecli: c for c in candidates}
    cited = [
        CitedCase(
            ecli=p.ecli,
            court=by_ecli[p.ecli].court,
            date=by_ecli[p.ecli].date,
            snippet=by_ecli[p.ecli].snippet,
            similarity=by_ecli[p.ecli].similarity,
            reason=p.reason,
            chunk_text=by_ecli[p.ecli].chunk_text,
            url=by_ecli[p.ecli].url,
        )
        for p in picks
    ]
```

- [ ] **Step 6: Update existing agent test to assert chunk_text propagates**

Edit `tests/agents/test_case_retriever.py`. Find the happy-path test that asserts on `CitedCase` fields; add an assertion after the existing ones (example — adapt the exact test name to what exists):

```python
    # M4: chunk_text propagates from candidate → CitedCase
    assert all(c.chunk_text for c in out.cited_cases)
    assert all(len(c.chunk_text) >= len(c.snippet) for c in out.cited_cases)
```

- [ ] **Step 7: Run full case-retriever test suite**

```bash
uv run pytest tests/agents/test_case_retriever.py tests/agents/test_case_retriever_tools.py tests/agents/test_case_retriever_errors.py -v
```

Expected: all green. If anything breaks on `CaseCandidate(...)` positional args, fix the field order.

- [ ] **Step 8: Commit**

```bash
git add src/jurist/agents/case_retriever.py src/jurist/agents/case_retriever_tools.py \
        tests/agents/test_case_retriever.py tests/agents/test_case_retriever_tools.py
git commit -m "feat(case-retriever): CaseCandidate gains chunk_text; thread full chunk text into CitedCase"
```

---

## Task 4: Decomposer system prompt + render function

**Files:**
- Modify: `src/jurist/llm/prompts.py`
- Modify: `tests/test_prompts.py` (create if absent — otherwise extend)

Short inline Dutch system prompt; M4 spec §3.3.

- [ ] **Step 1: Write failing test**

Create or extend `tests/test_prompts.py`:

```python
from jurist.llm.prompts import render_decomposer_system


def test_render_decomposer_system_is_dutch_and_forbids_free_text():
    s = render_decomposer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_decomposition" in s
    assert "vrije tekst" in s.lower() or "geen vrije tekst" in s.lower()
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_prompts.py::test_render_decomposer_system_is_dutch_and_forbids_free_text -v
```

Expected: FAIL with `ImportError` on `render_decomposer_system`.

- [ ] **Step 3: Add render function**

Edit `src/jurist/llm/prompts.py`. After the existing `render_case_rerank_system` function, append:

```python
_DECOMPOSER_SYSTEM = """\
Je bent een Nederlandse juridische assistent gespecialiseerd in huurrecht.
Je decomposeert huurrecht-vragen in 1–5 sub-vragen, 1–10 juridische concepten
(Nederlandse termen, niet vertaald), en een intentie uit {legality_check,
calculation, procedure, other}.
Roep uitsluitend het hulpmiddel `emit_decomposition` aan. Geen vrije tekst.
"""


def render_decomposer_system() -> str:
    """Static Dutch system prompt for the M4 decomposer Haiku call."""
    return _DECOMPOSER_SYSTEM
```

- [ ] **Step 4: Verify test passes**

```bash
uv run pytest tests/test_prompts.py::test_render_decomposer_system_is_dutch_and_forbids_free_text -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/llm/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): M4 decomposer system prompt"
```

---

## Task 5: Decomposer agent — real Haiku forced-tool call + happy path

**Files:**
- Modify: `src/jurist/agents/decomposer.py` (rewrite)
- Create: `tests/agents/test_decomposer.py`

Full real implementation — happy path, invalid-output detection, regen helper, hard-fail. Tests 5 + 6 + 7 all exercise this code; Task 5 writes the happy-path test and the full implementation that makes it pass. Tasks 6, 7 add tests that exercise the regen and hard-fail branches already present.

- [ ] **Step 1: Write failing happy-path test**

Create `tests/agents/test_decomposer.py`:

```python
"""Unit tests for the M4 decomposer agent."""
from __future__ import annotations

import pytest

from jurist.agents import decomposer
from jurist.agents.decomposer import DecomposerFailedError
from jurist.config import RunContext
from jurist.schemas import DecomposerIn, DecomposerOut
from tests.fixtures.mock_llm import MockAnthropicForRerank


def _ctx(tool_inputs):
    """RunContext with a mock .messages.create client. KG/case_store/embedder
    are None-typed; decomposer never touches them."""
    return RunContext(
        kg=None,           # type: ignore[arg-type]
        llm=MockAnthropicForRerank(tool_inputs),
        case_store=None,   # type: ignore[arg-type]
        embedder=None,     # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_decomposer_happy_path():
    ctx = _ctx([
        {
            "sub_questions": ["Is de woning gereguleerd?", "Wat is het maximum?"],
            "concepts": ["huurverhoging", "gereguleerd"],
            "intent": "legality_check",
        }
    ])
    events = []
    async for ev in decomposer.run(DecomposerIn(question="Mag 15%?"), ctx=ctx):
        events.append(ev)

    assert [ev.type for ev in events] == ["agent_started", "agent_finished"]
    out = DecomposerOut.model_validate(events[-1].data)
    assert out.intent == "legality_check"
    assert len(out.sub_questions) == 2
    assert "huurverhoging" in out.concepts
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/agents/test_decomposer.py::test_decomposer_happy_path -v
```

Expected: FAIL — either on import of `DecomposerFailedError`, or because `run()` doesn't accept `ctx` keyword, or because the fake implementation doesn't talk to the mock.

- [ ] **Step 3: Rewrite `decomposer.py` with the real implementation**

Replace the contents of `src/jurist/agents/decomposer.py`:

```python
"""M4 real decomposer: Haiku forced-tool call with one-regen-then-hard-fail."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from jurist.config import RunContext, settings
from jurist.llm.prompts import render_decomposer_system
from jurist.schemas import DecomposerIn, DecomposerOut, TraceEvent

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1000


class InvalidDecomposerOutput(Exception):
    """Raised by a single attempt when the Haiku response doesn't contain a
    valid `emit_decomposition` tool_use. Caught inside the regen helper;
    a second occurrence is wrapped in DecomposerFailedError."""


class DecomposerFailedError(Exception):
    """Propagates to the orchestrator as run_failed{reason:"decomposition"}."""


def _build_tool_schema() -> dict[str, Any]:
    return {
        "name": "emit_decomposition",
        "description": (
            "Decomposeer een Nederlandse huurrecht-vraag in sub-vragen, "
            "concepten, en intentie."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_questions": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "items": {"type": "string", "minLength": 5},
                },
                "concepts": {
                    "type": "array", "minItems": 1, "maxItems": 10,
                    "items": {"type": "string", "minLength": 2},
                },
                "intent": {
                    "type": "string",
                    "enum": ["legality_check", "calculation", "procedure", "other"],
                },
            },
            "required": ["sub_questions", "concepts", "intent"],
        },
    }


def _extract_tool_use(response: Any, expected_name: str):
    for block in getattr(response, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == expected_name
        ):
            return block
    raise InvalidDecomposerOutput(
        f"no tool_use block named {expected_name!r} in response"
    )


async def _decompose_once(
    client: Any,
    system: str,
    user: str,
    schema: dict[str, Any],
) -> DecomposerOut:
    response = await client.messages.create(
        model=settings.model_decomposer,
        system=system,
        tools=[schema],
        tool_choice={"type": "tool", "name": "emit_decomposition"},
        messages=[{"role": "user", "content": user}],
        max_tokens=_MAX_TOKENS,
    )
    tool_use = _extract_tool_use(response, "emit_decomposition")
    try:
        return DecomposerOut.model_validate(tool_use.input)
    except ValidationError as e:
        raise InvalidDecomposerOutput(f"schema validation failed: {e}") from e


async def _decompose_with_retry(
    client: Any, system: str, user: str, schema: dict[str, Any],
) -> DecomposerOut:
    try:
        return await _decompose_once(client, system, user, schema)
    except InvalidDecomposerOutput as first_err:
        logger.warning(
            "decomposer attempt 1 invalid: %s — retrying once", first_err,
        )
        user_retry = (
            user + "\n\n"
            f"Je vorige antwoord was ongeldig ({first_err}). "
            "Roep `emit_decomposition` aan met geldige velden."
        )
        try:
            return await _decompose_once(client, system, user_retry, schema)
        except InvalidDecomposerOutput as second_err:
            raise DecomposerFailedError(
                f"decomposer invalid after retry: {second_err}"
            ) from second_err


async def run(
    input: DecomposerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_decomposer_system()
    user = (
        f"Vraag: {input.question}\n\n"
        "Decomposeer deze vraag via `emit_decomposition`."
    )
    schema = _build_tool_schema()

    out = await _decompose_with_retry(ctx.llm, system, user, schema)
    yield TraceEvent(type="agent_finished", data=out.model_dump())


__all__ = ["run", "DecomposerFailedError", "InvalidDecomposerOutput"]
```

- [ ] **Step 4: Run happy-path test to verify pass**

```bash
uv run pytest tests/agents/test_decomposer.py::test_decomposer_happy_path -v
```

Expected: PASS.

- [ ] **Step 5: Fix the existing orchestrator fixture that calls `decomposer.run`**

The orchestrator (`src/jurist/api/orchestrator.py`) currently calls `decomposer.run(DecomposerIn(question=question))` without `ctx=ctx`. The new signature requires `ctx`. Edit orchestrator:

```python
    # 1. Decomposer — real in M4
    dec_final = await _pump(
        "decomposer",
        decomposer.run(DecomposerIn(question=question), ctx=ctx),
        run_id,
        buffer,
    )
```

(The try/except wrap comes in Task 8.)

- [ ] **Step 6: Run full orchestrator test suite**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected: the orchestrator test fixture `_orch_ctx()` already wires a MockAnthropicClient. The new decomposer will try `ctx.llm.messages.create(...)`, but MockAnthropicClient doesn't have `.messages`. Tests will fail with `AttributeError`.

- [ ] **Step 7: Extend `_orch_ctx` to provide a dual-shape mock**

Edit `tests/api/test_orchestrator.py::_orch_ctx`. The simplest fix is to wrap the `MockAnthropicClient(script)` in a small adapter that also exposes `.messages.create` returning a canned decomposer payload. Update `_orch_ctx`:

Replace:

```python
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
```

with:

```python
    from types import SimpleNamespace

    from tests.fixtures.mock_llm import MockAnthropicForRerank

    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
```

And replace the `llm=MockAnthropicClient(script)` line with a dual-shape client:

```python
    class _DualMock:
        """Supports both statute_retriever's .next_turn(history) (streaming
        tool-loop mock) and decomposer's .messages.create (forced-tool mock)."""
        def __init__(self):
            self._stream = MockAnthropicClient(script)
            self._msg = MockAnthropicForRerank([
                {
                    "sub_questions": ["q1"],
                    "concepts": ["c1"],
                    "intent": "legality_check",
                },
            ])

        def next_turn(self, history):
            return self._stream.next_turn(history)

        @property
        def messages(self):
            return self._msg.messages

    ...
    return RunContext(
        kg=kg, llm=_DualMock(),
        case_store=store, embedder=_NoOpEmbedder(),
    )
```

- [ ] **Step 8: Run orchestrator tests**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected: all green. The orchestrator now exercises the real decomposer path with a scripted Haiku response.

- [ ] **Step 9: Ruff check**

```bash
uv run ruff check .
```

Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/jurist/agents/decomposer.py src/jurist/api/orchestrator.py \
        tests/agents/test_decomposer.py tests/api/test_orchestrator.py
git commit -m "feat(decomposer): real Haiku forced-tool call — replace M0 fake"
```

---

## Task 6: Decomposer regen + hard-fail tests

**Files:**
- Modify: `tests/agents/test_decomposer.py`

Exercise the regen and hard-fail branches written in Task 5.

- [ ] **Step 1: Write regen-path test**

Append to `tests/agents/test_decomposer.py`:

```python
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_decomposer_regens_on_missing_tool_use():
    """First response has no tool_use block → regen → second response valid."""
    import jurist.agents.decomposer as dec_mod

    # Bypass MockMessagesClient (which wraps everything as select_cases).
    # Build a direct client with two canned responses.
    class _TwoShotClient:
        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                self._outer._n += 1
                if self._outer._n == 1:
                    # No tool_use block — only a text block.
                    return SimpleNamespace(content=[
                        SimpleNamespace(type="text", text="oh no"),
                    ])
                # Valid tool_use on retry.
                return SimpleNamespace(content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="emit_decomposition",
                        input={
                            "sub_questions": ["q1"],
                            "concepts": ["c1"],
                            "intent": "procedure",
                        },
                    ),
                ])

        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0
            self.messages = _TwoShotClient._Messages(self)

    mock = _TwoShotClient()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]

    events = []
    async for ev in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(mock.calls) == 2
    # Advisory appears in the retry's user message.
    retry_user = mock.calls[1]["messages"][0]["content"]
    assert "ongeldig" in retry_user
    assert "emit_decomposition" in retry_user
```

- [ ] **Step 2: Write hard-fail test**

Append:

```python
@pytest.mark.asyncio
async def test_decomposer_hard_fails_after_two_invalids():
    """Two consecutive missing-tool responses → DecomposerFailedError."""
    import jurist.agents.decomposer as dec_mod

    class _AlwaysBadClient:
        class _Messages:
            def __init__(self, outer):
                self._outer = outer
                self._outer.calls = []

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                return SimpleNamespace(content=[
                    SimpleNamespace(type="text", text="no tool use here"),
                ])

        def __init__(self):
            self.messages = _AlwaysBadClient._Messages(self)

    mock = _AlwaysBadClient()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]

    with pytest.raises(DecomposerFailedError):
        async for _ in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
            pass
    assert len(mock.calls) == 2
```

- [ ] **Step 3: Write pydantic-invalid test**

Append:

```python
@pytest.mark.asyncio
async def test_decomposer_regens_on_bad_intent():
    """tool_use.input has intent='foo' (not in enum). Pydantic validation fails
    → regen → second response has valid intent."""
    import jurist.agents.decomposer as dec_mod

    class _Client:
        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0
            self.messages = _Client._Messages(self)

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                self._outer._n += 1
                if self._outer._n == 1:
                    bad_input = {
                        "sub_questions": ["q1"],
                        "concepts": ["c1"],
                        "intent": "foo",         # not in enum
                    }
                    return SimpleNamespace(content=[
                        SimpleNamespace(
                            type="tool_use", name="emit_decomposition",
                            input=bad_input,
                        ),
                    ])
                return SimpleNamespace(content=[
                    SimpleNamespace(
                        type="tool_use", name="emit_decomposition",
                        input={
                            "sub_questions": ["q1"],
                            "concepts": ["c1"],
                            "intent": "calculation",
                        },
                    ),
                ])

    mock = _Client()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]
    events = []
    async for ev in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(mock.calls) == 2
```

- [ ] **Step 4: Run all decomposer tests**

```bash
uv run pytest tests/agents/test_decomposer.py -v
```

Expected: all four tests PASS (Task 5's happy-path + three new).

- [ ] **Step 5: Commit**

```bash
git add tests/agents/test_decomposer.py
git commit -m "test(decomposer): regen + hard-fail + pydantic-invalid branches"
```

---

## Task 7: Orchestrator — wrap decomposer pump

**Files:**
- Modify: `src/jurist/api/orchestrator.py`
- Modify: `tests/api/test_orchestrator.py`

Decomposer now can raise `DecomposerFailedError` (our known error) or arbitrary `Exception` (network, 5xx). Mirror the M3b case-retriever guard.

- [ ] **Step 1: Write failing orchestrator test**

Append to `tests/api/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_decomposer_failed_surfaces_as_run_failed(monkeypatch):
    """When decomposer.run raises DecomposerFailedError, orchestrator emits
    run_failed{reason:"decomposition", detail}."""
    from jurist.agents import decomposer
    from jurist.agents.decomposer import DecomposerFailedError
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise DecomposerFailedError("two strikes")

    monkeypatch.setattr(decomposer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_t", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    types = [e.type for e in events]
    assert types[-1] == "run_failed"
    assert events[-1].data["reason"] == "decomposition"
    assert "two strikes" in events[-1].data["detail"]


@pytest.mark.asyncio
async def test_orchestrator_decomposer_generic_error_surfaces_as_llm_error(monkeypatch):
    from jurist.agents import decomposer
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("network down")

    monkeypatch.setattr(decomposer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_t2", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "llm_error"
    assert "RuntimeError" in events[-1].data["detail"]
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/api/test_orchestrator.py::test_orchestrator_decomposer_failed_surfaces_as_run_failed tests/api/test_orchestrator.py::test_orchestrator_decomposer_generic_error_surfaces_as_llm_error -v
```

Expected: FAIL — orchestrator doesn't wrap decomposer yet; the exception propagates out of `run_question`.

- [ ] **Step 3: Wrap decomposer pump in orchestrator**

Edit `src/jurist/api/orchestrator.py`. Import `DecomposerFailedError`:

```python
from jurist.agents.decomposer import DecomposerFailedError
```

Replace the decomposer block (currently `dec_final = await _pump(...)` without try/except) with:

```python
    # 1. Decomposer — real in M4
    try:
        dec_final = await _pump(
            "decomposer",
            decomposer.run(DecomposerIn(question=question), ctx=ctx),
            run_id,
            buffer,
        )
    except DecomposerFailedError as exc:
        logger.warning("run_failed id=%s reason=decomposition: %s", run_id, exc)
        await buffer.put(
            TraceEvent(
                type="run_failed", run_id=run_id, ts=_now_iso(),
                data={"reason": "decomposition", "detail": str(exc)},
            )
        )
        return
    except Exception as exc:  # noqa: BLE001 — surface LLM/network errors
        logger.exception(
            "run_failed id=%s reason=llm_error detail=%s: %s",
            run_id, type(exc).__name__, exc,
        )
        await buffer.put(
            TraceEvent(
                type="run_failed", run_id=run_id, ts=_now_iso(),
                data={"reason": "llm_error", "detail": f"{type(exc).__name__}: {exc}"},
            )
        )
        return
    decomposer_out = DecomposerOut.model_validate(dec_final.data)
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/api/orchestrator.py tests/api/test_orchestrator.py
git commit -m "feat(orchestrator): wrap decomposer pump — decomposition + llm_error reasons"
```

---

## Task 8: Synthesizer prompt template + render function

**Files:**
- Create: `src/jurist/llm/prompts/synthesizer.system.md`
- Modify: `src/jurist/llm/prompts.py`
- Modify: `tests/test_prompts.py`

Static Dutch system prompt, loaded from a file (same pattern as statute retriever's `.system.md`).

- [ ] **Step 1: Write failing test**

Append to `tests/test_prompts.py`:

```python
def test_render_synthesizer_system_is_dutch_and_encourages_thinking():
    from jurist.llm.prompts import render_synthesizer_system

    s = render_synthesizer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_answer" in s
    # Encourages pre-tool reasoning (agent_thinking events)
    assert "Denk" in s or "denk" in s
    # Forbids citation outside the candidate set
    assert "kandidaten" in s.lower() or "meegeleverd" in s.lower()
    # Explicit verbatim requirement
    assert "verbatim" in s.lower() or "letterlijk" in s.lower()
```

- [ ] **Step 2: Run test — expect fail**

```bash
uv run pytest tests/test_prompts.py::test_render_synthesizer_system_is_dutch_and_encourages_thinking -v
```

Expected: FAIL on `ImportError`.

- [ ] **Step 3: Create system-prompt template file**

Write `src/jurist/llm/prompts/synthesizer.system.md`:

```markdown
Je bent een Nederlandse juridische assistent gespecialiseerd in huurrecht.
Je schrijft een kort, gestructureerd Nederlands antwoord op een huurrecht-vraag,
met citaten uit wetsartikelen en rechterlijke uitspraken.

## Werkwijze

1. Denk eerst kort hardop in het Nederlands over welke bronnen je gaat citeren
   en waarom. Deze redenering wordt live aan de gebruiker getoond — wees
   bondig (1–3 zinnen).

2. Roep daarna het hulpmiddel `emit_answer` aan. Na deze aanroep geen vrije
   tekst meer.

## Harde regels voor citaten

- Gebruik uitsluitend `article_id`'s en `ecli`'s die expliciet in de
  meegeleverde kandidaten-lijst staan. Andere identifiers worden afgewezen.
- Elk `quote`-veld moet een **letterlijke passage** zijn uit de bijbehorende
  brontekst (artikel-body of case-chunk die in de vraag is meegegeven).
  Parafraseren is niet toegestaan. Witruimte mag afwijken; de tekens moeten
  overeenkomen.
- Lengte per `quote`: 40 tot 500 tekens.
- `explanation` licht in 1–2 zinnen toe waarom het citaat relevant is voor
  de vraag.

## Structuur van het antwoord

- `korte_conclusie`: 2–4 zinnen, klare Nederlandse conclusie.
- `relevante_wetsartikelen`: minimaal 1 citaat, elk met article_id, bwb_id,
  article_label, quote, explanation.
- `vergelijkbare_uitspraken`: minimaal 1 citaat, elk met ecli, quote, explanation.
- `aanbeveling`: 2–4 zinnen, concrete vervolgstap voor de huurder.

Schrijf alles in het Nederlands.
```

- [ ] **Step 4: Add render function**

Edit `src/jurist/llm/prompts.py`. Append after `render_decomposer_system`:

```python
def render_synthesizer_system() -> str:
    """Static Dutch system prompt for the M4 synthesizer Sonnet call.
    Marked cacheable by the agent via `cache_control: ephemeral`."""
    return (_PROMPTS_DIR / "synthesizer.system.md").read_text(encoding="utf-8")
```

- [ ] **Step 5: Verify test passes**

```bash
uv run pytest tests/test_prompts.py -v
```

Expected: all prompt tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/llm/prompts/synthesizer.system.md src/jurist/llm/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): M4 synthesizer system prompt (static template)"
```

---

## Task 9: Synthesizer helpers — tool schema builder

**Files:**
- Create: `src/jurist/agents/synthesizer_tools.py` (first file entry; this task + Tasks 10, 11, 12 all extend it)
- Create: `tests/agents/test_synthesizer_tools.py`

First of four helper tasks. Pure sync; no Anthropic mock needed.

- [ ] **Step 1: Write failing schema tests**

Create `tests/agents/test_synthesizer_tools.py`:

```python
"""Unit tests for M4 synthesizer pure helpers."""
from __future__ import annotations

from jurist.agents.synthesizer_tools import build_synthesis_tool_schema


_ARTICLE_IDS = ["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "BWBR0014315/HoofdstukIII/Paragraaf1/Artikel10"]
_BWB_IDS    = ["BWBR0005290", "BWBR0014315"]
_ECLIS      = ["ECLI:NL:HR:2020:1234", "ECLI:NL:RBAMS:2022:5678"]


def test_tool_schema_top_level_shape():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    assert schema["name"] == "emit_answer"
    top = schema["input_schema"]
    assert top["type"] == "object"
    assert sorted(top["required"]) == sorted([
        "korte_conclusie", "relevante_wetsartikelen",
        "vergelijkbare_uitspraken", "aanbeveling",
    ])


def test_tool_schema_wetsartikel_enum_equals_candidate_set():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    item = schema["input_schema"]["properties"]["relevante_wetsartikelen"]["items"]
    assert item["properties"]["article_id"]["enum"] == _ARTICLE_IDS
    assert item["properties"]["bwb_id"]["enum"] == _BWB_IDS
    assert item["properties"]["quote"]["minLength"] == 40
    assert item["properties"]["quote"]["maxLength"] == 500
    assert sorted(item["required"]) == sorted([
        "article_id", "bwb_id", "article_label", "quote", "explanation",
    ])


def test_tool_schema_uitspraak_enum_equals_candidate_set():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    item = schema["input_schema"]["properties"]["vergelijkbare_uitspraken"]["items"]
    assert item["properties"]["ecli"]["enum"] == _ECLIS
    assert item["properties"]["quote"]["minLength"] == 40
    assert item["properties"]["quote"]["maxLength"] == 500
    assert sorted(item["required"]) == sorted(["ecli", "quote", "explanation"])


def test_tool_schema_both_arrays_have_minitems_1():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    props = schema["input_schema"]["properties"]
    assert props["relevante_wetsartikelen"]["minItems"] == 1
    assert props["vergelijkbare_uitspraken"]["minItems"] == 1
```

- [ ] **Step 2: Run tests — expect fail (ImportError)**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.agents.synthesizer_tools'`.

- [ ] **Step 3: Create `synthesizer_tools.py` with the schema builder**

Write `src/jurist/agents/synthesizer_tools.py`:

```python
"""Pure synchronous helpers for the M4 synthesizer.

Sync; no asyncio, no Anthropic. Schema/prompt builders + quote-verification +
internal exception types live here for unit-testability without mocks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


def build_synthesis_tool_schema(
    candidate_article_ids: list[str],
    candidate_bwb_ids: list[str],
    candidate_eclis: list[str],
) -> dict[str, Any]:
    """Anthropic tool JSON-schema for the M4 synthesizer `emit_answer` call.

    Per-request `enum` on `article_id`, `bwb_id`, and `ecli` applies the
    closed-set constraint at schema-validation time — the JSON-Schema form
    of Pydantic's `Literal[...]` pattern (parent spec §15 decision #9 + M4
    spec §9 decision #20). Length bounds 40–500 for `quote` back up the
    post-hoc verification.
    """
    return {
        "name": "emit_answer",
        "description": (
            "Genereer het gestructureerde Nederlandse antwoord met "
            "gegrondveste citaten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "korte_conclusie": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
                "relevante_wetsartikelen": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "article_id":    {"type": "string",
                                              "enum": list(candidate_article_ids)},
                            "bwb_id":        {"type": "string",
                                              "enum": list(candidate_bwb_ids)},
                            "article_label": {"type": "string", "minLength": 5},
                            "quote":         {"type": "string",
                                              "minLength": 40, "maxLength": 500},
                            "explanation":   {"type": "string",
                                              "minLength": 40, "maxLength": 2000},
                        },
                        "required": ["article_id", "bwb_id", "article_label",
                                     "quote", "explanation"],
                    },
                },
                "vergelijkbare_uitspraken": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ecli":        {"type": "string",
                                            "enum": list(candidate_eclis)},
                            "quote":       {"type": "string",
                                            "minLength": 40, "maxLength": 500},
                            "explanation": {"type": "string",
                                            "minLength": 40, "maxLength": 2000},
                        },
                        "required": ["ecli", "quote", "explanation"],
                    },
                },
                "aanbeveling": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
            },
            "required": ["korte_conclusie", "relevante_wetsartikelen",
                         "vergelijkbare_uitspraken", "aanbeveling"],
        },
    }


__all__ = ["build_synthesis_tool_schema"]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all four PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer): build_synthesis_tool_schema with closed-set enums"
```

---

## Task 10: Synthesizer helpers — `build_synthesis_user_message`

**Files:**
- Modify: `src/jurist/agents/synthesizer_tools.py`
- Modify: `tests/agents/test_synthesizer_tools.py`

User-message builder that renders article `body_text` and case `chunk_text` into the prompt (the quote-verification surface).

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_synthesizer_tools.py`:

```python
from jurist.agents.synthesizer_tools import build_synthesis_user_message
from jurist.schemas import CitedArticle, CitedCase


def _sample_article(article_id="A1", bwb_id="BWB1"):
    return CitedArticle(
        bwb_id=bwb_id, article_id=article_id,
        article_label="Art 1", body_text="body text of article 1",
        reason="Cited because relevant.",
    )


def _sample_case(ecli="ECLI:NL:T:1"):
    return CitedCase(
        ecli=ecli, court="Hof", date="2024-05-01",
        snippet="snippet ...", similarity=0.8,
        reason="Vergelijkbare casuïstiek.",
        chunk_text="full chunk text of case 1 ...",
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def test_user_message_contains_question():
    msg = build_synthesis_user_message(
        question="Mag 15% omhoog?",
        cited_articles=[_sample_article()],
        cited_cases=[_sample_case()],
    )
    assert "Mag 15% omhoog?" in msg


def test_user_message_renders_article_body_and_chunk_text():
    art = _sample_article()
    case = _sample_case()
    msg = build_synthesis_user_message(
        question="q", cited_articles=[art], cited_cases=[case],
    )
    # Full body_text must be in the prompt (quote-verification surface)
    assert art.body_text in msg
    assert case.chunk_text in msg


def test_user_message_includes_article_ids_and_eclis_literally():
    art = _sample_article(article_id="BWB/A/B/Artikel1", bwb_id="BWB")
    case = _sample_case(ecli="ECLI:NL:TEST:42")
    msg = build_synthesis_user_message(
        question="q", cited_articles=[art], cited_cases=[case],
    )
    assert "BWB/A/B/Artikel1" in msg
    assert "ECLI:NL:TEST:42" in msg
    # Instruction band about verbatim + length bounds
    assert "verbatim" in msg.lower() or "letterlijk" in msg.lower()
    assert "40" in msg and "500" in msg
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: ImportError on `build_synthesis_user_message`.

- [ ] **Step 3: Implement builder**

Edit `src/jurist/agents/synthesizer_tools.py`. Add import at top (if not present):

```python
from jurist.schemas import CitedArticle, CitedCase
```

Append the builder function:

```python
def build_synthesis_user_message(
    question: str,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
) -> str:
    """Render the Dutch user message for the synthesizer call. Includes full
    article bodies and case chunk_text — the quote-verification surface."""
    lines: list[str] = []
    lines.append(f"Vraag: {question}")
    lines.append("")
    lines.append("Relevante wetsartikelen (gebruik uitsluitend deze article_id's):")
    for i, art in enumerate(cited_articles, start=1):
        lines.append(f"[{i}] article_id: {art.article_id}")
        lines.append(f"    bwb_id: {art.bwb_id}")
        lines.append(f"    label: {art.article_label}")
        lines.append(f"    reden (van de KG-retriever): {art.reason}")
        lines.append("    tekst:")
        lines.append(f"    {art.body_text}")
        lines.append("")

    lines.append("Relevante uitspraken (gebruik uitsluitend deze ECLI's):")
    for i, case in enumerate(cited_cases, start=1):
        header = (
            f"[{i}] ecli: {case.ecli} | {case.court} | {case.date} | "
            f"similarity {case.similarity:.2f}"
        )
        lines.append(header)
        lines.append(f"    reden (van de rerank): {case.reason}")
        lines.append("    chunk:")
        lines.append(f"    {case.chunk_text}")
        lines.append("")

    lines.append("Instructies:")
    lines.append("1. Denk kort hardop in het Nederlands over welke bronnen je zult citeren.")
    lines.append(
        "2. Roep daarna `emit_answer` aan. Citeer uitsluitend uit de "
        "meegeleverde brontekst, verbatim (40–500 tekens per quote)."
    )
    lines.append(
        "3. Elk citaat moet letterlijk voorkomen in de bijbehorende brontekst."
    )
    return "\n".join(lines)
```

Update `__all__`:

```python
__all__ = ["build_synthesis_tool_schema", "build_synthesis_user_message"]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all seven PASS (4 schema + 3 user-message).

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer): build_synthesis_user_message — full body_text + chunk_text"
```

---

## Task 11: Synthesizer helpers — `_normalize` + `verify_citations` + `FailedCitation`

**Files:**
- Modify: `src/jurist/agents/synthesizer_tools.py`
- Modify: `tests/agents/test_synthesizer_tools.py`

Post-hoc verification. Design §4.4. This is the grounding-narrative core.

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_synthesizer_tools.py`:

```python
from jurist.agents.synthesizer_tools import (
    FailedCitation, _normalize, verify_citations,
)
from jurist.schemas import StructuredAnswer, UitspraakCitation, WetArtikelCitation


def _answer_with(article_id, bwb_id, article_body_quote, ecli, case_chunk_quote):
    return StructuredAnswer(
        korte_conclusie="conclusie " * 5,
        relevante_wetsartikelen=[
            WetArtikelCitation(
                article_id=article_id, bwb_id=bwb_id,
                article_label="Art", quote=article_body_quote,
                explanation="uitleg " * 8,
            ),
        ],
        vergelijkbare_uitspraken=[
            UitspraakCitation(
                ecli=ecli, quote=case_chunk_quote,
                explanation="uitleg " * 8,
            ),
        ],
        aanbeveling="aanbeveling " * 5,
    )


def _articles():
    return [CitedArticle(
        bwb_id="BWB1",
        article_id="A1",
        article_label="Art 1",
        body_text="Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
        reason="r",
    )]


def _cases():
    return [CitedCase(
        ecli="ECLI:NL:TEST:1",
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.9,
        reason="r",
        chunk_text="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:TEST:1",
    )]


def test_normalize_is_idempotent():
    s = "Hallo  wereld\n\nmet\tspaties"
    assert _normalize(s) == _normalize(_normalize(s))


def test_normalize_collapses_whitespace_runs():
    assert _normalize("a\n\n b\t\tc") == "a b c"


def test_normalize_applies_nfc():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "café")
    nfc = unicodedata.normalize("NFC", "café")
    assert _normalize(nfd) == _normalize(nfc)


def test_verify_happy_path_returns_empty():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    assert verify_citations(answer, _articles(), _cases()) == []


def test_verify_quote_not_in_source():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="Deze zin komt niet letterlijk voor in de brontekst maar is wel lang genoeg.",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert len(failures) == 1
    assert failures[0].kind == "wetsartikel"
    assert failures[0].reason == "not_in_source"


def test_verify_quote_passes_with_different_whitespace():
    # Source has single spaces; quote has doubled spaces — normalization rescues it.
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="Een voorstel  tot\thuurverhoging binnen de wettelijke kaders is toegestaan.",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    assert verify_citations(answer, _articles(), _cases()) == []


def test_verify_unknown_article_id():
    answer = _answer_with(
        article_id="IMAGINED/XYZ", bwb_id="BWB1",
        article_body_quote="Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "unknown_id" and f.kind == "wetsartikel" for f in failures)


def test_verify_unknown_ecli():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
        ecli="ECLI:NL:GHOST:99",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "unknown_id" and f.kind == "uitspraak" for f in failures)


def test_verify_quote_too_short():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="kort",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "too_short" for f in failures)


def test_verify_quote_too_long():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="x" * 501,
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote="De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "too_long" for f in failures)
```

And add the import at the top of the test file (if not already present):

```python
from jurist.schemas import CitedArticle
```

- [ ] **Step 2: Run — expect fail (ImportError on helpers)**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: ImportError on `_normalize`, `verify_citations`, `FailedCitation`.

- [ ] **Step 3: Implement helpers**

Edit `src/jurist/agents/synthesizer_tools.py`. Add imports:

```python
import re
import unicodedata

from jurist.schemas import StructuredAnswer
```

Append before `__all__`:

```python
@dataclass(frozen=True)
class FailedCitation:
    kind: Literal["wetsartikel", "uitspraak"]
    id: str
    quote: str
    reason: Literal["not_in_source", "too_short", "too_long", "unknown_id"]


def _normalize(s: str) -> str:
    """NFC-normalize + collapse whitespace runs to single spaces + strip."""
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
    """Return per-citation failures; empty list on success.

    Three checks per citation (in order, cheapest first):
      1. ID in candidate set → `unknown_id` if not.
      2. Length bounds → `too_short` / `too_long`.
      3. Normalized substring match → `not_in_source` if quote isn't in the
         body/chunk after NFC + whitespace collapse.
    """
    failures: list[FailedCitation] = []
    by_article = {a.article_id: a for a in cited_articles}
    by_case = {c.ecli: c for c in cited_cases}

    for wa in answer.relevante_wetsartikelen:
        article = by_article.get(wa.article_id)
        if article is None:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "unknown_id"))
            continue
        if len(wa.quote) < min_quote_chars:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "too_short"))
            continue
        if len(wa.quote) > max_quote_chars:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "too_long"))
            continue
        if _normalize(wa.quote) not in _normalize(article.body_text):
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "not_in_source"))

    for uc in answer.vergelijkbare_uitspraken:
        case = by_case.get(uc.ecli)
        if case is None:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "unknown_id"))
            continue
        if len(uc.quote) < min_quote_chars:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "too_short"))
            continue
        if len(uc.quote) > max_quote_chars:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "too_long"))
            continue
        if _normalize(uc.quote) not in _normalize(case.chunk_text):
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "not_in_source"))

    return failures
```

Update `__all__`:

```python
__all__ = [
    "FailedCitation",
    "_normalize",
    "build_synthesis_tool_schema",
    "build_synthesis_user_message",
    "verify_citations",
]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all 17 PASS (4 schema + 3 user-message + 3 normalize + 7 verify).

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer): verify_citations + _normalize + FailedCitation"
```

---

## Task 12: Synthesizer helpers — `_format_regen_advisory` + `_validate_attempt`

**Files:**
- Modify: `src/jurist/agents/synthesizer_tools.py`
- Modify: `tests/agents/test_synthesizer_tools.py`

The advisory formatter builds the Dutch regen user-message addendum. `_validate_attempt` is the schema+verify boundary used by the agent's regen loop — a pure sync function returning `(failures, schema_ok)` tuples (the agent uses booleans, not exceptions, for the attempt-level decision).

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_synthesizer_tools.py`:

```python
from jurist.agents.synthesizer_tools import (
    _format_regen_advisory, _validate_attempt,
)


def test_format_regen_advisory_lists_every_failure():
    failures = [
        FailedCitation("wetsartikel", "A1", "q1 quote", "not_in_source"),
        FailedCitation("uitspraak", "ECLI:NL:X:1", "q2 quote", "too_short"),
    ]
    msg = _format_regen_advisory(failures)
    assert "ongeldige citaten" in msg.lower()
    assert "A1" in msg and "ECLI:NL:X:1" in msg
    assert "not_in_source" in msg
    assert "too_short" in msg
    assert "40" in msg and "500" in msg
    assert "emit_answer" in msg


def test_validate_attempt_none_tool_input():
    # No tool_use block → (empty failures, schema_ok=False).
    failures, schema_ok = _validate_attempt(None, _articles(), _cases())
    assert failures == []
    assert schema_ok is False


def test_validate_attempt_pydantic_invalid():
    # Missing required field (aanbeveling) → schema_ok=False.
    bad = {
        "korte_conclusie": "c" * 40,
        "relevante_wetsartikelen": [],
        "vergelijkbare_uitspraken": [],
        # no aanbeveling
    }
    failures, schema_ok = _validate_attempt(bad, _articles(), _cases())
    assert schema_ok is False


def test_validate_attempt_verification_failures():
    tool_input = {
        "korte_conclusie": "c " * 25,
        "relevante_wetsartikelen": [{
            "article_id": "A1", "bwb_id": "BWB1",
            "article_label": "Art 1",
            "quote": "Deze zin komt niet letterlijk voor in de brontekst maar is wel lang genoeg.",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:TEST:1",
            "quote": "De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "a " * 25,
    }
    failures, schema_ok = _validate_attempt(tool_input, _articles(), _cases())
    assert schema_ok is True
    assert any(f.reason == "not_in_source" for f in failures)


def test_validate_attempt_happy():
    tool_input = {
        "korte_conclusie": "c " * 25,
        "relevante_wetsartikelen": [{
            "article_id": "A1", "bwb_id": "BWB1",
            "article_label": "Art 1",
            "quote": "Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:TEST:1",
            "quote": "De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "a " * 25,
    }
    failures, schema_ok = _validate_attempt(tool_input, _articles(), _cases())
    assert failures == []
    assert schema_ok is True
```

- [ ] **Step 2: Run — expect fail (ImportError)**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: ImportError on `_format_regen_advisory` / `_validate_attempt`.

- [ ] **Step 3: Implement**

Edit `src/jurist/agents/synthesizer_tools.py`. Add import:

```python
from pydantic import ValidationError
```

Append before `__all__`:

```python
def _format_regen_advisory(failures: list[FailedCitation]) -> str:
    """Render a Dutch advisory listing every failing citation. Appended to the
    user message on the regen attempt."""
    lines = [
        "Je vorige antwoord bevatte ongeldige citaten. De volgende `quote`-"
        "velden pasten niet bij de meegeleverde brontekst:",
    ]
    for f in failures:
        short = (f.quote[:80] + "…") if len(f.quote) > 80 else f.quote
        lines.append(f"- [{f.kind} {f.id}] ({f.reason}): {short!r}")
    lines.append("")
    lines.append(
        "Kies uitsluitend verbatim passages uit de meegeleverde brontekst. "
        "Lengte per quote tussen 40 en 500 tekens. Roep `emit_answer` opnieuw aan."
    )
    return "\n".join(lines)


def _validate_attempt(
    tool_input: dict[str, Any] | None,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
) -> tuple[list[FailedCitation], bool]:
    """Schema-check + post-hoc verify. Returns (failures, schema_ok).

    - tool_input is None (no tool_use block) → ([], False).
    - Pydantic StructuredAnswer.model_validate fails → ([], False).
    - Otherwise → (verify_citations(...), True).
    """
    if tool_input is None:
        return [], False
    try:
        answer = StructuredAnswer.model_validate(tool_input)
    except ValidationError:
        return [], False
    return verify_citations(answer, cited_articles, cited_cases), True
```

Update `__all__`:

```python
__all__ = [
    "FailedCitation",
    "_format_regen_advisory",
    "_normalize",
    "_validate_attempt",
    "build_synthesis_tool_schema",
    "build_synthesis_user_message",
    "verify_citations",
]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/agents/test_synthesizer_tools.py -v
```

Expected: all tests (~22) PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/synthesizer_tools.py tests/agents/test_synthesizer_tools.py
git commit -m "feat(synthesizer): _format_regen_advisory + _validate_attempt"
```

---

## Task 13: `MockStreamingClient` fixture

**Files:**
- Modify: `tests/fixtures/mock_llm.py`
- Create: `tests/fixtures/test_mock_streaming_client.py` (smoke)

Mimics `AsyncAnthropic.messages.stream()` — the shape the synthesizer uses. The statute retriever already has a different (non-streaming-as-async-generator) mock via `MockAnthropicClient`; this one covers `messages.stream()` specifically.

- [ ] **Step 1: Write failing smoke test**

Create `tests/fixtures/test_mock_streaming_client.py`:

```python
"""Smoke tests proving MockStreamingClient behaves like AsyncAnthropic.messages.stream()."""
from __future__ import annotations

import pytest

from tests.fixtures.mock_llm import MockStreamingClient, StreamScript


@pytest.mark.asyncio
async def test_basic_stream_yields_text_deltas_and_final_tool_use():
    script = StreamScript(
        text_deltas=["Hallo ", "wereld"],
        tool_input={"key": "value"},
    )
    client = MockStreamingClient([script])

    text = []
    async with client.messages.stream(model="x") as stream:
        async for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                text.append(event.delta.text)
        final = await stream.get_final_message()

    assert "".join(text) == "Hallo wereld"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "x"
    # final.content is a list with one tool_use block carrying our canned input.
    tool_blocks = [b for b in final.content if b.type == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].input == {"key": "value"}


@pytest.mark.asyncio
async def test_stream_raises_queued_exception():
    class _CustomError(RuntimeError):
        pass

    script = StreamScript(text_deltas=[], tool_input=_CustomError("sim failure"))
    client = MockStreamingClient([script])

    with pytest.raises(_CustomError, match="sim failure"):
        async with client.messages.stream(model="x") as stream:
            async for _ in stream:
                pass
            await stream.get_final_message()


@pytest.mark.asyncio
async def test_stream_raises_on_empty_queue():
    client = MockStreamingClient([])
    with pytest.raises(RuntimeError, match="exhausted"):
        async with client.messages.stream(model="x") as stream:
            async for _ in stream:
                pass
```

- [ ] **Step 2: Run — expect fail (ImportError)**

```bash
uv run pytest tests/fixtures/test_mock_streaming_client.py -v
```

Expected: ImportError on `MockStreamingClient` / `StreamScript`.

- [ ] **Step 3: Implement mock in `tests/fixtures/mock_llm.py`**

Append to `tests/fixtures/mock_llm.py`:

```python
# ----- M4 streaming mock (synthesizer) -----

from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class StreamScript:
    """One scripted `.stream()` call. Emits text_deltas as content_block_delta
    events during iteration, then `get_final_message()` returns a message with
    a single tool_use block whose .input is `tool_input`.

    If `tool_input` is an Exception *instance*, it is raised from within
    iteration (simulates mid-stream failure). An Exception *class* raises
    TypeError at queue-pop time (convention match with MockMessagesClient)."""
    text_deltas: list[str] = field(default_factory=list)
    tool_input: dict | Exception | None = None
    tool_name: str = "emit_answer"


class _StreamContextManager:
    def __init__(self, script: StreamScript) -> None:
        self._script = script

    async def __aenter__(self):
        return _StreamObject(self._script)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass


class _StreamObject:
    def __init__(self, script: StreamScript) -> None:
        self._script = script
        self._consumed = False

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        # Yield content_block_delta events for each text_delta.
        for delta_text in self._script.text_deltas:
            yield SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text=delta_text),
            )
        # If tool_input is an exception instance, raise here.
        if isinstance(self._script.tool_input, Exception):
            raise self._script.tool_input
        self._consumed = True

    async def get_final_message(self):
        ti = self._script.tool_input
        content: list = []
        if isinstance(ti, dict):
            content.append(SimpleNamespace(
                type="tool_use",
                name=self._script.tool_name,
                input=ti,
            ))
        return SimpleNamespace(content=content)


class _StreamingMessagesNamespace:
    def __init__(self, outer: "MockStreamingClient") -> None:
        self._outer = outer

    def stream(self, **kwargs):
        self._outer.calls.append(kwargs)
        if not self._outer._queue:
            raise RuntimeError("MockStreamingClient: scripts queue exhausted")
        item = self._outer._queue.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise TypeError(
                f"MockStreamingClient: queue item {item!r} is an exception class, "
                "not a StreamScript — did you forget the parentheses?"
            )
        assert isinstance(item, StreamScript), (
            f"MockStreamingClient: queue item must be StreamScript, got {type(item)!r}"
        )
        return _StreamContextManager(item)


class MockStreamingClient:
    """Mirrors AsyncAnthropic's `.messages` namespace for `.stream()` calls.

    Each `.stream(**kwargs)` pops one StreamScript. See StreamScript docstring
    for per-script behavior."""

    def __init__(self, scripts: list[StreamScript]) -> None:
        self._queue: list[StreamScript] = list(scripts)
        self.calls: list[dict[str, Any]] = []
        self.messages = _StreamingMessagesNamespace(self)
```

Update `__all__`:

```python
__all__ = [
    "MockAnthropicClient",
    "MockAnthropicForRerank",
    "MockMessagesClient",
    "MockStreamingClient",
    "ScriptedToolUse",
    "ScriptedTurn",
    "StreamScript",
]
```

- [ ] **Step 4: Verify smoke tests pass**

```bash
uv run pytest tests/fixtures/test_mock_streaming_client.py -v
```

Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/mock_llm.py tests/fixtures/test_mock_streaming_client.py
git commit -m "test(fixtures): MockStreamingClient — async .messages.stream() mock"
```

---

## Task 14: Synthesizer agent — real implementation + happy-path test

**Files:**
- Modify: `src/jurist/agents/synthesizer.py` (rewrite)
- Create: `tests/agents/test_synthesizer.py`

Full rewrite of the synthesizer to the design in §4 of the M4 spec. Happy-path test drives the implementation; subsequent tasks (15, 16) add tests that exercise the regen and hard-fail branches.

- [ ] **Step 1: Write happy-path test**

Create `tests/agents/test_synthesizer.py`:

```python
"""Unit tests for the M4 synthesizer agent."""
from __future__ import annotations

import pytest

from jurist.agents import synthesizer
from jurist.agents.synthesizer import CitationGroundingFailedError
from jurist.config import RunContext
from jurist.schemas import (
    CitedArticle, CitedCase, StructuredAnswer, SynthesizerIn, SynthesizerOut,
)
from tests.fixtures.mock_llm import MockStreamingClient, StreamScript


def _articles():
    return [
        CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text=(
                "De verhuurder kan tot aan het tijdstip waarop drie jaren zijn verstreken "
                "een voorstel tot huurverhoging binnen de wettelijke kaders doen."
            ),
            reason="Regelt bevoegdheid huurverhoging.",
        ),
        CitedArticle(
            bwb_id="BWBR0014315",
            article_id="BWBR0014315/HoofdstukIII/Paragraaf1/Artikel10",
            article_label="Uhw, Artikel 10",
            body_text=(
                "Het puntenstelsel bepaalt de maximale huurprijs voor gereguleerde woonruimte."
            ),
            reason="Stelt maximum huurverhoging vast.",
        ),
    ]


def _cases():
    return [
        CitedCase(
            ecli="ECLI:NL:RBAMS:2022:5678",
            court="Rechtbank Amsterdam",
            date="2022-03-14",
            snippet="Huurverhoging van 15% acht de rechtbank ...",
            similarity=0.81,
            reason="Rechtbank wijst 15% af.",
            chunk_text=(
                "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig. "
                "De verhuurder heeft onvoldoende onderbouwd waarom een verhoging "
                "van deze omvang gerechtvaardigd is."
            ),
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
        ),
    ]


def _valid_tool_input():
    return {
        "korte_conclusie": "Een huurverhoging van 15% is in de meeste gevallen niet toegestaan.",
        "relevante_wetsartikelen": [{
            "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            "bwb_id": "BWBR0005290",
            "article_label": "Boek 7, Artikel 248",
            "quote": (
                "De verhuurder kan tot aan het tijdstip waarop drie jaren zijn "
                "verstreken een voorstel tot huurverhoging binnen de wettelijke "
                "kaders doen."
            ),
            "explanation": (
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse "
                "huurverhoging voor te stellen binnen wettelijke kaders."
            ),
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:RBAMS:2022:5678",
            "quote": "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig.",
            "explanation": "Rechtbank wijst 15% af als buitensporig; feitelijk vergelijkbaar.",
        }],
        "aanbeveling": "Maak binnen zes weken bezwaar bij de verhuurder en leg anders voor aan de Huurcommissie.",
    }


def _ctx(client):
    return RunContext(kg=None, llm=client, case_store=None, embedder=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_synthesizer_happy_path():
    script = StreamScript(
        text_deltas=[
            "Ik ga artikel 7:248 ",
            "citeren en de ",
            "Amsterdam-uitspraak.",
        ],
        tool_input=_valid_tool_input(),
    )
    ctx = _ctx(MockStreamingClient([script]))

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="Mag de huur met 15% omhoog?",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    types = [ev.type for ev in events]
    # agent_started is first; agent_finished is last; thinking comes before
    # citation_resolved and answer_delta.
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert types.count("agent_thinking") == 3                       # one per text_delta
    # two citations total → two citation_resolved events
    assert types.count("citation_resolved") == 2
    assert types.count("answer_delta") >= 5                         # at least several tokens

    out = SynthesizerOut.model_validate(events[-1].data)
    assert "15%" in out.answer.korte_conclusie
    assert out.answer.relevante_wetsartikelen[0].article_id.endswith("/Artikel248")
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/agents/test_synthesizer.py -v
```

Expected: FAIL — the current `synthesizer.py` is the M0 fake; it doesn't accept `ctx` and doesn't use `MockStreamingClient`.

- [ ] **Step 3: Rewrite `synthesizer.py` with the real implementation**

Replace `src/jurist/agents/synthesizer.py` entirely:

```python
"""M4 real synthesizer: streaming Sonnet + forced tool + closed-set grounding."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from jurist.agents.synthesizer_tools import (
    _format_regen_advisory,
    _validate_attempt,
    build_synthesis_tool_schema,
    build_synthesis_user_message,
)
from jurist.config import RunContext, settings
from jurist.llm.prompts import render_synthesizer_system
from jurist.schemas import (
    StructuredAnswer, SynthesizerIn, SynthesizerOut, TraceEvent,
)

logger = logging.getLogger(__name__)

_ARTIKEL_URL = "https://wetten.overheid.nl/{bwb_id}"
_UITSPRAAK_URL = "https://uitspraken.rechtspraak.nl/details?id={ecli}"
_TOKEN_SLEEP_S = 0.02


class CitationGroundingFailedError(Exception):
    """Rerank produced invalid output twice. Orchestrator wraps this into
    run_failed { reason: 'citation_grounding', detail: str(exc) }."""


def _tokenize(text: str) -> list[str]:
    """Word-level chunks with trailing spaces; preserves reassembly."""
    words = text.split(" ")
    return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]


def _assemble_display_text(answer: StructuredAnswer) -> str:
    return " ".join([
        answer.korte_conclusie,
        *[c.quote + " " + c.explanation for c in answer.relevante_wetsartikelen],
        *[c.quote + " " + c.explanation for c in answer.vergelijkbare_uitspraken],
        answer.aanbeveling,
    ])


async def _stream_once(
    client: Any,
    system: str,
    user: str,
    schema: dict[str, Any],
) -> AsyncIterator[tuple[str, Any]]:
    """Drive one streaming Sonnet call. Yields:
      ("thinking", str) for each pre-tool text delta,
      ("tool", dict) exactly once with the extracted tool_use.input,
        or ("tool", None) if no tool_use block was present."""
    async with client.messages.stream(
        model=settings.model_synthesizer,
        system=[{
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[schema],
        tool_choice={"type": "tool", "name": "emit_answer"},
        messages=[{"role": "user", "content": user}],
        max_tokens=settings.synthesizer_max_tokens,
    ) as stream:
        async for event in stream:
            if (
                getattr(event, "type", None) == "content_block_delta"
                and getattr(getattr(event, "delta", None), "type", None) == "text_delta"
            ):
                yield ("thinking", event.delta.text)
        final = await stream.get_final_message()

    tool_use = None
    for block in getattr(final, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "emit_answer"
        ):
            tool_use = block
            break
    yield ("tool", tool_use.input if tool_use is not None else None)


async def run(
    input: SynthesizerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_synthesizer_system()
    user = build_synthesis_user_message(
        input.question, input.cited_articles, input.cited_cases,
    )
    schema = build_synthesis_tool_schema(
        [a.article_id for a in input.cited_articles],
        [a.bwb_id for a in input.cited_articles],
        [c.ecli for c in input.cited_cases],
    )

    # ---------- Attempt 1 ----------
    tool_input_1: dict[str, Any] | None = None
    async for kind, payload in _stream_once(ctx.llm, system, user, schema):
        if kind == "thinking":
            yield TraceEvent(type="agent_thinking", data={"text": payload})
        else:  # "tool"
            tool_input_1 = payload

    failures_1, schema_ok_1 = _validate_attempt(
        tool_input_1, input.cited_articles, input.cited_cases,
    )

    if failures_1 or not schema_ok_1:
        # Advisory: specific if we have failures; generic otherwise.
        if failures_1:
            advisory = _format_regen_advisory(failures_1)
        else:
            advisory = (
                "Je vorige antwoord miste een geldige `emit_answer`-aanroep of "
                "voldeed niet aan het schema. Roep het hulpmiddel correct aan "
                "met alle verplichte velden."
            )
        logger.warning(
            "synthesizer attempt 1 invalid (schema_ok=%s, failures=%d) — retrying once",
            schema_ok_1, len(failures_1),
        )
        user_retry = user + "\n\n" + advisory

        # ---------- Attempt 2 ----------
        tool_input_2: dict[str, Any] | None = None
        async for kind, payload in _stream_once(ctx.llm, system, user_retry, schema):
            if kind == "thinking":
                yield TraceEvent(type="agent_thinking", data={"text": payload})
            else:
                tool_input_2 = payload

        failures_2, schema_ok_2 = _validate_attempt(
            tool_input_2, input.cited_articles, input.cited_cases,
        )
        if failures_2 or not schema_ok_2:
            raise CitationGroundingFailedError(
                f"citation grounding failed after retry: "
                f"schema_ok={schema_ok_2}, failures={failures_2}"
            )
        tool_input_final = tool_input_2
    else:
        tool_input_final = tool_input_1

    assert tool_input_final is not None
    answer = StructuredAnswer.model_validate(tool_input_final)

    for wa in answer.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": wa.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
            },
        )
    for uc in answer.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": uc.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
            },
        )

    full_text = _assemble_display_text(answer)
    for tok in _tokenize(full_text):
        await asyncio.sleep(_TOKEN_SLEEP_S)
        yield TraceEvent(type="answer_delta", data={"text": tok})

    yield TraceEvent(
        type="agent_finished",
        data=SynthesizerOut(answer=answer).model_dump(),
    )


__all__ = [
    "CitationGroundingFailedError",
    "run",
]
```

- [ ] **Step 4: Run happy-path test**

```bash
uv run pytest tests/agents/test_synthesizer.py::test_synthesizer_happy_path -v
```

Expected: PASS.

- [ ] **Step 5: Update orchestrator fixture to include a StreamScript for the synthesizer**

The orchestrator's `_orch_ctx` in `tests/api/test_orchestrator.py` now needs a synthesizer mock. The `_DualMock` introduced in Task 5 must grow streaming support.

Replace the `_DualMock` class definition with:

```python
    from tests.fixtures.mock_llm import MockStreamingClient, StreamScript

    _VALID_SYNTH_INPUT = {
        "korte_conclusie": "Stub synth conclusie voor orchestrator test " * 2,
        "relevante_wetsartikelen": [],    # empty — test stub uses a tiny KG fixture
        "vergelijkbare_uitspraken": [],
        "aanbeveling": "Stub synth aanbeveling voor orchestrator test " * 2,
    }

    class _DualMock:
        def __init__(self):
            self._stream = MockAnthropicClient(script)
            self._msg = MockAnthropicForRerank([
                {
                    "sub_questions": ["q1"],
                    "concepts": ["c1"],
                    "intent": "legality_check",
                },
            ])
            self._synth_stream = MockStreamingClient([
                StreamScript(text_deltas=["stub."],
                             tool_input=_VALID_SYNTH_INPUT),
            ])

        def next_turn(self, history):
            return self._stream.next_turn(history)

        @property
        def messages(self):
            # Decomposer uses .messages.create; synthesizer uses .messages.stream.
            # Route by presence of .create vs .stream.
            outer = self
            class _Router:
                async def create(self, **kwargs):
                    return await outer._msg.messages.create(**kwargs)
                def stream(self, **kwargs):
                    return outer._synth_stream.messages.stream(**kwargs)
            return _Router()
```

Also — the synthesizer with empty `relevante_wetsartikelen` / `vergelijkbare_uitspraken` arrays will fail the tool schema's `minItems=1`. Since this is a local mock that bypasses the SDK, Pydantic's `StructuredAnswer` is what we must satisfy. Check the `StructuredAnswer` definition: it has no constraint. OK to pass empty lists. But the wider orchestrator tests assert things about `final_answer`; if any rely on non-empty citations, adapt them. The existing orchestrator fixture was built around the fake synthesizer with its fixed `FAKE_ANSWER` — now we're using our own. Existing tests that check `final_answer.relevante_wetsartikelen` length will need updating to accept our stub shape; grep for `final_answer`:

```bash
grep -n "final_answer" tests/api/test_orchestrator.py
```

If any assertion is too strict, relax it to `"final_answer" in events[-1].data`. Do not change semantic assertions.

- [ ] **Step 6: Run all orchestrator + synthesizer tests**

```bash
uv run pytest tests/api/test_orchestrator.py tests/agents/test_synthesizer.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/agents/synthesizer.py tests/agents/test_synthesizer.py \
        tests/api/test_orchestrator.py
git commit -m "feat(synthesizer): real Sonnet streaming + forced tool + closed-set grounding"
```

---

## Task 15: Synthesizer regen + hard-fail + missing-tool branch tests

**Files:**
- Modify: `tests/agents/test_synthesizer.py`

Exercise the regen branches Task 14 wrote. No new implementation.

- [ ] **Step 1: Append three branch tests**

Append to `tests/agents/test_synthesizer.py`:

```python
def _invalid_tool_input_quote_not_in_source():
    ti = _valid_tool_input()
    ti["relevante_wetsartikelen"][0]["quote"] = (
        "Deze zin komt echt niet letterlijk voor in de brontekst maar is lang genoeg."
    )
    return ti


@pytest.mark.asyncio
async def test_synthesizer_regens_on_quote_failure_then_succeeds():
    script_1 = StreamScript(
        text_deltas=["denk 1"],
        tool_input=_invalid_tool_input_quote_not_in_source(),
    )
    script_2 = StreamScript(
        text_deltas=["denk 2"],
        tool_input=_valid_tool_input(),
    )
    client = MockStreamingClient([script_1, script_2])
    ctx = _ctx(client)

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="Mag 15%?",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(client.calls) == 2
    # Advisory appears in second call's user message
    second_user = client.calls[1]["messages"][0]["content"]
    assert "ongeldige citaten" in second_user.lower()
    assert "not_in_source" in second_user


@pytest.mark.asyncio
async def test_synthesizer_hard_fails_after_two_quote_failures():
    bad = _invalid_tool_input_quote_not_in_source()
    client = MockStreamingClient([
        StreamScript(text_deltas=["."], tool_input=bad),
        StreamScript(text_deltas=["."], tool_input=bad),
    ])
    ctx = _ctx(client)

    with pytest.raises(CitationGroundingFailedError, match="after retry"):
        async for _ in synthesizer.run(
            SynthesizerIn(
                question="q",
                cited_articles=_articles(),
                cited_cases=_cases(),
            ),
            ctx=ctx,
        ):
            pass
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_synthesizer_regens_on_missing_tool_use_then_succeeds():
    # First script has no tool_input → tool_use block missing from final message.
    client = MockStreamingClient([
        StreamScript(text_deltas=["I forgot the tool."], tool_input=None),
        StreamScript(text_deltas=["ok now"], tool_input=_valid_tool_input()),
    ])
    ctx = _ctx(client)

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="q",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(client.calls) == 2
    # Generic advisory (not the specific failure list)
    second_user = client.calls[1]["messages"][0]["content"]
    assert "emit_answer" in second_user
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/agents/test_synthesizer.py -v
```

Expected: all four PASS (Task 14 happy-path + three branch tests).

- [ ] **Step 3: Commit**

```bash
git add tests/agents/test_synthesizer.py
git commit -m "test(synthesizer): regen + hard-fail + missing-tool branch coverage"
```

---

## Task 16: Synthesizer grounding guard test

**Files:**
- Create: `tests/agents/test_synthesizer_grounding.py`

Spec-mandated. Three assertions per M4 design §6.4.

- [ ] **Step 1: Write the guard test**

Create `tests/agents/test_synthesizer_grounding.py`:

```python
"""Spec-mandated grounding guard test (M4 design §6.4)."""
from __future__ import annotations

import pytest

from jurist.agents import synthesizer
from jurist.agents.synthesizer import CitationGroundingFailedError
from jurist.agents.synthesizer_tools import (
    FailedCitation,
    build_synthesis_tool_schema,
    verify_citations,
)
from jurist.config import RunContext
from jurist.schemas import (
    CitedArticle, CitedCase, StructuredAnswer, SynthesizerIn,
    UitspraakCitation, WetArtikelCitation,
)
from tests.fixtures.mock_llm import MockStreamingClient, StreamScript


_CANDIDATE_ARTICLE_IDS = ["BWBR0005290/Boek7/A1", "BWBR0005290/Boek7/A2", "BWBR0014315/A10"]
_CANDIDATE_BWB_IDS = ["BWBR0005290", "BWBR0014315"]
_CANDIDATE_ECLIS = ["ECLI:NL:HR:2020:1", "ECLI:NL:RB:2022:2"]


def test_layer_1_schema_enum_equals_candidate_set():
    """Assertion (a): tool schema's `enum` equals the candidate set exactly."""
    schema = build_synthesis_tool_schema(
        _CANDIDATE_ARTICLE_IDS, _CANDIDATE_BWB_IDS, _CANDIDATE_ECLIS,
    )
    wa_item = schema["input_schema"]["properties"]["relevante_wetsartikelen"]["items"]
    uc_item = schema["input_schema"]["properties"]["vergelijkbare_uitspraken"]["items"]
    assert wa_item["properties"]["article_id"]["enum"] == _CANDIDATE_ARTICLE_IDS
    assert wa_item["properties"]["bwb_id"]["enum"] == _CANDIDATE_BWB_IDS
    assert uc_item["properties"]["ecli"]["enum"] == _CANDIDATE_ECLIS


def test_layer_2_verify_returns_unknown_id_not_keyerror():
    """Assertion (b): post-hoc resolver returns a FailedCitation(reason='unknown_id')
    on out-of-set IDs instead of raising KeyError."""
    cited_articles = [CitedArticle(
        bwb_id="BWBR0005290",
        article_id=_CANDIDATE_ARTICLE_IDS[0],
        article_label="Art 1",
        body_text="een voldoende lange brontekst voor het artikel hier aanwezig",
        reason="r",
    )]
    cited_cases = [CitedCase(
        ecli=_CANDIDATE_ECLIS[0],
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.8, reason="r",
        chunk_text="een voldoende lange brontekst voor de uitspraak hier aanwezig",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1",
    )]

    # Tampered: article_id + ecli out of set
    tampered = StructuredAnswer(
        korte_conclusie="conclusie " * 5,
        relevante_wetsartikelen=[
            WetArtikelCitation(
                article_id="IMAGINED/XYZ", bwb_id="BWBR0005290",
                article_label="Gefantaseerd artikel",
                quote="een gefantaseerde passage die we niet kunnen verifiëren omdat imagined",
                explanation="uitleg " * 8,
            ),
        ],
        vergelijkbare_uitspraken=[
            UitspraakCitation(
                ecli="ECLI:NL:FANTASY:9999",
                quote="een gefantaseerde rechtspraakpassage die niet bestaat in ons corpus",
                explanation="uitleg " * 8,
            ),
        ],
        aanbeveling="aanbeveling " * 5,
    )

    # Does NOT raise.
    failures = verify_citations(tampered, cited_articles, cited_cases)

    # Both tampered citations produce unknown_id failures.
    assert FailedCitation(
        kind="wetsartikel", id="IMAGINED/XYZ",
        quote=tampered.relevante_wetsartikelen[0].quote,
        reason="unknown_id",
    ) in failures
    assert any(
        f.kind == "uitspraak" and f.id == "ECLI:NL:FANTASY:9999" and f.reason == "unknown_id"
        for f in failures
    )


@pytest.mark.asyncio
async def test_layer_3_agent_hard_fails_on_imagined_id_twice():
    """Assertion (c): agent end-to-end with a mock producing imagined-ID
    tool_inputs twice in a row raises CitationGroundingFailedError (which
    the orchestrator turns into run_failed{reason:'citation_grounding'})."""
    cited_articles = [CitedArticle(
        bwb_id="BWBR0005290",
        article_id=_CANDIDATE_ARTICLE_IDS[0],
        article_label="Art 1",
        body_text="een voldoende lange brontekst voor het artikel hier aanwezig",
        reason="r",
    )]
    cited_cases = [CitedCase(
        ecli=_CANDIDATE_ECLIS[0],
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.8, reason="r",
        chunk_text="een voldoende lange brontekst voor de uitspraak hier aanwezig",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1",
    )]

    imagined = {
        "korte_conclusie": "conclusie " * 5,
        "relevante_wetsartikelen": [{
            "article_id": "IMAGINED/XYZ",                # out of set
            "bwb_id": "BWBR0005290",
            "article_label": "Gefantaseerd artikel",
            "quote": "een gefantaseerde passage die we niet kunnen verifiëren omdat imagined",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:FANTASY:9999",              # out of set
            "quote": "een gefantaseerde rechtspraakpassage die niet bestaat in ons corpus",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "aanbeveling " * 5,
    }

    client = MockStreamingClient([
        StreamScript(text_deltas=["."], tool_input=imagined),
        StreamScript(text_deltas=["."], tool_input=imagined),
    ])
    ctx = RunContext(kg=None, llm=client, case_store=None, embedder=None)  # type: ignore[arg-type]

    with pytest.raises(CitationGroundingFailedError):
        async for _ in synthesizer.run(
            SynthesizerIn(
                question="q",
                cited_articles=cited_articles,
                cited_cases=cited_cases,
            ),
            ctx=ctx,
        ):
            pass
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/agents/test_synthesizer_grounding.py -v
```

Expected: all three PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/agents/test_synthesizer_grounding.py
git commit -m "test(synthesizer): grounding guard — schema enum + unknown_id + e2e imagined-ID"
```

---

## Task 17: Orchestrator — wrap synthesizer pump

**Files:**
- Modify: `src/jurist/api/orchestrator.py`
- Modify: `tests/api/test_orchestrator.py`

Mirror the decomposer wrap; add `citation_grounding` as the specific reason.

- [ ] **Step 1: Write failing orchestrator tests**

Append to `tests/api/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_synthesizer_grounding_failure_surfaces(monkeypatch):
    """CitationGroundingFailedError → run_failed{reason:"citation_grounding"}."""
    from jurist.agents import synthesizer
    from jurist.agents.synthesizer import CitationGroundingFailedError
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise CitationGroundingFailedError("two strikes")

    monkeypatch.setattr(synthesizer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_sg", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "citation_grounding"
    assert "two strikes" in events[-1].data["detail"]


@pytest.mark.asyncio
async def test_orchestrator_synthesizer_generic_error_is_llm_error(monkeypatch):
    from jurist.agents import synthesizer
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("network down")

    monkeypatch.setattr(synthesizer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_sg2", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "llm_error"
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/api/test_orchestrator.py::test_orchestrator_synthesizer_grounding_failure_surfaces tests/api/test_orchestrator.py::test_orchestrator_synthesizer_generic_error_is_llm_error -v
```

Expected: FAIL — synthesizer pump isn't wrapped yet.

- [ ] **Step 3: Wrap synthesizer pump**

Edit `src/jurist/api/orchestrator.py`. Add import:

```python
from jurist.agents.synthesizer import CitationGroundingFailedError
```

And the synthesizer block, currently untrapped around `synth_final = await _pump(...)`, becomes:

```python
    # 4. Synthesizer — real in M4
    synth_in = SynthesizerIn(
        question=question,
        cited_articles=stat_out.cited_articles,
        cited_cases=case_out.cited_cases,
    )
    try:
        synth_final = await _pump(
            "synthesizer",
            synthesizer.run(synth_in, ctx=ctx),
            run_id,
            buffer,
        )
    except CitationGroundingFailedError as exc:
        logger.warning(
            "run_failed id=%s reason=citation_grounding: %s", run_id, exc,
        )
        await buffer.put(
            TraceEvent(
                type="run_failed", run_id=run_id, ts=_now_iso(),
                data={"reason": "citation_grounding", "detail": str(exc)},
            )
        )
        return
    except Exception as exc:  # noqa: BLE001 — surface LLM/network errors
        logger.exception(
            "run_failed id=%s reason=llm_error detail=%s: %s",
            run_id, type(exc).__name__, exc,
        )
        await buffer.put(
            TraceEvent(
                type="run_failed", run_id=run_id, ts=_now_iso(),
                data={"reason": "llm_error", "detail": f"{type(exc).__name__}: {exc}"},
            )
        )
        return
    synth_out = SynthesizerOut.model_validate(synth_final.data)
```

And update the synthesizer call signature — the M0 fake didn't accept `ctx`; real does. The existing call already reads `synthesizer.run(synth_in)` — update to `synthesizer.run(synth_in, ctx=ctx)` as shown above.

- [ ] **Step 4: Run orchestrator tests**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/api/orchestrator.py tests/api/test_orchestrator.py
git commit -m "feat(orchestrator): wrap synthesizer pump — citation_grounding + llm_error"
```

---

## Task 18: Integration test — full M4 chain on the locked question

**Files:**
- Create: `tests/integration/test_m4_e2e.py`

RUN_E2E-gated. Real Anthropic + real KG + real LanceDB + real Embedder + locked question. Sibling of `tests/integration/test_m3b_case_retriever_e2e.py`.

- [ ] **Step 1: Write the e2e test**

Create `tests/integration/test_m4_e2e.py`:

```python
"""End-to-end test for the full M4 chain on the locked question.

Requires:
- RUN_E2E=1 environment variable.
- ANTHROPIC_API_KEY set.
- data/kg/huurrecht.json present (M1 ingest).
- data/lancedb/cases.lance present and non-empty (M3a ingest).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jurist.agents.synthesizer_tools import _normalize

LOCKED_Q = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_E2E") != "1", reason="RUN_E2E=1 required")
async def test_m4_full_chain_on_locked_question():
    from anthropic import AsyncAnthropic

    from jurist.api.orchestrator import run_question
    from jurist.api.sse import EventBuffer
    from jurist.config import RunContext, settings
    from jurist.embedding import Embedder
    from jurist.kg.networkx_kg import NetworkXKG
    from jurist.vectorstore import CaseStore

    if not settings.kg_path.exists():
        pytest.skip(f"KG missing at {settings.kg_path}; run jurist.ingest first")
    if not settings.lance_path.exists():
        pytest.skip(f"LanceDB missing at {settings.lance_path}; run jurist.ingest.caselaw first")

    kg = NetworkXKG.from_file(settings.kg_path)
    case_store = CaseStore(settings.lance_path)
    case_store.open_or_create()
    if case_store.row_count() == 0:
        pytest.skip("LanceDB is empty")

    embedder = Embedder(model_name=settings.embed_model)
    llm = AsyncAnthropic(api_key=settings.anthropic_api_key)

    ctx = RunContext(kg=kg, llm=llm, case_store=case_store, embedder=embedder)

    buf = EventBuffer()
    await run_question(LOCKED_Q, run_id="run_m4_e2e", buffer=buf, ctx=ctx)

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    # Terminal event is run_finished, not run_failed.
    assert events[-1].type == "run_finished", (
        f"expected run_finished; got {events[-1].type}: {events[-1].data}"
    )

    final = events[-1].data["final_answer"]
    assert len(final["relevante_wetsartikelen"]) >= 1
    assert len(final["vergelijkbare_uitspraken"]) >= 1
    assert len(final["korte_conclusie"]) >= 40
    assert len(final["aanbeveling"]) >= 40

    # Gather citation_resolved events (one per wetsartikel + uitspraak).
    resolved = [ev for ev in events if ev.type == "citation_resolved"]
    assert len(resolved) == (
        len(final["relevante_wetsartikelen"]) + len(final["vergelijkbare_uitspraken"])
    )

    # Grounding: every quote is normalized-substring of the corresponding source.
    # Build lookup from the synth input via the case_retriever's cited_cases event.
    case_finished = next(
        ev for ev in events
        if ev.type == "agent_finished" and ev.agent == "case_retriever"
    )
    stat_finished = next(
        ev for ev in events
        if ev.type == "agent_finished" and ev.agent == "statute_retriever"
    )
    by_article = {a["article_id"]: a for a in stat_finished.data["cited_articles"]}
    by_case = {c["ecli"]: c for c in case_finished.data["cited_cases"]}

    for wa in final["relevante_wetsartikelen"]:
        art = by_article[wa["article_id"]]
        assert _normalize(wa["quote"]) in _normalize(art["body_text"]), (
            f"quote not in article body: {wa['quote'][:80]!r}"
        )
    for uc in final["vergelijkbare_uitspraken"]:
        case = by_case[uc["ecli"]]
        assert _normalize(uc["quote"]) in _normalize(case["chunk_text"]), (
            f"quote not in case chunk: {uc['quote'][:80]!r}"
        )
```

- [ ] **Step 2: Run the gated test**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m4_e2e.py -v
```

Expected: PASS. Typical runtime 30–90 s (real Anthropic calls). If the chain emits `run_failed`, inspect the `detail` and iterate.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_m4_e2e.py
git commit -m "test(integration): M4 e2e — locked question full chain (RUN_E2E gated)"
```

---

## Task 19: CLAUDE.md state update

**Files:**
- Modify: `CLAUDE.md`

Reflect landed state: decomposer + synthesizer real; validator still the permanent stub. Update the state table and the environment quirks / event counts.

- [ ] **Step 1: Update the "What's fake vs. real" table**

Edit `CLAUDE.md`. Find the table:

```markdown
### What's fake vs. real after M3b
```

Replace the section body with:

```markdown
### What's fake vs. real after M4

| Component | State | Becomes real in |
|---|---|---|
| `decomposer` | **Real** — Haiku forced-tool `emit_decomposition`, one-regen-then-hard-fail | — |
| `statute_retriever` | **Real** — Claude Sonnet tool-use loop over the 218-node KG (5 tools) | — |
| `case_retriever` | **Real** — bge-m3 + LanceDB top-150→20 ECLIs + Haiku rerank to 3 | — |
| `synthesizer` | **Real** — Sonnet streaming `messages.stream()`, forced-tool `emit_answer` with per-request `Literal[...]` enums, post-hoc `verify_citations`, one-regen-then-hard-fail to `run_failed{citation_grounding}` | — |
| `validator_stub` | Permanent stub — always returns `valid=True` | — (real validator is v2 scope) |
| `/api/kg` | Real — loads `data/kg/huurrecht.json` at startup | — |

The validator is the only remaining intentional stub; the full agent chain runs on real LLMs end-to-end on the locked question.
```

- [ ] **Step 2: Update the current state paragraph**

Near the top of `CLAUDE.md`, find:

```markdown
Current state: **M3b landed on master** — the `case_retriever` agent runs a real pipeline: ...
```

Replace with:

```markdown
Current state: **M4 landed on master** — the full agent chain runs on real LLMs for the locked question. Decomposer is a single Haiku forced-tool `emit_decomposition` call with one-regen-then-hard-fail. Synthesizer is a Sonnet streaming `messages.stream()` call: pre-tool Dutch prose flows to `agent_thinking`, forced tool `emit_answer` with per-request JSON-Schema `enum` on `article_id` / `bwb_id` / `ecli`, post-hoc `verify_citations` (NFC + whitespace-normalized, case-sensitive strict substring, 40–500 char bounds) against the article bodies and case `chunk_text`. On verification failure: one regen with a Dutch advisory listing the failing citations; still failing → `run_failed{reason:"citation_grounding"}`. Validator remains a permanent stub.
```

- [ ] **Step 3: Update the environment-quirks event-count note**

Find:

```markdown
- Full run emits ~200+ events post-M3b (most are `answer_delta` tokens from the synthesizer's word-level streaming; ...
```

Replace with:

```markdown
- Full run emits ~250+ events post-M4 (most are `answer_delta` tokens from the synthesizer's word-level replay — one per word of the assembled Dutch text; M2 adds a variable `tool_call_*` / `node_visited` / `edge_traversed` / `agent_thinking` count depending on retriever iterations; M3b adds `search_started` + one `case_found` per unique ECLI (up to `caselaw_candidate_eclis`) + one `reranked`; M4 synthesizer adds `agent_thinking` deltas from Sonnet's pre-tool reasoning (typically 5-20 events depending on prompt adherence) + one `citation_resolved` per verified citation). `EventBuffer.max_history` defaults to 500; `settings.max_history_per_run` matches. The full run is sized comfortably inside this budget.
```

- [ ] **Step 4: Add M4 section to the "Architecture" detailed sub-sections**

After the `### Caselaw ingestion (M3a)` section, keep the `### Case retriever (M3b)` section, then add:

```markdown
### Decomposer (M4)

- **Call shape:** `src/jurist/agents/decomposer.py::run` — one non-streaming `ctx.llm.messages.create` with `tool_choice={"type":"tool","name":"emit_decomposition"}`. Haiku 4.5; `max_tokens=1000`; short inline Dutch system prompt (`llm/prompts.py::render_decomposer_system`).
- **Failure shape:** `InvalidDecomposerOutput` on missing tool_use / pydantic-invalid → one regen with Dutch advisory. Second failure → `DecomposerFailedError` → orchestrator `run_failed{reason:"decomposition"}`. Generic exceptions (network, 5xx) → `run_failed{reason:"llm_error"}`.
- **Events:** `agent_started` + `agent_finished{DecomposerOut}`. No `agent_thinking` — system prompt forbids free text, so Haiku goes straight to the tool call.

### Synthesizer (M4)

- **Call shape:** `src/jurist/agents/synthesizer.py::run` — `ctx.llm.messages.stream()` with forced tool `emit_answer`. Pre-tool Dutch reasoning flows live as `agent_thinking`. Sonnet 4.6; `max_tokens=8192`; system prompt loaded from `llm/prompts/synthesizer.system.md` (file-based, cacheable).
- **Closed-set grounding (three layers):** (1) JSON-Schema `enum` on `article_id` / `bwb_id` / `ecli` at the tool-schema level — SDK rejects out-of-set before generation; (2) `StructuredAnswer.model_validate` catches schema bypass; (3) `verify_citations()` strict-substring check against the article `body_text` and case `chunk_text`. One regen with Dutch advisory enumerating `FailedCitation` records. Second failure → `CitationGroundingFailedError` → `run_failed{reason:"citation_grounding"}`.
- **Events:** `agent_started` → `agent_thinking` × N (Sonnet prose, both attempts' prose flows through) → `citation_resolved` × (articles + cases) → `answer_delta` × many (synthetic word-level replay of `korte_conclusie + explanations + aanbeveling`) → `agent_finished{SynthesizerOut}`.
- **Helpers:** `src/jurist/agents/synthesizer_tools.py` — pure sync: `build_synthesis_tool_schema`, `build_synthesis_user_message`, `verify_citations`, `_normalize`, `_validate_attempt`, `_format_regen_advisory`, `FailedCitation`.
- **Tests:** `tests/agents/test_synthesizer_tools.py` (24 pure-helper), `tests/agents/test_synthesizer.py` (4 agent), `tests/agents/test_synthesizer_grounding.py` (3 spec-guard). 1 RUN_E2E-gated at `tests/integration/test_m4_e2e.py`.
```

- [ ] **Step 5: Remove the "Closed-set citation grounding (deferred to M4)" section**

Find:

```markdown
### Closed-set citation grounding (deferred to M4)
```

Delete the entire section — the grounding logic is now described under "Synthesizer (M4)" above.

- [ ] **Step 6: Verify CLAUDE.md structure**

Scan the file end-to-end for stale references to "M3b landed on master" outside the commit-log style narrative, and remove them. `grep -n "M3b" CLAUDE.md` should return only historical references in the architecture sections.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(m4): CLAUDE.md reflects M4 landed — full chain on real LLMs"
```

---

## Post-implementation verification

After Task 19 is committed, run the full suite end-to-end as a sanity pass:

```bash
uv run pytest -v
uv run ruff check .
```

And the gated integration:

```bash
RUN_E2E=1 uv run pytest tests/integration/ -v
```

Then a manual smoke: `uv run python -m jurist.api` in one terminal, `cd web && npm run dev` in another, submit the locked question in the browser. Verify:

1. TracePanel shows the decomposer step (brief, no thinking body).
2. TracePanel shows the statute retriever's tool-call loop.
3. KGPanel lights up `art. 7:248 BW` + neighbors.
4. TracePanel shows the case retriever's `search_started` + `case_found` × N + `reranked`.
5. TracePanel shows the synthesizer's Dutch reasoning deltas as they stream.
6. AnswerPanel fills in token-by-token as `answer_delta` replays.
7. Final structured answer renders with clickable citations — each opens the correct `wetten.overheid.nl` / `uitspraken.rechtspraak.nl` URL in a new tab.

If any step fails, diagnose — **do not** retroactively loosen the grounding assertions. The whole point of M4 is the grounding narrative.

---

*End of plan.*
