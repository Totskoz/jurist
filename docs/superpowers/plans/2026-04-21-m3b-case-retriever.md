# M3b — Case Retriever Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M0 fake `case_retriever` agent with a real pipeline that embeds the decomposer's sub-questions with bge-m3, retrieves the most relevant chunks from the M3a LanceDB index, deduplicates to unique ECLIs, reranks with Haiku via a forced tool schema, and returns 3 `CitedCase`s with Dutch reason strings. Closed-set grounding via JSON-Schema `enum`; one regen then hard-fail via `RerankFailedError` → `run_failed{reason:"case_rerank"}`.

**Architecture:** Five-stage sync-inside-async pipeline (embed → cosine top-K → group-by-ECLI → Haiku rerank → assemble). Pure retrieval helper (`case_retriever_tools.py`) keeps stages 1–3 + schema/prompt builders testable without asyncio or Anthropic. The agent module (`case_retriever.py`) handles events + the Haiku call + regen-or-fail logic. API lifespan grows a fail-fast LanceDB gate and an Embedder cold-load (~5–10s, one-time per process). `CaseStore.query()` signature changes to return `(row, similarity)` tuples. `CaseRetrieverIn` gains a `question: str` field.

**Tech Stack:** Python 3.11, `sentence-transformers` (already landed in M3a) for bge-m3, `lancedb` (M3a) for vector search, `anthropic` Async SDK for Haiku messages.create, `pytest` + `pytest-asyncio` for tests. No new runtime dependencies.

**Authoritative spec:** `docs/superpowers/specs/2026-04-21-m3b-case-retriever-design.md`. When a task references a rule ("per spec §5.2"), read that section before implementing — the spec is the source of truth for WHAT; this plan is HOW.

**Preflight:**
- Working tree clean on `m3b-case-retriever`. Parent-spec amendment (Task 0) and the spec itself are already committed on this branch.
- `ANTHROPIC_API_KEY` must be set in `.env` or the environment for the integration test (Task 13) and for manual API smoke tests; unit tests run fine without it.
- `data/lancedb/cases.lance` must exist and be non-empty (from M3a) for API startup and the integration test to succeed. Tests that need it will skip with a clear message if absent.
- bge-m3 (~2.3 GB) is already cached in `~/.cache/huggingface/hub/` from M3a; no fresh download needed.
- Environment quirks (from CLAUDE.md): `uv` at `C:\Users\totti\.local\bin` may need `export PATH="/c/Users/totti/.local/bin:$PATH"`; API port is 8766; Git LF→CRLF warnings on commit are benign.

**Conventions across all tasks:**
- One task ≈ one commit. Commit at the end of each task after tests pass + `uv run ruff check .` is clean.
- Test-first: write failing test → see it fail → implement → see it pass → commit.
- Paths use forward slashes in markdown and Python; the Windows shell handles the conversion.
- Do NOT use `--no-verify` or bypass pre-commit hooks. If a hook fails, fix the issue and re-commit.
- `tests/fixtures/mock_llm.py` is the house convention for test mocks — this plan extends it rather than adding a parallel file in `src/`.

---

## Task 0: Amend parent spec for M3b

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`

Prerequisite commit on `m3b-case-retriever`. Documents the over-fetch 150→20 approach, adds `question` to `CaseRetrieverIn`, adds three env vars, adds three decision-log entries.

- [ ] **Step 1: Rewrite §5.3 "Implementation" steps 2–3**

Grep for the current block:

```bash
grep -n "LanceDB cosine top-20" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
```

Replace:

```markdown
2. LanceDB cosine top-20 (no subject_uri filter — the keyword fence at ingest time ensures all rows are huurrecht-relevant).
3. Deduplicate to one chunk per ECLI (keep the highest-similarity chunk).
```

with:

```markdown
2. LanceDB cosine top-K chunks (K = `caselaw_candidate_chunks`, default 150; no subject_uri filter — the keyword fence at ingest time ensures all rows are huurrecht-relevant).
3. Group-by-ECLI keeping the best chunk per ECLI; cap at N unique ECLIs (N = `caselaw_candidate_eclis`, default 20). The 150→20 ratio is sized against M3a's observed ~7.8 chunks/case; at the parent spec's original top-20 chunks, post-dedupe collapsed to ~2–3 unique ECLIs, starving the rerank.
```

- [ ] **Step 2: Add `question` to `CaseRetrieverIn` in §5.3**

Replace:

```python
class CaseRetrieverIn(BaseModel):
    sub_questions: list[str]
    statute_context: list[CitedArticle]
```

with:

```python
class CaseRetrieverIn(BaseModel):
    question: str                      # M3b: user's original wording, threaded by orchestrator
    sub_questions: list[str]
    statute_context: list[CitedArticle]
```

- [ ] **Step 3: Add three env vars to §13**

After the `JURIST_CASELAW_LIMIT` line, append:

```markdown
- `JURIST_CASELAW_CANDIDATE_CHUNKS` — default `150`. Cosine over-fetch pool size before ECLI-dedupe (M3b).
- `JURIST_CASELAW_CANDIDATE_ECLIS` — default `20`. Cap on unique ECLIs reaching the Haiku rerank (M3b).
- `JURIST_CASELAW_RERANK_SNIPPET_CHARS` — default `400`. Chunk-text excerpt length per rerank candidate (M3b).
```

- [ ] **Step 4: Add three rows to the §15 decisions log**

Append to the decisions table (after row 15):

```markdown
| 16 | Case retriever over-fetches ~150 chunks → ECLI-dedupe → 20 unique → rerank 3 | Top-20 chunks literally (original §5.3) | M3a corpus stats: avg ~7.8 chunks/case ⇒ top-20 chunks collapses to ~2-3 unique ECLIs, starving the rerank. |
| 17 | Closed-set grounding on case rerank via JSON-Schema `enum` on `ecli` | Post-hoc validation only | Mirrors synthesizer per-request `Literal[...]` (decision #9) at the retrieval boundary as well as the answer boundary. |
| 18 | Case rerank hard-fails (one regen → `RerankFailedError` → `run_failed{case_rerank}`) on malformed output | Soft-degrade to cosine-only top-3 with generic reasons | Consistent with synthesizer's grounding philosophy; loud demo failure beats silent degradation. |
```

- [ ] **Step 5: Verify the edits**

```bash
grep -n "caselaw_candidate_chunks" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "question: str" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
grep -n "case rerank" docs/superpowers/specs/2026-04-17-jurist-v1-design.md
```

Expected: each grep returns at least one hit.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-04-17-jurist-v1-design.md
git commit -m "docs(spec): amend parent spec for M3b — over-fetch, question field, decision log"
```

---

## Task 1: Config settings + RunContext extension

**Files:**
- Modify: `src/jurist/config.py`
- Modify: `tests/test_config.py`

Wire four settings (one of which — `model_rerank` — was already named in parent-spec §13 but never instantiated) and two `RunContext` fields.

- [ ] **Step 1: Write failing tests for new settings**

Append to `tests/test_config.py`:

```python
def test_settings_defaults_m3b() -> None:
    from jurist.config import Settings
    s = Settings()
    assert s.model_rerank == "claude-haiku-4-5-20251001"
    assert s.caselaw_candidate_chunks == 150
    assert s.caselaw_candidate_eclis == 20
    assert s.caselaw_rerank_snippet_chars == 400


def test_settings_m3b_env_overrides(monkeypatch) -> None:
    from jurist.config import Settings
    monkeypatch.setenv("JURIST_MODEL_RERANK", "claude-sonnet-4-6")
    monkeypatch.setenv("JURIST_CASELAW_CANDIDATE_CHUNKS", "200")
    monkeypatch.setenv("JURIST_CASELAW_CANDIDATE_ECLIS", "25")
    monkeypatch.setenv("JURIST_CASELAW_RERANK_SNIPPET_CHARS", "500")
    s = Settings()
    assert s.model_rerank == "claude-sonnet-4-6"
    assert s.caselaw_candidate_chunks == 200
    assert s.caselaw_candidate_eclis == 25
    assert s.caselaw_rerank_snippet_chars == 500
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
uv run pytest tests/test_config.py -v -k "m3b"
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'model_rerank'` (and similar for the others).

- [ ] **Step 3: Add four settings + two RunContext fields**

Edit `src/jurist/config.py`. After the M3a `embed_batch` line add:

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

Extend the TYPE_CHECKING block:

```python
if TYPE_CHECKING:
    from jurist.embedding import Embedder
    from jurist.kg.interface import KnowledgeGraph
    from jurist.vectorstore import CaseStore
```

Extend `RunContext`:

```python
@dataclass(frozen=True)
class RunContext:
    """Per-run injected state. Threaded through the orchestrator to agents
    that need external resources."""

    kg: KnowledgeGraph
    llm: Any
    case_store: CaseStore   # M3b — opened at lifespan
    embedder: Embedder      # M3b — cold-loaded at lifespan (~5-10s one-time)
```

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/test_config.py -v -k "m3b"
```

Expected: PASS (both tests).

- [ ] **Step 5: Run the full config test suite to confirm no regressions**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all green.

- [ ] **Step 6: Ruff check**

```bash
uv run ruff check src/jurist/config.py tests/test_config.py
```

Expected: All checks passed.

**Note:** The existing orchestrator tests construct `RunContext(kg=..., llm=...)` — adding required fields `case_store` and `embedder` without defaults will break them. We deliberately do not give defaults here (they're required, not optional). The orchestrator tests are fixed in Task 11; until then, expect `tests/api/test_orchestrator.py` to fail with TypeError on missing arguments. This is intentional TDD backpressure — the next tasks use a conftest-level fixture to supply these.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/config.py tests/test_config.py
git commit -m "feat(config): M3b settings + RunContext gains case_store and embedder"
```

---

## Task 2: CaseStore.query() returns (row, similarity) tuples

**Files:**
- Modify: `src/jurist/vectorstore.py`
- Modify: `tests/vectorstore/test_vectorstore.py`

`CaseStore.query()` currently drops `_distance`; M3b needs the cosine similarity for the `case_found` event + `CitedCase.similarity` field. Cosine similarity = `1.0 - _distance` for LanceDB's cosine metric.

- [ ] **Step 1: Write a failing test for the new signature**

Open `tests/vectorstore/test_vectorstore.py`. Append:

```python
def test_query_returns_row_similarity_tuples(tmp_path) -> None:
    from jurist.schemas import CaseChunkRow
    from jurist.vectorstore import CaseStore
    import numpy as np

    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()

    # Two distinct vectors; query with one exactly and verify ordering + score.
    v1 = (np.eye(1024)[0]).astype(np.float32).tolist()
    v2 = (np.eye(1024)[1]).astype(np.float32).tolist()
    rows = [
        CaseChunkRow(
            ecli="ECLI:NL:X:2025:1", chunk_idx=0, court="Rb", date="2025-01-01",
            zaaknummer="z1", subject_uri="u", modified="2025-01-01",
            text="t1", embedding=v1, url="u1",
        ),
        CaseChunkRow(
            ecli="ECLI:NL:X:2025:2", chunk_idx=0, court="Rb", date="2025-01-01",
            zaaknummer="z2", subject_uri="u", modified="2025-01-01",
            text="t2", embedding=v2, url="u2",
        ),
    ]
    store.add_rows(rows)

    results = store.query(np.asarray(v1, dtype=np.float32), top_k=2)
    assert len(results) == 2
    # Each entry is a (CaseChunkRow, float) tuple
    (first_row, first_sim), (second_row, second_sim) = results
    assert first_row.ecli == "ECLI:NL:X:2025:1"
    assert second_row.ecli == "ECLI:NL:X:2025:2"
    # Perfect match similarity ≈ 1.0; orthogonal ≈ 0.0
    assert first_sim > second_sim
    assert 0.99 <= first_sim <= 1.0 + 1e-6
    assert -1e-6 <= second_sim <= 0.01
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
uv run pytest tests/vectorstore/test_vectorstore.py::test_query_returns_row_similarity_tuples -v
```

Expected: FAIL — `TypeError: cannot unpack non-iterable CaseChunkRow object` (or similar).

- [ ] **Step 3: Update the `query()` method**

In `src/jurist/vectorstore.py`, replace the entire `query` method:

```python
    def query(
        self,
        vector: np.ndarray,
        *,
        top_k: int = 20,
    ) -> list[tuple[CaseChunkRow, float]]:
        """Cosine top-K. Returns (row, similarity) pairs sorted by descending
        similarity. similarity = 1.0 - _distance (LanceDB cosine metric)."""
        self._require_open()
        vec = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
        df = self._table.search(vec).metric("cosine").limit(top_k).to_pandas()
        out: list[tuple[CaseChunkRow, float]] = []
        for rec in df.to_dict(orient="records"):
            distance = float(rec.pop("_distance", 0.0))
            similarity = 1.0 - distance
            out.append((CaseChunkRow.model_validate(rec), similarity))
        return out
```

- [ ] **Step 4: Run the new test**

```bash
uv run pytest tests/vectorstore/test_vectorstore.py::test_query_returns_row_similarity_tuples -v
```

Expected: PASS.

- [ ] **Step 5: Fix any existing tests that called the old signature**

Other tests in the same file may unpack `query()` results assuming `list[CaseChunkRow]`. Grep:

```bash
grep -n "\.query(" tests/vectorstore/test_vectorstore.py
```

For each call site where the result is consumed as rows directly (e.g., `rows = store.query(...)` then `rows[0].ecli`), update to unpack tuples:

```python
# Before
rows = store.query(vec, top_k=5)
assert rows[0].ecli == "..."

# After
results = store.query(vec, top_k=5)
row, _sim = results[0]
assert row.ecli == "..."
```

- [ ] **Step 6: Run the full vectorstore test suite**

```bash
uv run pytest tests/vectorstore/ -v
```

Expected: all green.

- [ ] **Step 7: Ruff**

```bash
uv run ruff check src/jurist/vectorstore.py tests/vectorstore/test_vectorstore.py
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/jurist/vectorstore.py tests/vectorstore/test_vectorstore.py
git commit -m "feat(vectorstore): CaseStore.query returns (row, similarity) tuples"
```

---

## Task 3: Add `question: str` to CaseRetrieverIn

**Files:**
- Modify: `src/jurist/schemas.py`
- Modify: `src/jurist/api/orchestrator.py`
- Modify: `tests/test_schemas.py` (or an existing schema test file)

One-line schema change + one-line orchestrator update. The existing M0 fake `case_retriever` ignores `input`, so the field can be added without breaking the fake.

- [ ] **Step 1: Write a failing test**

Append to `tests/test_schemas.py`:

```python
def test_case_retriever_in_has_question_field() -> None:
    from jurist.schemas import CaseRetrieverIn, CitedArticle
    inp = CaseRetrieverIn(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Q1", "Q2"],
        statute_context=[
            CitedArticle(
                bwb_id="BWBR0005290",
                article_id="BWBR0005290/Boek7/Artikel248",
                article_label="Boek 7, Artikel 248",
                body_text="body",
                reason="relevant",
            ),
        ],
    )
    assert inp.question == "Mag de huur 15% omhoog?"


def test_case_retriever_in_requires_question() -> None:
    import pytest
    from pydantic import ValidationError
    from jurist.schemas import CaseRetrieverIn
    with pytest.raises(ValidationError):
        CaseRetrieverIn(sub_questions=["Q"], statute_context=[])
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/test_schemas.py -v -k "question"
```

Expected: FAIL (`question` is not yet a field).

- [ ] **Step 3: Add the field**

In `src/jurist/schemas.py`, update `CaseRetrieverIn`:

```python
class CaseRetrieverIn(BaseModel):
    question: str                    # M3b — user's original wording, threaded by orchestrator
    sub_questions: list[str]
    statute_context: list[CitedArticle]
```

- [ ] **Step 4: Thread `question` in the orchestrator**

In `src/jurist/api/orchestrator.py`, find the `CaseRetrieverIn(...)` construction (currently around "3. Case retriever"):

```python
    case_in = CaseRetrieverIn(
        sub_questions=decomposer_out.sub_questions,
        statute_context=stat_out.cited_articles,
    )
```

Replace with:

```python
    case_in = CaseRetrieverIn(
        question=question,
        sub_questions=decomposer_out.sub_questions,
        statute_context=stat_out.cited_articles,
    )
```

- [ ] **Step 5: Run the schema test + the orchestrator test to confirm no regressions (schema-wise)**

```bash
uv run pytest tests/test_schemas.py -v -k "question"
```

Expected: PASS.

Note: `tests/api/test_orchestrator.py` will still fail due to `RunContext` requiring `case_store` + `embedder` from Task 1. We fix that in Task 11.

- [ ] **Step 6: Ruff**

```bash
uv run ruff check src/jurist/schemas.py src/jurist/api/orchestrator.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/schemas.py src/jurist/api/orchestrator.py tests/test_schemas.py
git commit -m "feat(schemas): add question field to CaseRetrieverIn; thread via orchestrator"
```

---

## Task 4: Pure helper — retrieve_candidates + internal types

**Files:**
- Create: `src/jurist/agents/case_retriever_tools.py`
- Create: `tests/agents/test_case_retriever_tools.py`

Pure sync helper. Defines `CaseCandidate`, `RerankPick`, `InvalidRerankOutput`, plus the `retrieve_candidates` function.

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_case_retriever_tools.py`:

```python
"""Pure-helper tests for case_retriever_tools — no asyncio, no Anthropic."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents.case_retriever_tools import (
    CaseCandidate,
    retrieve_candidates,
)
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore


class _FakeEmbedder:
    """Returns a fixed (1, 1024) vector. Ignores input texts."""

    def __init__(self, vector: np.ndarray) -> None:
        self._vector = vector.reshape(1, -1).astype(np.float32)

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        return np.repeat(self._vector, len(texts) or 1, axis=0)


def _row(ecli: str, chunk_idx: int, text: str, embedding: list[float]) -> CaseChunkRow:
    return CaseChunkRow(
        ecli=ecli, chunk_idx=chunk_idx,
        court="Rb", date="2025-01-01", zaaknummer="z",
        subject_uri="u", modified="2025-01-01",
        text=text, embedding=embedding,
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


@pytest.fixture
def populated_store(tmp_path):
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    # 12 chunks across 4 ECLIs: A has 5, B has 4, C has 2, D has 1.
    # Vectors are crafted so that A's chunk 0 has the highest similarity
    # to the query basis e[0], followed by A's chunk 1, then B's chunks…
    def vec(dim: int, scale: float = 1.0) -> list[float]:
        v = np.zeros(1024, dtype=np.float32)
        v[dim] = scale
        return v.tolist()

    rows = [
        _row("ECLI:A", 0, "A best",  vec(0, 1.00)),
        _row("ECLI:A", 1, "A next",  vec(0, 0.95)),
        _row("ECLI:A", 2, "A mid",   vec(0, 0.90)),
        _row("ECLI:A", 3, "A late",  vec(0, 0.85)),
        _row("ECLI:A", 4, "A worst", vec(0, 0.80)),
        _row("ECLI:B", 0, "B best",  vec(0, 0.75)),
        _row("ECLI:B", 1, "B next",  vec(0, 0.70)),
        _row("ECLI:B", 2, "B mid",   vec(0, 0.65)),
        _row("ECLI:B", 3, "B late",  vec(0, 0.60)),
        _row("ECLI:C", 0, "C best",  vec(0, 0.55)),
        _row("ECLI:C", 1, "C next",  vec(0, 0.50)),
        _row("ECLI:D", 0, "D only " * 100, vec(0, 0.45)),
    ]
    store.add_rows(rows)
    return store


def test_retrieve_candidates_preserves_descending_similarity(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32); query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=50,
    )
    assert [c.ecli for c in cands] == ["ECLI:A", "ECLI:B", "ECLI:C", "ECLI:D"]
    sims = [c.similarity for c in cands]
    assert sims == sorted(sims, reverse=True)


def test_retrieve_candidates_keeps_best_chunk_per_ecli(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32); query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=200,
    )
    by_ecli = {c.ecli: c for c in cands}
    # A's best chunk (idx 0, scale 1.00) wins over chunks 1-4
    assert by_ecli["ECLI:A"].snippet.startswith("A best")
    # B's best (idx 0, 0.75)
    assert by_ecli["ECLI:B"].snippet.startswith("B best")


def test_retrieve_candidates_caps_at_eclis_limit(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32); query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=2, snippet_chars=50,
    )
    assert len(cands) == 2
    assert [c.ecli for c in cands] == ["ECLI:A", "ECLI:B"]


def test_retrieve_candidates_truncates_snippet_with_ellipsis(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32); query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=30,
    )
    d = next(c for c in cands if c.ecli == "ECLI:D")
    # D's text is "D only " repeated 100 times; truncated at 30 chars + ellipsis
    assert d.snippet.endswith("…")
    assert len(d.snippet) <= 31   # 30 chars + 1 ellipsis


def test_retrieve_candidates_returns_empty_for_empty_store(tmp_path) -> None:
    store = CaseStore(tmp_path / "empty.lance")
    store.open_or_create()
    embedder = _FakeEmbedder(np.zeros(1024, dtype=np.float32))
    cands = retrieve_candidates(
        store, embedder, "q", chunks_top_k=10, eclis_limit=5, snippet_chars=50,
    )
    assert cands == []


def test_case_candidate_is_frozen() -> None:
    import dataclasses
    c = CaseCandidate(
        ecli="E", court="Rb", date="2025-01-01",
        snippet="s", similarity=0.5, url="u",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.ecli = "F"  # type: ignore[misc]
```

- [ ] **Step 2: Run, confirm all fail (module doesn't exist yet)**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v
```

Expected: ModuleNotFoundError for `jurist.agents.case_retriever_tools`.

- [ ] **Step 3: Implement the helper**

Create `src/jurist/agents/case_retriever_tools.py`:

```python
"""Pure retrieval helper for the M3b case retriever.

Sync; no asyncio, no Anthropic. Types live here because they are internal
in-process handoff types, not serialized across any boundary (spec §4.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from jurist.embedding import Embedder
from jurist.vectorstore import CaseStore


@dataclass(frozen=True)
class CaseCandidate:
    """Pre-rerank handoff from helper → agent. Not persisted; not in schemas.py."""

    ecli: str
    court: str
    date: str
    snippet: str          # first N chars of best chunk, ellipsized
    similarity: float     # cosine from best chunk (0..1]
    url: str


@dataclass(frozen=True)
class RerankPick:
    """Validated row from Haiku's select_cases tool output."""

    ecli: str
    reason: str           # Dutch justification, ≥20 chars post-strip


class InvalidRerankOutput(Exception):
    """Raised by _rerank_once for malformed output. Caught inside the agent;
    a second occurrence is wrapped in RerankFailedError and propagated."""


def retrieve_candidates(
    store: CaseStore,
    embedder: Embedder,
    query: str,
    *,
    chunks_top_k: int,
    eclis_limit: int,
    snippet_chars: int = 400,
) -> list[CaseCandidate]:
    """Embed → cosine top-K chunks → group-by-ECLI (first chunk wins, since
    results are sorted desc by similarity) → take up to `eclis_limit` unique
    ECLIs. Returns [] if the store yields no rows."""
    vec = embedder.encode([query])[0]
    scored = store.query(vec, top_k=chunks_top_k)
    if not scored:
        return []

    # Python dicts preserve insertion order; LanceDB returns rows sorted
    # descending by similarity, so the first occurrence of each ECLI is its
    # highest-scoring chunk.
    seen: dict[str, tuple] = {}  # ecli → (CaseChunkRow, similarity float)
    for row, sim in scored:
        if row.ecli not in seen:
            seen[row.ecli] = (row, sim)
        if len(seen) >= eclis_limit:
            break

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
    return candidates


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


__all__ = [
    "CaseCandidate",
    "RerankPick",
    "InvalidRerankOutput",
    "retrieve_candidates",
]
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
git commit -m "feat(agents): retrieve_candidates pure helper + CaseCandidate/RerankPick dataclasses"
```

---

## Task 5: Pure helper — build_rerank_tool_schema

**Files:**
- Modify: `src/jurist/agents/case_retriever_tools.py`
- Modify: `tests/agents/test_case_retriever_tools.py`

JSON Schema builder for Haiku's forced tool. The `enum` on `ecli` is the closed-set constraint (mirror of synthesizer's per-request `Literal`).

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_case_retriever_tools.py`:

```python
def test_rerank_tool_schema_populates_enum() -> None:
    from jurist.agents.case_retriever_tools import build_rerank_tool_schema
    eclis = ["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]
    schema = build_rerank_tool_schema(eclis)
    assert schema["name"] == "select_cases"
    props = schema["input_schema"]["properties"]["picks"]
    assert props["minItems"] == 3
    assert props["maxItems"] == 3
    assert props["uniqueItems"] is True
    item_props = props["items"]["properties"]
    assert item_props["ecli"]["enum"] == eclis
    assert item_props["ecli"]["type"] == "string"
    assert item_props["reason"]["minLength"] == 20
    assert set(props["items"]["required"]) == {"ecli", "reason"}


def test_rerank_tool_schema_top_level_required_is_picks() -> None:
    from jurist.agents.case_retriever_tools import build_rerank_tool_schema
    schema = build_rerank_tool_schema(["E1", "E2", "E3", "E4"])
    assert schema["input_schema"]["required"] == ["picks"]
    assert schema["input_schema"]["type"] == "object"
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v -k "tool_schema"
```

Expected: FAIL — `ImportError: cannot import name 'build_rerank_tool_schema'`.

- [ ] **Step 3: Implement**

In `src/jurist/agents/case_retriever_tools.py`, add:

```python
def build_rerank_tool_schema(candidate_eclis: list[str]) -> dict:
    """Anthropic tool JSON-schema with per-request `enum` on ecli — the
    closed-set constraint (JSON-Schema form of Pydantic Literal[...])."""
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

Add `"build_rerank_tool_schema"` to the `__all__` list.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v
```

Expected: all green.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
git commit -m "feat(agents): build_rerank_tool_schema — JSON-Schema enum on ecli"
```

---

## Task 6: Pure helper — build_rerank_user_message

**Files:**
- Modify: `src/jurist/agents/case_retriever_tools.py`
- Modify: `tests/agents/test_case_retriever_tools.py`

Dutch prompt builder. Renders question, sub-questions, statute context (label + reason), numbered candidates.

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_case_retriever_tools.py`:

```python
def test_build_rerank_user_message_contains_all_inputs() -> None:
    from jurist.agents.case_retriever_tools import (
        CaseCandidate,
        build_rerank_user_message,
    )
    from jurist.schemas import CitedArticle

    candidates = [
        CaseCandidate(
            ecli="ECLI:NL:RBAMS:2022:5678",
            court="Rechtbank Amsterdam",
            date="2022-03-14",
            snippet="Huurverhoging van 15% …",
            similarity=0.81,
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
        ),
        CaseCandidate(
            ecli="ECLI:NL:HR:2020:1234",
            court="Hoge Raad",
            date="2020-09-11",
            snippet="De verhuurder mag …",
            similarity=0.70,
            url="u",
        ),
    ]
    statute_context = [
        CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text="body",
            reason="Regelt jaarlijkse huurverhoging.",
        ),
    ]
    msg = build_rerank_user_message(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Is 15% rechtmatig?", "Geldt dit ook bij vrije sector?"],
        statute_context=statute_context,
        candidates=candidates,
    )
    # Question rendered
    assert "Mag de huur 15% omhoog?" in msg
    # Sub-questions rendered as bullets
    assert "- Is 15% rechtmatig?" in msg
    assert "- Geldt dit ook bij vrije sector?" in msg
    # Statute label + reason rendered
    assert "Boek 7, Artikel 248" in msg
    assert "Regelt jaarlijkse huurverhoging." in msg
    # Candidates rendered with index + ECLI + court + date + similarity
    assert "[1]" in msg
    assert "ECLI:NL:RBAMS:2022:5678" in msg
    assert "Rechtbank Amsterdam" in msg
    assert "2022-03-14" in msg
    # Similarity numeric (not the CaseCandidate repr)
    assert "0.81" in msg
    # Snippet rendered
    assert "Huurverhoging van 15%" in msg
    # Instruction to call select_cases
    assert "select_cases" in msg


def test_build_rerank_user_message_handles_empty_statute_context() -> None:
    from jurist.agents.case_retriever_tools import (
        CaseCandidate,
        build_rerank_user_message,
    )
    cand = CaseCandidate(
        ecli="E", court="Rb", date="2025-01-01",
        snippet="s", similarity=0.5, url="u",
    )
    msg = build_rerank_user_message(
        question="Q",
        sub_questions=["SQ"],
        statute_context=[],
        candidates=[cand],
    )
    # Does not crash; still contains the question + candidate
    assert "Q" in msg
    assert "ECLI:E" in msg or "E" in msg
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v -k "user_message"
```

Expected: FAIL — `ImportError` on `build_rerank_user_message`.

- [ ] **Step 3: Implement**

In `src/jurist/agents/case_retriever_tools.py`, add:

```python
from jurist.schemas import CitedArticle


def build_rerank_user_message(
    question: str,
    sub_questions: list[str],
    statute_context: list[CitedArticle],
    candidates: list[CaseCandidate],
) -> str:
    """Render the Dutch user message for the Haiku rerank call."""
    lines: list[str] = []
    lines.append(f"Vraag: {question}")
    lines.append("")
    lines.append("Sub-vragen:")
    for sq in sub_questions:
        lines.append(f"- {sq}")
    lines.append("")

    if statute_context:
        lines.append("Relevante wetsartikelen (uit de kennisgraaf):")
        for art in statute_context:
            lines.append(f"- {art.article_label}: {art.reason}")
        lines.append("")

    lines.append(f"Kandidaat-uitspraken ({len(candidates)}):")
    for i, c in enumerate(candidates, start=1):
        header = (
            f"[{i}] {c.ecli} | {c.court} | {c.date} | "
            f"sim {c.similarity:.2f}"
        )
        lines.append(header)
        lines.append(f"    {c.snippet}")
    lines.append("")

    lines.append(
        "Kies 3 uitspraken via `select_cases`. Geef voor elke keuze een "
        "korte Nederlandse reden (1–2 zinnen) die verwijst naar feitelijke "
        "gelijkenis, juridische strekking, of toepassing van de genoemde "
        "artikelen."
    )
    return "\n".join(lines)
```

Add `"build_rerank_user_message"` to `__all__`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/agents/test_case_retriever_tools.py -v
```

Expected: all green.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/agents/case_retriever_tools.py tests/agents/test_case_retriever_tools.py
git commit -m "feat(agents): build_rerank_user_message — Dutch prompt with statute + candidates"
```

---

## Task 7: System prompt — render_case_rerank_system

**Files:**
- Modify: `src/jurist/llm/prompts.py`
- Create: `tests/llm/test_prompts_case_rerank.py`

Static Dutch system prompt, marked cacheable by the agent.

- [ ] **Step 1: Write failing test**

Create `tests/llm/test_prompts_case_rerank.py`:

```python
def test_render_case_rerank_system_is_dutch_and_non_empty() -> None:
    from jurist.llm.prompts import render_case_rerank_system
    text = render_case_rerank_system()
    assert isinstance(text, str)
    assert len(text) > 100
    # Dutch-specific markers
    lower = text.casefold()
    assert "nederlandse" in lower or "nederlands" in lower
    # Mention the task shape
    assert "uitspra" in lower
    assert "select_cases" in text


def test_render_case_rerank_system_is_stable_across_calls() -> None:
    from jurist.llm.prompts import render_case_rerank_system
    assert render_case_rerank_system() == render_case_rerank_system()
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/llm/test_prompts_case_rerank.py -v
```

Expected: FAIL — `ImportError: cannot import name 'render_case_rerank_system'`.

- [ ] **Step 3: Add the renderer**

At the bottom of `src/jurist/llm/prompts.py`, add:

```python
_CASE_RERANK_SYSTEM = """\
Je bent een Nederlandse juridische annotator. Je krijgt een huurrecht-vraag, \
relevante wetsartikelen uit de Nederlandse kennisgraaf, en een lijst \
kandidaat-uitspraken uit de rechtspraak. Kies exact 3 uitspraken die het \
meest relevant zijn voor de vraag en de juridische context van de \
wetsartikelen.

Schrijf voor elke keuze een korte Nederlandse reden (1–2 zinnen) die uitlegt \
waarom deze uitspraak relevant is — verwijs naar feitelijke gelijkenis met \
de vraag, juridische strekking, of toepassing van de genoemde artikelen. \
Gebruik uitsluitend de ECLI's die in de kandidaten-lijst staan.

Roep het hulpmiddel `select_cases` aan met precies 3 keuzes. Geen vrije \
tekst daarbuiten.
"""


def render_case_rerank_system() -> str:
    """Static Dutch system prompt for the Haiku rerank call (M3b).
    Marked cacheable by the agent via `cache_control: ephemeral`."""
    return _CASE_RERANK_SYSTEM
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/llm/test_prompts_case_rerank.py -v
```

Expected: both PASS.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/llm/prompts.py tests/llm/test_prompts_case_rerank.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/llm/prompts.py tests/llm/test_prompts_case_rerank.py
git commit -m "feat(prompts): render_case_rerank_system — static Dutch system prompt"
```

---

## Task 8: Mock Anthropic clients for rerank tests

**Files:**
- Modify: `tests/fixtures/mock_llm.py`
- Create: `tests/fixtures/test_mock_llm_rerank.py`

Adds `MockMessagesClient` + `MockAnthropicForRerank` alongside the existing streaming mock. Non-streaming, one-shot `messages.create` surface mirrors `AsyncAnthropic`.

- [ ] **Step 1: Write failing tests**

Create `tests/fixtures/test_mock_llm_rerank.py`:

```python
"""Self-tests for the rerank mocks."""
from __future__ import annotations

import pytest

from tests.fixtures.mock_llm import MockAnthropicForRerank


@pytest.mark.asyncio
async def test_mock_returns_canned_tool_input() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[
        {"picks": [
            {"ecli": "E1", "reason": "r" * 20},
            {"ecli": "E2", "reason": "r" * 20},
            {"ecli": "E3", "reason": "r" * 20},
        ]},
    ])
    resp = await mock.messages.create(
        model="m", system=[], tools=[], tool_choice={},
        messages=[], max_tokens=100,
    )
    blocks = [b for b in resp.content if b.type == "tool_use"]
    assert len(blocks) == 1
    assert blocks[0].name == "select_cases"
    assert len(blocks[0].input["picks"]) == 3
    assert blocks[0].input["picks"][0]["ecli"] == "E1"


@pytest.mark.asyncio
async def test_mock_raises_queued_exceptions() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[
        RuntimeError("anthropic 503"),
    ])
    with pytest.raises(RuntimeError, match="anthropic 503"):
        await mock.messages.create(model="m", messages=[])


@pytest.mark.asyncio
async def test_mock_exhausted_queue_raises() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[])
    with pytest.raises(RuntimeError, match="queue exhausted"):
        await mock.messages.create(model="m", messages=[])
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/fixtures/test_mock_llm_rerank.py -v
```

Expected: FAIL — `ImportError: cannot import name 'MockAnthropicForRerank'`.

- [ ] **Step 3: Extend `tests/fixtures/mock_llm.py`**

At the bottom of `tests/fixtures/mock_llm.py`, append:

```python
from types import SimpleNamespace


class MockMessagesClient:
    """Mocks `AsyncAnthropic.messages.create` for forced-tool, non-streaming
    calls (M3b case rerank). Returns a canned tool_use response from a queue.

    A queued Exception is raised instead of returning — for simulating 5xx/network.
    An empty queue raises RuntimeError to surface test-setup mistakes."""

    def __init__(self, tool_inputs: list) -> None:
        # Each entry is either a `dict` (canned tool input) or an `Exception`.
        self._queue = list(tool_inputs)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._queue:
            raise RuntimeError("MockMessagesClient: tool_inputs queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        # Mirror the Anthropic SDK's `Message` object shape (enough for our agent).
        tool_use = SimpleNamespace(
            type="tool_use",
            name="select_cases",
            input=item,
        )
        return SimpleNamespace(content=[tool_use])


class MockAnthropicForRerank:
    """Mirrors `AsyncAnthropic`'s `.messages` attribute shape for one-shot
    `messages.create` tests."""

    def __init__(self, tool_inputs: list) -> None:
        self.messages = MockMessagesClient(tool_inputs)


__all__ = [
    "MockAnthropicClient",
    "MockAnthropicForRerank",
    "MockMessagesClient",
    "ScriptedToolUse",
    "ScriptedTurn",
]
```

- [ ] **Step 4: Run the mock tests**

```bash
uv run pytest tests/fixtures/test_mock_llm_rerank.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check tests/fixtures/mock_llm.py tests/fixtures/test_mock_llm_rerank.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/mock_llm.py tests/fixtures/test_mock_llm_rerank.py
git commit -m "test(fixtures): MockAnthropicForRerank for forced-tool non-streaming mocks"
```

---

## Task 9: Rewrite case_retriever agent — happy path

**Files:**
- Modify: `src/jurist/agents/case_retriever.py`
- Create: `tests/agents/test_case_retriever.py` (replaces `test_fake_case_retriever.py`)
- Delete: `tests/agents/test_fake_case_retriever.py`

Replaces the M0 fake. Adds `RerankFailedError`, `_extract_tool_use`, `_validate_picks`, `_rerank_once`, `_rerank_with_retry`, and `run`.

- [ ] **Step 1: Delete the M0 fake test**

```bash
git rm tests/agents/test_fake_case_retriever.py
```

- [ ] **Step 2: Write a failing happy-path test**

Create `tests/agents/test_case_retriever.py`:

```python
"""M3b case retriever — happy path."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents import case_retriever
from jurist.agents.case_retriever_tools import CaseCandidate
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleNode,
    CaseChunkRow,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    KGSnapshot,
)
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicForRerank


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        self.calls.append(list(texts))
        v = np.zeros((len(texts), 1024), dtype=np.float32)
        v[:, 0] = 1.0
        return v


def _row(ecli: str, idx: int, text: str, scale: float) -> CaseChunkRow:
    emb = np.zeros(1024, dtype=np.float32); emb[0] = scale
    return CaseChunkRow(
        ecli=ecli, chunk_idx=idx, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text=text, embedding=emb.tolist(),
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def _kg_stub() -> NetworkXKG:
    snap = KGSnapshot(
        generated_at="t", source_versions={},
        nodes=[ArticleNode(
            article_id="A", bwb_id="BWBX", label="A", title="T",
            body_text="b", outgoing_refs=[],
        )],
        edges=[],
    )
    return NetworkXKG.from_snapshot(snap)


def _populate_store(tmp_path) -> CaseStore:
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    rows = [
        _row("ECLI:NL:A:1", 0, "text A best",  1.00),
        _row("ECLI:NL:A:1", 1, "text A next",  0.95),
        _row("ECLI:NL:B:2", 0, "text B best",  0.80),
        _row("ECLI:NL:C:3", 0, "text C best",  0.60),
        _row("ECLI:NL:D:4", 0, "text D best",  0.55),
    ]
    store.add_rows(rows)
    return store


def _valid_picks(eclis: list[str]) -> dict:
    assert len(eclis) >= 3
    return {"picks": [
        {"ecli": eclis[0], "reason": "Feitelijk zeer vergelijkbaar met de vraag."},
        {"ecli": eclis[1], "reason": "Relevant voor juridische context van huurverhoging."},
        {"ecli": eclis[2], "reason": "Toepassing van Boek 7, Artikel 248 in vergelijkbare zaak."},
    ]}


@pytest.mark.asyncio
async def test_happy_path_emits_expected_events(tmp_path) -> None:
    store = _populate_store(tmp_path)
    embedder = _FakeEmbedder()
    # First 3 ECLIs in cosine order: A, B, C
    mock = MockAnthropicForRerank(tool_inputs=[
        _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]),
    ])
    ctx = RunContext(
        kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder,
    )
    inp = CaseRetrieverIn(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Is 15% rechtmatig?"],
        statute_context=[CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text="body",
            reason="Regelt huurverhoging.",
        )],
    )

    events = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    types = [e.type for e in events]

    assert types[0] == "agent_started"
    assert types[1] == "search_started"
    case_found_events = [e for e in events if e.type == "case_found"]
    assert len(case_found_events) == 4  # A, B, C, D
    assert {e.data["ecli"] for e in case_found_events} == {
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3", "ECLI:NL:D:4",
    }

    reranked = [e for e in events if e.type == "reranked"]
    assert len(reranked) == 1
    assert reranked[0].data["kept"] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]

    assert types[-1] == "agent_finished"
    final_data = events[-1].data
    out = CaseRetrieverOut.model_validate(final_data)
    assert len(out.cited_cases) == 3
    assert [c.ecli for c in out.cited_cases] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    # Similarity flows from best chunk; A's best chunk scale is 1.0
    assert out.cited_cases[0].similarity > 0.99
    # Reason flows from Haiku mock
    assert "vergelijkbaar" in out.cited_cases[0].reason
    # URL flows through from the row
    assert out.cited_cases[0].url == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:A:1"
    )


@pytest.mark.asyncio
async def test_embedder_called_once_with_joined_sub_questions(tmp_path) -> None:
    store = _populate_store(tmp_path)
    embedder = _FakeEmbedder()
    mock = MockAnthropicForRerank(tool_inputs=[
        _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]),
    ])
    ctx = RunContext(kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder)
    inp = CaseRetrieverIn(
        question="Q?", sub_questions=["SQ1", "SQ2"], statute_context=[],
    )
    _ = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    assert len(embedder.calls) == 1
    # Joined with newline
    assert embedder.calls[0] == ["SQ1\nSQ2"]
```

- [ ] **Step 3: Run, confirm fail**

```bash
uv run pytest tests/agents/test_case_retriever.py -v
```

Expected: FAIL — the current `case_retriever.py` is the M0 fake (no real pipeline, no Haiku call).

- [ ] **Step 4: Rewrite `src/jurist/agents/case_retriever.py`**

Replace the entire file contents with:

```python
"""M3b real case retriever: bge-m3 + LanceDB + Haiku rerank."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from jurist.agents.case_retriever_tools import (
    CaseCandidate,
    InvalidRerankOutput,
    RerankPick,
    build_rerank_tool_schema,
    build_rerank_user_message,
    retrieve_candidates,
)
from jurist.config import RunContext, settings
from jurist.llm.prompts import render_case_rerank_system
from jurist.schemas import (
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedCase,
    TraceEvent,
)

logger = logging.getLogger(__name__)

_RERANK_MAX_TOKENS = 1500


class RerankFailedError(Exception):
    """Rerank produced invalid output twice. Orchestrator wraps this into
    run_failed { reason: 'case_rerank', detail: str(exc) }."""


async def run(
    input: CaseRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    yield TraceEvent(type="search_started")

    query = "\n".join(input.sub_questions)
    candidates = retrieve_candidates(
        store=ctx.case_store,
        embedder=ctx.embedder,
        query=query,
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


async def _rerank_with_retry(
    *,
    client: Any,
    candidates: list[CaseCandidate],
    question: str,
    sub_questions: list[str],
    statute_context: list,
) -> list[RerankPick]:
    system = render_case_rerank_system()
    user = build_rerank_user_message(
        question=question,
        sub_questions=sub_questions,
        statute_context=statute_context,
        candidates=candidates,
    )
    candidate_eclis = [c.ecli for c in candidates]
    schema = build_rerank_tool_schema(candidate_eclis)

    try:
        return await _rerank_once(client, system, user, schema, candidate_eclis)
    except InvalidRerankOutput as first_err:
        logger.warning("rerank attempt 1 invalid: %s — retrying once", first_err)
        user_retry = (
            user + "\n\n"
            f"Je vorige antwoord was ongeldig ({first_err}). "
            "Kies exact 3 verschillende ECLI's uit de lijst en geef voor "
            "elk een korte Nederlandse reden (minimaal 20 tekens)."
        )
        try:
            return await _rerank_once(client, system, user_retry, schema, candidate_eclis)
        except InvalidRerankOutput as second_err:
            raise RerankFailedError(
                f"case rerank invalid after retry: {second_err}"
            ) from second_err


async def _rerank_once(
    client: Any,
    system: str,
    user: str,
    schema: dict,
    candidate_eclis: list[str],
) -> list[RerankPick]:
    response = await client.messages.create(
        model=settings.model_rerank,
        system=[{
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[schema],
        tool_choice={"type": "tool", "name": "select_cases"},
        messages=[{"role": "user", "content": user}],
        max_tokens=_RERANK_MAX_TOKENS,
    )
    tool_use = _extract_tool_use(response, "select_cases")
    picks_raw = tool_use.input.get("picks")
    _validate_picks(picks_raw, candidate_eclis)
    return [RerankPick(ecli=p["ecli"], reason=p["reason"].strip()) for p in picks_raw]


def _extract_tool_use(response: Any, expected_name: str):
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and \
                getattr(block, "name", None) == expected_name:
            return block
    raise InvalidRerankOutput(
        f"no tool_use block named {expected_name!r} in response"
    )


def _validate_picks(picks: Any, candidate_eclis: list[str]) -> None:
    if not isinstance(picks, list) or len(picks) != 3:
        raise InvalidRerankOutput(
            f"picks must be a list of exactly 3 items, got {type(picks).__name__} "
            f"len={len(picks) if hasattr(picks, '__len__') else 'n/a'}"
        )
    enum_set = set(candidate_eclis)
    seen: set[str] = set()
    for i, p in enumerate(picks):
        if not isinstance(p, dict):
            raise InvalidRerankOutput(f"pick {i} not a dict")
        ecli = p.get("ecli")
        reason = p.get("reason", "")
        if ecli not in enum_set:
            raise InvalidRerankOutput(
                f"pick {i} ecli {ecli!r} not in candidate set"
            )
        if ecli in seen:
            raise InvalidRerankOutput(f"duplicate ecli {ecli!r}")
        seen.add(ecli)
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise InvalidRerankOutput(
                f"pick {i} reason must be a string of ≥20 chars (post-strip)"
            )


__all__ = ["run", "RerankFailedError"]
```

- [ ] **Step 5: Run the happy-path tests**

```bash
uv run pytest tests/agents/test_case_retriever.py -v
```

Expected: both PASS.

- [ ] **Step 6: Ruff**

```bash
uv run ruff check src/jurist/agents/case_retriever.py tests/agents/test_case_retriever.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/agents/case_retriever.py tests/agents/test_case_retriever.py
git rm --cached tests/agents/test_fake_case_retriever.py 2>/dev/null || true
git commit -m "feat(agents): real case_retriever with bge-m3 + LanceDB + Haiku rerank (happy path)"
```

---

## Task 10: Agent — error paths (regen, hard-fail, <3 candidates, validation)

**Files:**
- Create: `tests/agents/test_case_retriever_errors.py`

Covers every failure path the agent must handle.

- [ ] **Step 1: Write the failing error-path tests**

Create `tests/agents/test_case_retriever_errors.py`:

```python
"""M3b case retriever — error paths. All tests use mocks; no network."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents import case_retriever
from jurist.agents.case_retriever import RerankFailedError
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleNode,
    CaseChunkRow,
    CaseRetrieverIn,
    KGSnapshot,
)
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicForRerank


class _FakeEmbedder:
    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        v = np.zeros((len(texts), 1024), dtype=np.float32)
        v[:, 0] = 1.0
        return v


def _row(ecli: str, idx: int, scale: float) -> CaseChunkRow:
    emb = np.zeros(1024, dtype=np.float32); emb[0] = scale
    return CaseChunkRow(
        ecli=ecli, chunk_idx=idx, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t" * 500, embedding=emb.tolist(),
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def _kg_stub() -> NetworkXKG:
    snap = KGSnapshot(
        generated_at="t", source_versions={},
        nodes=[ArticleNode(
            article_id="A", bwb_id="BWBX", label="A", title="T",
            body_text="b", outgoing_refs=[],
        )],
        edges=[],
    )
    return NetworkXKG.from_snapshot(snap)


def _full_store(tmp_path) -> CaseStore:
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    rows = [
        _row("ECLI:NL:A:1", 0, 1.00),
        _row("ECLI:NL:B:2", 0, 0.80),
        _row("ECLI:NL:C:3", 0, 0.60),
        _row("ECLI:NL:D:4", 0, 0.55),
    ]
    store.add_rows(rows)
    return store


def _valid_picks(eclis: list[str]) -> dict:
    return {"picks": [
        {"ecli": eclis[0], "reason": "Relevant voor feitelijke gelijkenis."},
        {"ecli": eclis[1], "reason": "Past juridisch bij de vraag over huurverhoging."},
        {"ecli": eclis[2], "reason": "Illustreert de werking van Boek 7 Artikel 248."},
    ]}


def _ctx(tmp_path, mock: MockAnthropicForRerank, store=None) -> RunContext:
    return RunContext(
        kg=_kg_stub(), llm=mock,
        case_store=store if store is not None else _full_store(tmp_path),
        embedder=_FakeEmbedder(),
    )


def _input() -> CaseRetrieverIn:
    return CaseRetrieverIn(
        question="Q?", sub_questions=["SQ"], statute_context=[],
    )


@pytest.mark.asyncio
async def test_regen_succeeds_after_invalid_first_response(tmp_path, caplog) -> None:
    # First response: missing tool_use (empty content). Second: valid.
    from types import SimpleNamespace

    class _EmptyResponse(Exception):
        """Not used as exception; we craft a raw mock below."""

    class _FirstBadClient:
        """First call: response with no tool_use. Second: valid picks."""
        def __init__(self) -> None:
            self._second = MockAnthropicForRerank(
                tool_inputs=[_valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])],
            )
            self._calls = 0

        class _Msgs:
            def __init__(self, outer: "_FirstBadClient") -> None:
                self._outer = outer

            async def create(self, **kwargs):
                self._outer._calls += 1
                if self._outer._calls == 1:
                    # Empty response: no tool_use blocks
                    return SimpleNamespace(content=[])
                return await self._outer._second.messages.create(**kwargs)

        @property
        def messages(self):
            return _FirstBadClient._Msgs(self)

    client = _FirstBadClient()
    ctx = _ctx(tmp_path, client)  # type: ignore[arg-type]

    import logging
    caplog.set_level(logging.WARNING, logger="jurist.agents.case_retriever")
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"
    # One regen happened
    assert any("rerank attempt 1 invalid" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_invalid_twice_raises_rerank_failed(tmp_path) -> None:
    # Both responses: empty content (no tool_use)
    from types import SimpleNamespace

    class _AlwaysEmpty:
        class _Msgs:
            async def create(self, **kwargs):
                return SimpleNamespace(content=[])

        @property
        def messages(self):
            return _AlwaysEmpty._Msgs()

    ctx = _ctx(tmp_path, _AlwaysEmpty())  # type: ignore[arg-type]
    with pytest.raises(RerankFailedError, match="invalid after retry"):
        _ = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]


@pytest.mark.asyncio
async def test_less_than_three_candidates_short_circuits(tmp_path) -> None:
    # Store with only 2 unique ECLIs
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([
        _row("ECLI:NL:A:1", 0, 1.0),
        _row("ECLI:NL:B:2", 0, 0.8),
    ])

    class _NoCallClient:
        class _Msgs:
            async def create(self, **kwargs):
                raise AssertionError("must not be called when candidates < 3")

        @property
        def messages(self):
            return _NoCallClient._Msgs()

    ctx = _ctx(tmp_path, _NoCallClient(), store=store)  # type: ignore[arg-type]
    with pytest.raises(RerankFailedError, match="candidates.*<3"):
        _ = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]


@pytest.mark.asyncio
async def test_duplicate_ecli_in_picks_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Feitelijk zeer vergelijkbaar."},
        {"ecli": "ECLI:NL:A:1", "reason": "Tweede keer A — ongeldig, dupliceert."},
        {"ecli": "ECLI:NL:B:2", "reason": "Relevant voor juridische context."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_ecli_not_in_candidate_set_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:Z:99", "reason": "Uit de lucht gegrepen ECLI-niet-in-set."},
        {"ecli": "ECLI:NL:A:1", "reason": "Echte ECLI uit de kandidaten."},
        {"ecli": "ECLI:NL:B:2", "reason": "Nog een echte ECLI uit de kandidaten."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_short_reason_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Ok"},   # too short
        {"ecli": "ECLI:NL:B:2", "reason": "Voldoet aan alle eisen hoop ik."},
        {"ecli": "ECLI:NL:C:3", "reason": "Ook voldoende, minstens twintig tekens."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_wrong_pick_count_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Slechts een pick; te weinig."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"
```

- [ ] **Step 2: Run, confirm tests fail or pass — investigate**

```bash
uv run pytest tests/agents/test_case_retriever_errors.py -v
```

Expected: tests should PASS because the agent from Task 9 already handles these paths. If any fail, the agent code is incomplete; fix before committing.

- [ ] **Step 3: Ruff**

```bash
uv run ruff check tests/agents/test_case_retriever_errors.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/agents/test_case_retriever_errors.py
git commit -m "test(agents): case_retriever error paths — regen, hard-fail, validation"
```

---

## Task 11: Orchestrator integration — case_retriever try/except

**Files:**
- Create: `tests/api/conftest.py`
- Modify: `src/jurist/api/orchestrator.py`
- Modify: `tests/api/test_orchestrator.py`

Mirror the existing `statute_retriever` guard for `case_retriever`: catch `RerankFailedError` → `run_failed{reason:"case_rerank"}`; catch generic `Exception` → `run_failed{reason:"llm_error"}`.

Making `case_retriever` real means the pre-existing orchestrator tests — which build a `MockAnthropicClient` (streaming only; no `.messages.create`) — will crash when `case_retriever.run` calls the rerank path. We stub it at the conftest level for everything under `tests/api/`, and override the stub per-test for the two new failure-path tests.

- [ ] **Step 1: Create an autouse stub fixture for `case_retriever.run`**

Create `tests/api/conftest.py`:

```python
"""Shared fixtures for tests/api/. Keeps orchestrator tests focused on
orchestrator behavior (event stamping, pump ordering, run_finished) by
stubbing the real case_retriever — individual tests can override via
monkeypatch.setattr to exercise the real one or a specific failure."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_case_retriever(monkeypatch):
    from jurist.agents import case_retriever
    from jurist.schemas import CaseRetrieverOut, CitedCase, TraceEvent

    async def _fake(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        yield TraceEvent(type="search_started")
        yield TraceEvent(
            type="case_found",
            data={"ecli": "ECLI:NL:STUB:1", "similarity": 0.9},
        )
        yield TraceEvent(
            type="reranked",
            data={"kept": ["ECLI:NL:STUB:1"]},
        )
        out = CaseRetrieverOut(cited_cases=[CitedCase(
            ecli="ECLI:NL:STUB:1", court="Rb Test", date="2025-01-01",
            snippet="canned snippet for orchestrator tests",
            similarity=0.9,
            reason="Canned reason from tests/api/conftest.py stub fixture.",
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:STUB:1",
        )])
        yield TraceEvent(type="agent_finished", data=out.model_dump())

    monkeypatch.setattr(case_retriever, "run", _fake)
    yield
```

- [ ] **Step 2: Update the `_orch_ctx()` helper to include a minimal `case_store` + `embedder`**

The existing helper in `tests/api/test_orchestrator.py` only sets `kg` and `llm`. `RunContext` (after Task 1) requires two more fields. Because Step 1's stub replaces `case_retriever.run`, the store does not need to be queryable — a trivial tmp-dir store + a no-op embedder are enough to satisfy construction.

Replace the existing `_orch_ctx()`:

```python
def _orch_ctx() -> RunContext:
    import tempfile
    from pathlib import Path
    import numpy as np
    from jurist.vectorstore import CaseStore
    from jurist.schemas import CaseChunkRow

    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="Art A", title="T",
            body_text="b", outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    kg = NetworkXKG.from_snapshot(snap)
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    # One-row CaseStore — satisfies RunContext construction; the autouse
    # conftest stub replaces case_retriever.run so the store is never queried.
    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    v = np.zeros(1024, dtype=np.float32).tolist()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=v, url="u",
    )])

    class _NoOpEmbedder:
        def encode(self, texts, *, batch_size=32):
            return np.zeros((len(texts), 1024), dtype=np.float32)

    return RunContext(
        kg=kg,
        llm=MockAnthropicClient(script),
        case_store=store,
        embedder=_NoOpEmbedder(),
    )
```

- [ ] **Step 3: Update the pre-existing `test_orchestrator_emits_run_failed_on_llm_error` to pass case_store + embedder**

It currently builds its own `ctx` inline (doesn't use `_orch_ctx`). Replace with:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_llm_error():
    """Per spec §5: uncaught exception in statute_retriever → run_failed."""
    import tempfile
    from pathlib import Path
    import numpy as np
    from jurist.vectorstore import CaseStore
    from jurist.schemas import CaseChunkRow

    nodes = [ArticleNode(
        article_id="A", bwb_id="BWBX", label="A", title="T",
        body_text="b", outgoing_refs=[],
    )]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    kg = NetworkXKG.from_snapshot(snap)

    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    v = np.zeros(1024, dtype=np.float32).tolist()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=v, url="u",
    )])

    class _NoOpEmbedder:
        def encode(self, texts, *, batch_size=32):
            return np.zeros((len(texts), 1024), dtype=np.float32)

    ctx = RunContext(
        kg=kg, llm=_BoomLLM(), case_store=store, embedder=_NoOpEmbedder(),
    )
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=ctx)
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "llm_error"
    assert "anthropic 503" in final.data["detail"]
    assert not any(e.type == "run_finished" for e in events)
```

- [ ] **Step 4: Append the two new failure-path tests**

Append to `tests/api/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_rerank_failed(monkeypatch):
    """RerankFailedError from case_retriever → run_failed{case_rerank}."""
    from jurist.agents import case_retriever
    from jurist.agents.case_retriever import RerankFailedError
    from jurist.schemas import TraceEvent

    async def _failing_case_retriever(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RerankFailedError("mock: invalid after retry")

    # Overrides the autouse conftest stub
    monkeypatch.setattr(case_retriever, "run", _failing_case_retriever)

    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "case_rerank"
    assert "invalid after retry" in final.data["detail"]
    assert not any(e.type == "run_finished" for e in events)


@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_generic_case_exception(monkeypatch):
    """Generic Exception from case_retriever → run_failed{llm_error}."""
    from jurist.agents import case_retriever
    from jurist.schemas import TraceEvent

    async def _exploding_case_retriever(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("anthropic 429 rate limited")

    monkeypatch.setattr(case_retriever, "run", _exploding_case_retriever)

    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "llm_error"
    assert "429" in final.data["detail"]
```

- [ ] **Step 5: Run, confirm the two new tests fail**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected:
- `test_orchestrator_emits_run_failed_on_rerank_failed` — FAIL (`RerankFailedError` not caught by orchestrator).
- `test_orchestrator_emits_run_failed_on_generic_case_exception` — FAIL (generic Exception not caught either).
- Pre-existing tests PASS (conftest stub + updated `_orch_ctx` make them work).

- [ ] **Step 6: Wrap case_retriever in try/except**

In `src/jurist/api/orchestrator.py`, find the current `case_retriever` block:

```python
    # 3. Case retriever
    case_in = CaseRetrieverIn(
        question=question,
        sub_questions=decomposer_out.sub_questions,
        statute_context=stat_out.cited_articles,
    )
    case_final = await _pump(
        "case_retriever",
        case_retriever.run(case_in),
        run_id,
        buffer,
    )
    case_out = CaseRetrieverOut.model_validate(case_final.data)
```

Replace with (note: `case_retriever.run` now needs `ctx=ctx`):

```python
    # 3. Case retriever — real in M3b
    case_in = CaseRetrieverIn(
        question=question,
        sub_questions=decomposer_out.sub_questions,
        statute_context=stat_out.cited_articles,
    )
    try:
        case_final = await _pump(
            "case_retriever",
            case_retriever.run(case_in, ctx=ctx),
            run_id,
            buffer,
        )
    except RerankFailedError as exc:
        logger.exception(
            "run_failed id=%s reason=case_rerank: %s", run_id, exc,
        )
        await buffer.put(
            TraceEvent(
                type="run_failed", run_id=run_id, ts=_now_iso(),
                data={"reason": "case_rerank", "detail": str(exc)},
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
    case_out = CaseRetrieverOut.model_validate(case_final.data)
```

Add the import at the top:

```python
from jurist.agents.case_retriever import RerankFailedError
```

- [ ] **Step 7: Run orchestrator tests**

```bash
uv run pytest tests/api/test_orchestrator.py -v
```

Expected: all pass (including the two new failure-path tests).

- [ ] **Step 8: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all green (or only `RUN_E2E`-gated skips).

- [ ] **Step 9: Ruff**

```bash
uv run ruff check src/jurist/api/orchestrator.py tests/api/conftest.py tests/api/test_orchestrator.py
```

Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/jurist/api/orchestrator.py tests/api/conftest.py tests/api/test_orchestrator.py
git commit -m "feat(orchestrator): wrap case_retriever — RerankFailedError → run_failed{case_rerank}"
```

---

## Task 12: API lifespan — LanceDB gate + Embedder cold-load

**Files:**
- Modify: `src/jurist/api/app.py`
- Create: `tests/api/test_lifespan_m3b.py`

Fail-fast on missing/empty LanceDB; cold-load Embedder; thread both into `RunContext`.

- [ ] **Step 1: Write failing lifespan tests**

Create `tests/api/test_lifespan_m3b.py`:

```python
"""Lifespan gate tests for M3b — LanceDB presence + Embedder wiring."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_lifespan_raises_when_lance_path_missing(tmp_path, monkeypatch) -> None:
    from jurist.api.app import lifespan
    from jurist.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=True)
    # kg_path, lance_path, cases_dir all derive from data_dir
    # Create a KG so the KG gate passes — the LanceDB gate is what we test
    (tmp_path / "kg").mkdir()
    (tmp_path / "kg" / "huurrecht.json").write_text(
        '{"generated_at":"t","source_versions":{},"nodes":[],"edges":[]}'
    )
    # lance_path intentionally absent

    import asyncio
    from fastapi import FastAPI
    app = FastAPI()

    async def _run():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="LanceDB.*missing"):
        asyncio.run(_run())


def test_lifespan_raises_when_lance_index_empty(tmp_path, monkeypatch) -> None:
    from jurist.api.app import lifespan
    from jurist.config import settings
    from jurist.vectorstore import CaseStore

    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=True)
    (tmp_path / "kg").mkdir()
    (tmp_path / "kg" / "huurrecht.json").write_text(
        '{"generated_at":"t","source_versions":{},"nodes":[],"edges":[]}'
    )
    # Create an empty lance table
    (tmp_path / "lancedb").mkdir()
    store = CaseStore(tmp_path / "lancedb" / "cases.lance")
    store.open_or_create()
    # Do NOT add any rows

    import asyncio
    from fastapi import FastAPI
    app = FastAPI()

    async def _run():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="LanceDB.*empty"):
        asyncio.run(_run())
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/api/test_lifespan_m3b.py -v
```

Expected: FAIL — the current lifespan does not gate LanceDB.

- [ ] **Step 3: Update the lifespan**

In `src/jurist/api/app.py`, add imports at the top (near the existing ones):

```python
from jurist.embedding import Embedder
from jurist.vectorstore import CaseStore
```

Replace the entire `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # KG gate (existing)
    try:
        app.state.kg = NetworkXKG.load_from_json(settings.kg_path)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"KG not found at {settings.kg_path}. "
            f"Run: uv run python -m jurist.ingest.statutes"
        ) from e
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(
            f"KG at {settings.kg_path} failed to load: {e}. "
            f"Re-run: uv run python -m jurist.ingest.statutes --refresh"
        ) from e
    logger.info(
        "Loaded KG: %d nodes, %d edges from %s",
        len(app.state.kg.all_nodes()),
        len(app.state.kg.all_edges()),
        settings.kg_path,
    )

    # LanceDB gate (M3b)
    if not settings.lance_path.exists():
        raise RuntimeError(
            f"LanceDB case index missing at {settings.lance_path}. "
            f"Run: uv run python -m jurist.ingest.caselaw"
        )
    case_store = CaseStore(settings.lance_path)
    case_store.open_or_create()
    if case_store.row_count() == 0:
        raise RuntimeError(
            f"LanceDB at {settings.lance_path} is empty. "
            f"Run: uv run python -m jurist.ingest.caselaw"
        )
    app.state.case_store = case_store
    logger.info(
        "Opened case index: %d rows across %d ECLIs at %s",
        case_store.row_count(),
        len(case_store.all_eclis()),
        settings.lance_path,
    )

    # Embedder cold-load (~5-10s, one-time per process)
    logger.info(
        "Loading embedder %s (cold load ~5-10s; subsequent requests are fast)",
        settings.embed_model,
    )
    app.state.embedder = Embedder(model_name=settings.embed_model)
    logger.info("Embedder ready")

    app.state.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    logger.info("Anthropic client ready (model_retriever=%s model_rerank=%s)",
                settings.model_retriever, settings.model_rerank)
    yield
```

Update the `ask()` handler to pass the new fields to `RunContext`:

```python
@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    question_id = f"run_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=settings.max_history_per_run)
    _runs[question_id] = buf
    ctx = RunContext(
        kg=app.state.kg,
        llm=app.state.anthropic,
        case_store=app.state.case_store,
        embedder=app.state.embedder,
    )
    task = asyncio.create_task(run_question(req.question, question_id, buf, ctx))
    _tasks[question_id] = task
    return AskResponse(question_id=question_id)
```

- [ ] **Step 4: Run the lifespan tests**

```bash
uv run pytest tests/api/test_lifespan_m3b.py -v
```

Expected: both PASS.

- [ ] **Step 5: Run existing API tests**

```bash
uv run pytest tests/api/ -v
```

Expected: all pass. If any of `test_endpoints.py`, `test_kg_endpoint.py`, or `test_sse.py` broke because their fixtures bypass the lifespan or construct `RunContext` manually, fix them by mirroring the `_orch_ctx()` pattern from Task 11.

- [ ] **Step 6: Ruff**

```bash
uv run ruff check src/jurist/api/app.py tests/api/test_lifespan_m3b.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/api/app.py tests/api/test_lifespan_m3b.py
git commit -m "feat(api): lifespan gates LanceDB + cold-loads Embedder; RunContext threads both"
```

---

## Task 13: Integration test — RUN_E2E real Haiku + real LanceDB

**Files:**
- Create: `tests/integration/test_m3b_case_retriever_e2e.py`

RUN_E2E-gated. Real Embedder, real LanceDB (must exist — skip otherwise), real Haiku. Asserts the acceptance criteria from spec §15 on the locked question.

- [ ] **Step 1: Create the integration test**

Create `tests/integration/test_m3b_case_retriever_e2e.py`:

```python
"""M3b end-to-end integration test. Gated on RUN_E2E=1.

Requires:
- ANTHROPIC_API_KEY in env
- data/lancedb/cases.lance populated from M3a ingest
- bge-m3 model in HuggingFace cache
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_RUN_E2E = os.getenv("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_E2E,
    reason="integration test — set RUN_E2E=1 to run (costs Anthropic tokens + ~30s)",
)


@pytest.mark.asyncio
async def test_m3b_locked_question_returns_three_valid_cases() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    from anthropic import AsyncAnthropic
    from jurist.agents import case_retriever
    from jurist.config import RunContext, settings
    from jurist.embedding import Embedder
    from jurist.kg.networkx_kg import NetworkXKG
    from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut, CitedArticle
    from jurist.vectorstore import CaseStore

    # Preconditions
    if not settings.lance_path.exists():
        pytest.skip(
            f"LanceDB index missing at {settings.lance_path} — "
            "run `uv run python -m jurist.ingest.caselaw` first"
        )
    if not settings.kg_path.exists():
        pytest.skip(
            f"KG missing at {settings.kg_path} — "
            "run `uv run python -m jurist.ingest.statutes` first"
        )

    # Wire up real RunContext
    kg = NetworkXKG.load_from_json(settings.kg_path)
    store = CaseStore(settings.lance_path)
    store.open_or_create()
    assert store.row_count() > 0, "LanceDB is empty"

    embedder = Embedder(model_name=settings.embed_model)
    llm = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    ctx = RunContext(kg=kg, llm=llm, case_store=store, embedder=embedder)

    # Realistic M4-shape input (stand in for the decomposer + M2 retriever
    # that are wired earlier in the full pipeline).
    inp = CaseRetrieverIn(
        question=(
            "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
        ),
        sub_questions=[
            "Mag een verhuurder de huur eenzijdig met 15% verhogen?",
            "Geldt de maximale huurverhoging voor zowel gereguleerde als "
            "geliberaliseerde huurwoningen?",
            "Wat kan de huurder doen tegen een buitensporige huurverhoging?",
        ],
        statute_context=[
            CitedArticle(
                bwb_id="BWBR0005290",
                article_id="BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel248",
                article_label="Boek 7, Artikel 248",
                body_text="De verhuurder kan tot aan het tijdstip...",
                reason="Regelt jaarlijkse huurverhoging bij gereguleerde huur.",
            ),
        ],
    )

    events = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    final = events[-1]
    assert final.type == "agent_finished", \
        f"expected agent_finished, got {final.type} events={[e.type for e in events]}"
    out = CaseRetrieverOut.model_validate(final.data)

    # Acceptance assertions (spec §15)
    assert len(out.cited_cases) == 3

    all_eclis = store.all_eclis()
    for c in out.cited_cases:
        # ECLI exists in LanceDB
        assert c.ecli in all_eclis, f"rerank picked unknown ECLI {c.ecli}"
        # Similarity in (0, 1]
        assert 0.0 < c.similarity <= 1.0 + 1e-6, \
            f"implausible similarity {c.similarity} for {c.ecli}"
        # Reason non-trivial Dutch
        assert len(c.reason.strip()) >= 20, \
            f"reason too short for {c.ecli}: {c.reason!r}"
        # Contains at least one Dutch letter (lowercase ascii a-z)
        assert re.search(r"[a-z]", c.reason.casefold()), \
            f"reason lacks letters: {c.reason!r}"
        # URL pattern
        assert re.match(
            r"^https://uitspraken\.rechtspraak\.nl/details\?id=ECLI:",
            c.url,
        ), f"unexpected URL: {c.url}"

    # 3 distinct ECLIs
    assert len({c.ecli for c in out.cited_cases}) == 3
```

- [ ] **Step 2: Verify the test is correctly SKIP-ed without RUN_E2E**

```bash
uv run pytest tests/integration/test_m3b_case_retriever_e2e.py -v
```

Expected: `1 skipped` with the reason message.

- [ ] **Step 3: Run the test with RUN_E2E=1 (only if LanceDB is populated on this host)**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m3b_case_retriever_e2e.py -v -s
```

Expected: PASS in ~10-30 seconds. Watch for:
- "Loading BAAI/bge-m3…" (5-10s)
- LanceDB query + Haiku call (~2-4s)
- All assertions green.

If any assertion fails, the spec's acceptance criterion is violated — investigate before committing. A common failure would be Haiku's reasons being under 20 chars or non-Dutch; bump `minLength` in the schema or sharpen the system prompt.

- [ ] **Step 4: Ruff**

```bash
uv run ruff check tests/integration/test_m3b_case_retriever_e2e.py
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_m3b_case_retriever_e2e.py
git commit -m "test(integration): M3b locked-question e2e (RUN_E2E-gated, real bge-m3 + Haiku)"
```

---

## Task 14: Docs + `.env.example` update

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.env.example`
- Modify: `README.md` (if present and relevant)

Document the agent state change, the new startup latency, and the new env vars.

- [ ] **Step 1: Update CLAUDE.md "What's fake vs. real" table**

In `CLAUDE.md`, find the section that lists agent states (search for the row "case_retriever"):

```markdown
| `case_retriever` | M0 fake — emits `FAKE_CASES` one by one | M3b (bge-m3 + LanceDB + Haiku rerank) |
```

Replace with:

```markdown
| `case_retriever` | **Real** — bge-m3 + LanceDB top-150→20 ECLIs + Haiku rerank to 3 | — |
```

- [ ] **Step 2: Update the "Current state" paragraph**

Find the paragraph starting with "Current state: **M3a landed on master**". Update to reflect M3b landing:

```markdown
Current state: **M3b landed on m3b-case-retriever (pending merge)** — the `case_retriever` agent runs a real pipeline: embed sub-questions with bge-m3, retrieve top-150 LanceDB chunks, dedupe to 20 unique ECLIs, Haiku-rerank to 3 `CitedCase`s with Dutch reason strings. Closed-set grounding via JSON-Schema `enum` on ECLI; one regen then `run_failed{reason:"case_rerank"}` on malformed output. API startup adds an Embedder cold-load (~5-10s, one-time per process) and a fail-fast gate on `data/lancedb/cases.lance`. Decomposer and synthesizer remain M0 fakes (→ M4); validator is a permanent stub.
```

- [ ] **Step 3: Update the Commands / Start API server note**

Find:

```markdown
- Start API server: `uv run python -m jurist.api` — listens on `http://127.0.0.1:8766` with hot-reload. API hard-fails at startup if `data/kg/huurrecht.json` is missing — run the KG build step first on a fresh clone.
```

Replace with:

```markdown
- Start API server: `uv run python -m jurist.api` — listens on `http://127.0.0.1:8766` with hot-reload. API hard-fails at startup if `data/kg/huurrecht.json` OR `data/lancedb/cases.lance` is missing/empty — run both ingest steps first on a fresh clone. First boot additionally cold-loads bge-m3 (~5-10s; ~1.1 GB RAM resident).
```

- [ ] **Step 4: Update the M3a-observations paragraph**

Find the paragraph that starts with "Full run emits ~200+ events post-M2…" and confirm it still fits. If there's a "what M3b will bring" sentence that's now stale, remove it.

- [ ] **Step 5: Update `.env.example`**

Append to `.env.example`:

```bash
# --- M3b: case retriever -----------------------------------------------

# Rerank model. Must be a Claude tool-use capable model.
# JURIST_MODEL_RERANK=claude-haiku-4-5-20251001

# Cosine over-fetch pool (chunks) before ECLI-dedupe. M3a corpus averages
# ~7.8 chunks/case, so 150 chunks statistically dedupes to ≥20 unique ECLIs.
# JURIST_CASELAW_CANDIDATE_CHUNKS=150

# Cap on unique ECLIs reaching the rerank.
# JURIST_CASELAW_CANDIDATE_ECLIS=20

# Chunk-text excerpt length per candidate (in the rerank prompt).
# JURIST_CASELAW_RERANK_SNIPPET_CHARS=400
```

- [ ] **Step 6: README (if it exists and has a section on the agent state)**

```bash
grep -n "case_retriever" README.md 2>/dev/null
```

If hits exist, update the M3a-era language that says "M3b will replace the fake" to "M3b replaced the fake; case retriever runs bge-m3 + LanceDB + Haiku rerank."

- [ ] **Step 7: Sanity grep — no stale "fake case" references outside tests/fakes**

```bash
grep -rn "fake case" docs/ CLAUDE.md README.md 2>/dev/null | grep -v fixtures
```

Expected: only historical references in the discussions / M3a-plan documents (those are preserved chronologically).

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md .env.example
git add README.md 2>/dev/null || true
git commit -m "docs(m3b): CLAUDE.md state, .env.example env vars, startup latency note"
```

---

## Task 15: Final verification

**Files:** No edits (verification only; manual fixes if anything surfaces).

- [ ] **Step 1: Full test suite**

```bash
uv run pytest -v
```

Expected: all green; `RUN_E2E`-gated tests skip.

- [ ] **Step 2: Ruff across the entire repo**

```bash
uv run ruff check .
```

Expected: "All checks passed!"

- [ ] **Step 3: RUN_E2E integration (requires ANTHROPIC_API_KEY + populated LanceDB)**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m3b_case_retriever_e2e.py -v -s
```

Expected: PASS.

- [ ] **Step 4: Manual smoke against the running API (optional, operator-driven)**

Start the backend and frontend in two shells:

```bash
# shell 1
uv run python -m jurist.api

# shell 2
cd web && npm run dev
```

Open `http://localhost:5173`, submit the locked question:

> *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*

Verify:
- KG animates through the statute retriever's path, culminating in art. 7:248 BW lit.
- `case_retriever` section in the trace panel shows: `agent_started` → `search_started` → 20 × `case_found` → `reranked {kept:[3]}` → `agent_finished`.
- Three cases render in the answer panel (or the fake synthesizer's placeholder reflects them); each citation opens `https://uitspraken.rechtspraak.nl/details?id=ECLI:...` in a new tab.
- No console errors; no `run_failed` in the trace panel.

If anything regresses, open an issue comment rather than silently patching — the v1 acceptance gate is "no manual interventions during a live demo."

- [ ] **Step 5: Final branch-ready check**

```bash
git status
git log --oneline master..HEAD
```

Expected: working tree clean; 15 commits on `m3b-case-retriever` above `master` (Task 0 spec amend + Tasks 1–14 features + Task 15 is verification only, no commit).

The branch is now ready for review, merge to master, and a brief CLAUDE.md refresh on master if the merge commit's branch-name line wants updating.

---

*End of plan.*
