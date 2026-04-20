# M2 — Real Statute Retriever Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M0 fake `statute_retriever` with a real Claude Sonnet 4.6 tool-use loop over the M1 huurrecht KG (218 nodes, 283 edges).

**Architecture:** Thin Anthropic wrapper (`run_tool_loop`) drives the agent. Tool implementations sit in a `ToolExecutor` bound to the loaded `KnowledgeGraph`. Agent translates internal `LoopEvent`s to the existing `TraceEvent` protocol so the frontend is unchanged. `RunContext(kg, llm)` threads state through the orchestrator.

**Tech Stack:** Python 3.11, `anthropic` SDK (new dep), FastAPI, NetworkX, pytest + pytest-asyncio.

**Authoritative spec:** `docs/superpowers/specs/2026-04-20-m2-statute-retriever-design.md`. When a task references a rule ("per spec §5"), read that section before implementing — the spec is the source of truth for WHAT; this plan is HOW.

**Preflight:**
- Working tree must be clean on branch `m2-statute-retriever`.
- `data/kg/huurrecht.json` exists (run `uv run python -m jurist.ingest.statutes` if not).
- `ANTHROPIC_API_KEY` in `.env` (only required for Task 22's gated e2e; unit tests mock the client).

**Conventions across all tasks:**
- One task ≈ one commit. Commit at the end of each task after tests pass + `uv run ruff check .` is clean.
- Test-first where feasible: write failing test → see fail → implement → see pass → commit.
- Paths use forward slashes. Windows CRLF warnings on commit are benign (per `CLAUDE.md`).
- If `uv` isn't on `PATH`: `export PATH="/c/Users/totti/.local/bin:$PATH"`.

---

## Task 1: Add anthropic SDK dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `anthropic` to dependencies**

Edit `pyproject.toml` — insert into the `dependencies` list (alphabetical placement, after `"sse-starlette>=2.1"`):

```toml
dependencies = [
    "anthropic>=0.39",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
    "sse-starlette>=2.1",
    "lxml>=5.3",
    "httpx>=0.27",
    "networkx>=3.3",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --extra dev`
Expected: installs `anthropic` and its transitive deps without conflicts.

- [ ] **Step 3: Verify importable**

Run: `uv run python -c "from anthropic import AsyncAnthropic; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add anthropic SDK dependency for M2"
```

---

## Task 2: Config settings + RunContext

**Files:**
- Modify: `src/jurist/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests first**

Append to `tests/test_config.py` (check existing imports; add if needed):

```python
from jurist.config import RunContext, Settings


def test_settings_exposes_m2_fields():
    s = Settings()
    assert s.model_retriever == "claude-sonnet-4-6"
    assert s.max_retriever_iters == 15
    assert s.retriever_wall_clock_cap_s == 90.0
    assert s.statute_catalog_snippet_chars == 200


def test_runcontext_is_frozen_dataclass():
    ctx = RunContext(kg=object(), llm=object())
    assert ctx.kg is not None
    assert ctx.llm is not None
    with __import__("pytest").raises(Exception):  # FrozenInstanceError
        ctx.kg = object()  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'jurist.config' has no attribute 'RunContext'` (or similar).

- [ ] **Step 3: Implement**

Replace `src/jurist/config.py` contents with:

```python
"""Settings object + per-run context. Expands as milestones land."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from jurist.kg.interface import KnowledgeGraph

load_dotenv()


@dataclass(frozen=True)
class Settings:
    max_history_per_run: int = int(os.getenv("JURIST_MAX_HISTORY_PER_RUN", "500"))
    cors_allow_origin: str = os.getenv("JURIST_CORS_ORIGIN", "http://localhost:5173")
    data_dir: Path = Path(os.getenv("JURIST_DATA_DIR", "./data"))

    # M2 — statute retriever
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    model_retriever: str = os.getenv("JURIST_MODEL_RETRIEVER", "claude-sonnet-4-6")
    max_retriever_iters: int = int(os.getenv("JURIST_MAX_RETRIEVER_ITERS", "15"))
    retriever_wall_clock_cap_s: float = float(
        os.getenv("JURIST_RETRIEVER_WALL_CLOCK_CAP_S", "90")
    )
    statute_catalog_snippet_chars: int = int(
        os.getenv("JURIST_STATUTE_CATALOG_SNIPPET_CHARS", "200")
    )

    @property
    def kg_path(self) -> Path:
        return self.data_dir / "kg" / "huurrecht.json"


settings = Settings()


@dataclass(frozen=True)
class RunContext:
    """Per-run injected state. Threaded through the orchestrator to agents
    that need external resources (KG, LLM client, later: vector store)."""

    kg: "KnowledgeGraph"
    llm: Any  # AsyncAnthropic — kept untyped at runtime to avoid importing
              # the Anthropic SDK in contexts that don't need it (tests
              # pass mock objects).
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all new tests PASS; existing ones still PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/jurist/config.py tests/test_config.py
git add src/jurist/config.py tests/test_config.py
git commit -m "feat(config): add M2 settings + RunContext dataclass"
```

---

## Task 3: `make_snippet` helper

**Files:**
- Create: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_statute_retriever_tools.py`:

```python
from jurist.agents.statute_retriever_tools import make_snippet


def test_make_snippet_short_passes_through():
    assert make_snippet("kort") == "kort"


def test_make_snippet_collapses_whitespace():
    assert make_snippet("foo\n\nbar\tbaz") == "foo bar baz"


def test_make_snippet_truncates_at_word_boundary():
    # 300-char string of "word " repeated → truncated before the cutoff word
    body = "word " * 100
    result = make_snippet(body, max_chars=30)
    assert result.endswith("…")
    # No partial word before the ellipsis
    trimmed = result.rstrip("…").rstrip()
    assert not trimmed.endswith("wor")  # would mean we cut mid-word
    assert len(trimmed) <= 30


def test_make_snippet_no_ellipsis_when_exact_fit():
    body = "a" * 50
    assert make_snippet(body, max_chars=50) == body
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jurist.agents.statute_retriever_tools'`.

- [ ] **Step 3: Implement**

Create `src/jurist/agents/statute_retriever_tools.py`:

```python
"""Statute retriever tool implementations + helpers."""
from __future__ import annotations


def make_snippet(body: str, max_chars: int = 200) -> str:
    """Collapse whitespace and truncate to a word boundary with an ellipsis."""
    compact = " ".join(body.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "…"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): make_snippet helper with whitespace + word-boundary handling"
```

---

## Task 4: `ToolExecutor` + `get_article`

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §3 tool table: `get_article(article_id)` returns `{article_id, label, title, body_text, outgoing_refs}`. Unknown id → `is_error`.

- [ ] **Step 1: Write failing tests**

Prepend fixture + append tests to `tests/agents/test_statute_retriever_tools.py`:

```python
import pytest

from jurist.agents.statute_retriever_tools import ToolExecutor, ToolResult
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


@pytest.fixture
def fixture_kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="A",
            bwb_id="BWBX",
            label="Art A",
            title="Title A",
            body_text="Body of A with refs to B.",
            outgoing_refs=["B"],
        ),
        ArticleNode(
            article_id="B",
            bwb_id="BWBX",
            label="Art B",
            title="Title B",
            body_text="Body of B, short.",
            outgoing_refs=[],
        ),
        ArticleNode(
            article_id="C",
            bwb_id="BWBX",
            label="Art C",
            title="Title C",
            body_text="About rent and rent again.",
            outgoing_refs=[],
        ),
    ]
    edges = [ArticleEdge(from_id="A", to_id="B", kind="explicit")]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=edges)
    return NetworkXKG.from_snapshot(snap)


@pytest.mark.asyncio
async def test_get_article_returns_body_and_outgoing_refs(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {"article_id": "A"})
    assert isinstance(r, ToolResult)
    assert not r.is_error
    assert r.extra["article_id"] == "A"
    assert r.extra["body_text"] == "Body of A with refs to B."
    assert r.extra["outgoing_refs"] == ["B"]
    assert r.kg_effect == {"node_visited": "A"}
    assert "Art A" in r.result_summary


@pytest.mark.asyncio
async def test_get_article_unknown_id_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {"article_id": "MISSING"})
    assert r.is_error
    assert "unknown" in r.result_summary.lower()
    assert r.kg_effect is None


@pytest.mark.asyncio
async def test_get_article_missing_arg_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {})
    assert r.is_error
    assert r.kg_effect is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'ToolExecutor'`.

- [ ] **Step 3: Implement**

Append to `src/jurist/agents/statute_retriever_tools.py`:

```python
from dataclasses import dataclass, field
from typing import Any

from jurist.kg.interface import KnowledgeGraph


@dataclass
class ToolResult:
    """Normalized tool execution result.

    - result_summary: human-readable one-liner for TracePanel.
    - extra: structured fields surfaced in TraceEvent.data (hit_ids,
      neighbor_ids, body_text, outgoing_refs, etc.) AND serialized into
      the Anthropic tool_result content.
    - is_error: follows Anthropic tool_result semantics.
    - kg_effect: signals to the caller (the retriever agent) which KG-state
      event to emit next: {"node_visited": id} or
      {"edge_traversed": (from, to)}.
    """

    result_summary: str
    extra: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    kg_effect: dict[str, Any] | None = None


class ToolExecutor:
    def __init__(self, kg: KnowledgeGraph, snippet_chars: int = 200) -> None:
        self._kg = kg
        self._snippet_chars = snippet_chars

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        handlers = {
            "search_articles": self._search_articles,
            "list_neighbors": self._list_neighbors,
            "get_article": self._get_article,
            "follow_cross_ref": self._follow_cross_ref,
            "done": self._validate_done,
        }
        handler = handlers.get(name)
        if handler is None:
            return ToolResult(
                result_summary=f"unknown tool: {name}",
                is_error=True,
            )
        return handler(args)

    def _get_article(self, args: dict[str, Any]) -> ToolResult:
        article_id = args.get("article_id")
        if not article_id:
            return ToolResult(
                result_summary="missing required argument: article_id",
                is_error=True,
            )
        node = self._kg.get_node(article_id)
        if node is None:
            return ToolResult(
                result_summary=f"unknown article_id: {article_id}",
                is_error=True,
            )
        return ToolResult(
            result_summary=f"{node.label} — {node.title}",
            extra={
                "article_id": article_id,
                "label": node.label,
                "title": node.title,
                "body_text": node.body_text,
                "outgoing_refs": list(node.outgoing_refs),
            },
            kg_effect={"node_visited": article_id},
        )

    # Subsequent tasks fill in.
    def _search_articles(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def _list_neighbors(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def _follow_cross_ref(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def _validate_done(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: all get_article + make_snippet tests PASS (NotImplementedError tools untested for now).

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): ToolExecutor + get_article"
```

---

## Task 5: `list_neighbors`

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §3: returns `[{article_id, label, title}]` — one per outgoing_ref, no body. Unknown id → `is_error`. No `kg_effect` (peek operation).

- [ ] **Step 1: Write failing tests**

Append to the test file:

```python
@pytest.mark.asyncio
async def test_list_neighbors_returns_labels_and_titles(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "A"})
    assert not r.is_error
    neighbors = r.extra["neighbors"]
    assert neighbors == [{"article_id": "B", "label": "Art B", "title": "Title B"}]
    # neighbor_ids also surfaced for frontend chips
    assert r.extra["neighbor_ids"] == ["B"]
    assert r.kg_effect is None  # peek, no visit


@pytest.mark.asyncio
async def test_list_neighbors_empty_for_leaf(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "B"})
    assert not r.is_error
    assert r.extra["neighbors"] == []
    assert r.extra["neighbor_ids"] == []


@pytest.mark.asyncio
async def test_list_neighbors_unknown_id_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "MISSING"})
    assert r.is_error
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k list_neighbors`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace the `_list_neighbors` method body:

```python
def _list_neighbors(self, args: dict[str, Any]) -> ToolResult:
    article_id = args.get("article_id")
    if not article_id:
        return ToolResult(
            result_summary="missing required argument: article_id",
            is_error=True,
        )
    node = self._kg.get_node(article_id)
    if node is None:
        return ToolResult(
            result_summary=f"unknown article_id: {article_id}",
            is_error=True,
        )
    neighbors: list[dict[str, str]] = []
    for nid in node.outgoing_refs:
        nb = self._kg.get_node(nid)
        if nb is None:
            # In-corpus-only invariant: outgoing_refs should be filtered by
            # ingester; but be defensive.
            continue
        neighbors.append({
            "article_id": nid,
            "label": nb.label,
            "title": nb.title,
        })
    return ToolResult(
        result_summary=f"{len(neighbors)} neighbor(s)",
        extra={
            "neighbors": neighbors,
            "neighbor_ids": [n["article_id"] for n in neighbors],
        },
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: all list_neighbors tests PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): list_neighbors (peek) with labels + titles"
```

---

## Task 6: `follow_cross_ref`

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §3 + §4: returns `get_article`-shaped body for `to_id`. Emits `node_visited{to_id}` **and** `edge_traversed{from_id, to_id}`. The edge must exist in the KG; unknown edge → `is_error` with the hint to use `get_article(to_id)`.

We need the KG to expose edge existence. Widen the `KnowledgeGraph` protocol now.

- [ ] **Step 1: Widen the KnowledgeGraph protocol**

Edit `src/jurist/kg/interface.py`:

```python
"""KnowledgeGraph Protocol — widened in M2 as tool impls need it."""
from __future__ import annotations

from typing import Protocol

from jurist.schemas import ArticleEdge, ArticleNode


class KnowledgeGraph(Protocol):
    def all_nodes(self) -> list[ArticleNode]: ...
    def all_edges(self) -> list[ArticleEdge]: ...
    def get_node(self, article_id: str) -> ArticleNode | None: ...
    def has_edge(self, from_id: str, to_id: str) -> bool: ...
```

- [ ] **Step 2: Implement `has_edge` on NetworkXKG**

Append to the `NetworkXKG` class in `src/jurist/kg/networkx_kg.py`:

```python
    def has_edge(self, from_id: str, to_id: str) -> bool:
        return self._graph.has_edge(from_id, to_id)
```

- [ ] **Step 3: Write failing tests**

Append to `tests/agents/test_statute_retriever_tools.py`:

```python
@pytest.mark.asyncio
async def test_follow_cross_ref_returns_body_and_edge_effect(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "B"}
    )
    assert not r.is_error
    assert r.extra["body_text"] == "Body of B, short."
    assert r.kg_effect == {"edge_traversed": ("A", "B"), "node_visited": "B"}


@pytest.mark.asyncio
async def test_follow_cross_ref_missing_edge_errors_with_hint(fixture_kg):
    # Both nodes exist but no edge A→C in the fixture.
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "C"}
    )
    assert r.is_error
    assert "get_article" in r.result_summary
    assert r.kg_effect is None


@pytest.mark.asyncio
async def test_follow_cross_ref_unknown_from_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "MISSING", "to_id": "B"}
    )
    assert r.is_error


@pytest.mark.asyncio
async def test_follow_cross_ref_unknown_to_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "MISSING"}
    )
    assert r.is_error
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k follow_cross_ref`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 5: Implement**

Replace `_follow_cross_ref`:

```python
def _follow_cross_ref(self, args: dict[str, Any]) -> ToolResult:
    from_id = args.get("from_id")
    to_id = args.get("to_id")
    if not from_id or not to_id:
        return ToolResult(
            result_summary="missing required arguments: from_id, to_id",
            is_error=True,
        )
    from_node = self._kg.get_node(from_id)
    if from_node is None:
        return ToolResult(
            result_summary=f"unknown from_id: {from_id}",
            is_error=True,
        )
    to_node = self._kg.get_node(to_id)
    if to_node is None:
        return ToolResult(
            result_summary=f"unknown to_id: {to_id}",
            is_error=True,
        )
    if not self._kg.has_edge(from_id, to_id):
        return ToolResult(
            result_summary=(
                f"no edge from {from_id} to {to_id} in the corpus — "
                f"use get_article({to_id}) if you only need the content."
            ),
            is_error=True,
        )
    return ToolResult(
        result_summary=f"{to_node.label} — {to_node.title}",
        extra={
            "article_id": to_id,
            "label": to_node.label,
            "title": to_node.title,
            "body_text": to_node.body_text,
            "outgoing_refs": list(to_node.outgoing_refs),
        },
        kg_effect={"edge_traversed": (from_id, to_id), "node_visited": to_id},
    )
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/ -v -k "not e2e"`
Expected: all previously-passing tests still pass; new follow_cross_ref tests pass.

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/jurist/ tests/
git add src/jurist/agents/statute_retriever_tools.py \
        src/jurist/kg/interface.py src/jurist/kg/networkx_kg.py \
        tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): follow_cross_ref with edge validation; widen KG protocol"
```

---

## Task 7: `search_articles` (Jaccard lexical)

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §3 + decisions log #4: lexical Jaccard token-overlap against `title + body_text[:snippet_chars]`, case-folded, simple Dutch stop-words removed. Returns top-K `{article_id, label, title, snippet}` in descending score order.

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_search_articles_ranks_rent_over_unrelated(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    # "rent" appears twice in C ("rent and rent again"), zero times in A/B.
    r = await exec_.execute("search_articles", {"query": "rent", "top_k": 3})
    assert not r.is_error
    ids = [h["article_id"] for h in r.extra["hits"]]
    assert ids[0] == "C"
    # hit_ids surfaced for frontend chips
    assert r.extra["hit_ids"] == ids


@pytest.mark.asyncio
async def test_search_articles_respects_top_k(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "search_articles", {"query": "body", "top_k": 1}
    )
    assert len(r.extra["hits"]) == 1


@pytest.mark.asyncio
async def test_search_articles_empty_query_returns_empty(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("search_articles", {"query": "", "top_k": 5})
    assert not r.is_error
    assert r.extra["hits"] == []
    assert r.extra["hit_ids"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k search_articles`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Add a module-level helper + replace `_search_articles`:

```python
# Minimal Dutch + English stop-words; low-cost coarse filter.
_STOP_WORDS = frozenset({
    "de", "het", "een", "en", "of", "in", "van", "op", "met", "bij",
    "te", "ten", "tot", "dat", "die", "dit", "deze", "is", "zijn",
    "wordt", "worden", "niet", "geen", "als", "ook", "maar", "nog",
    "the", "and", "or", "of", "to", "in", "a", "an", "is", "are",
})


def _tokenize(text: str) -> set[str]:
    return {
        t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
        if t and t not in _STOP_WORDS and len(t) > 1
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
```

And:

```python
def _search_articles(self, args: dict[str, Any]) -> ToolResult:
    query = (args.get("query") or "").strip()
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 10))
    if not query:
        return ToolResult(
            result_summary="0 hits (empty query)",
            extra={"hits": [], "hit_ids": []},
        )
    q_tokens = _tokenize(query)
    scored: list[tuple[float, Any]] = []
    for node in self._kg.all_nodes():
        snippet = make_snippet(node.body_text, self._snippet_chars)
        field_tokens = _tokenize(f"{node.title} {snippet}")
        score = _jaccard(q_tokens, field_tokens)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for score, node in scored[:top_k]:
        hits.append({
            "article_id": node.article_id,
            "label": node.label,
            "title": node.title,
            "snippet": make_snippet(node.body_text, self._snippet_chars),
            "score": round(score, 4),
        })
    return ToolResult(
        result_summary=f"{len(hits)} hit(s)",
        extra={"hits": hits, "hit_ids": [h["article_id"] for h in hits]},
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: all search_articles tests PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): search_articles (Jaccard lexical, top-K, stop-word filtered)"
```

---

## Task 8: `done` validator

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §3: `done.selected` = `[{article_id, reason}]`. All `article_id`s must exist in KG. The validator itself doesn't terminate the loop — that's the caller's responsibility; it just returns success/error so the LLM client can decide whether to retry once or coerce.

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_done_validates_known_ids(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [
            {"article_id": "A", "reason": "core rule"},
            {"article_id": "B", "reason": "procedure"},
        ]},
    )
    assert not r.is_error
    assert r.extra["selected_count"] == 2


@pytest.mark.asyncio
async def test_done_rejects_unknown_id(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [
            {"article_id": "A", "reason": "ok"},
            {"article_id": "NOPE", "reason": "bad"},
        ]},
    )
    assert r.is_error
    assert "NOPE" in r.result_summary


@pytest.mark.asyncio
async def test_done_empty_selected_is_allowed(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("done", {"selected": []})
    assert not r.is_error
    assert r.extra["selected_count"] == 0


@pytest.mark.asyncio
async def test_done_rejects_missing_reason(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [{"article_id": "A"}]},  # no reason
    )
    assert r.is_error
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k done`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace `_validate_done`:

```python
def _validate_done(self, args: dict[str, Any]) -> ToolResult:
    selected = args.get("selected")
    if selected is None or not isinstance(selected, list):
        return ToolResult(
            result_summary="`selected` must be a list of {article_id, reason}",
            is_error=True,
        )
    unknown: list[str] = []
    missing_reason: list[str] = []
    for entry in selected:
        if not isinstance(entry, dict):
            return ToolResult(
                result_summary="each entry must be {article_id, reason}",
                is_error=True,
            )
        aid = entry.get("article_id")
        reason = entry.get("reason")
        if not aid:
            return ToolResult(
                result_summary="entry missing article_id",
                is_error=True,
            )
        if not reason:
            missing_reason.append(aid)
            continue
        if self._kg.get_node(aid) is None:
            unknown.append(aid)
    if unknown:
        return ToolResult(
            result_summary=(
                f"unknown article_id(s) in selected: {unknown}. "
                f"Pick from the catalog you were given."
            ),
            is_error=True,
        )
    if missing_reason:
        return ToolResult(
            result_summary=f"missing reason for: {missing_reason}",
            is_error=True,
        )
    return ToolResult(
        result_summary=f"{len(selected)} selected",
        extra={"selected_count": len(selected), "selected": selected},
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: all tool tests PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): done validator — reject unknown ids + missing reasons"
```

---

## Task 9: Catalog builder

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Per spec §6: catalog format is one article per line, `[<id>] "<label>" — <title>: <snippet>`. Sort by `article_id` for stability.

- [ ] **Step 1: Write failing tests**

Append:

```python
from jurist.agents.statute_retriever_tools import build_catalog


def test_build_catalog_formats_rows(fixture_kg):
    text = build_catalog(fixture_kg, snippet_chars=200)
    lines = text.strip().split("\n")
    assert len(lines) == 3  # 3 fixture nodes
    # Sorted by article_id (A, B, C)
    assert lines[0].startswith("[A]")
    assert lines[1].startswith("[B]")
    assert lines[2].startswith("[C]")
    assert '"Art A"' in lines[0]
    assert "Title A" in lines[0]
    assert "Body of A" in lines[0]


def test_build_catalog_truncates_long_bodies(fixture_kg):
    text = build_catalog(fixture_kg, snippet_chars=10)
    lines = text.strip().split("\n")
    # With snippet_chars=10, "Body of A with refs to B." → truncated + "…"
    row_a = [l for l in lines if l.startswith("[A]")][0]
    assert "…" in row_a
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k build_catalog`
Expected: FAIL — `ImportError: cannot import name 'build_catalog'`.

- [ ] **Step 3: Implement**

Append to `src/jurist/agents/statute_retriever_tools.py`:

```python
def build_catalog(kg: KnowledgeGraph, snippet_chars: int = 200) -> str:
    """Render the full KG as a one-article-per-line catalog for the system prompt."""
    rows: list[str] = []
    nodes = sorted(kg.all_nodes(), key=lambda n: n.article_id)
    for node in nodes:
        snippet = make_snippet(node.body_text, snippet_chars)
        rows.append(
            f'[{node.article_id}] "{node.label}" — {node.title}: {snippet}'
        )
    return "\n".join(rows)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: catalog tests PASS.

- [ ] **Step 5: Smoke-test against real KG**

Run: `uv run python -c "from jurist.kg.networkx_kg import NetworkXKG; from jurist.config import settings; from jurist.agents.statute_retriever_tools import build_catalog; kg = NetworkXKG.load_from_json(settings.kg_path); text = build_catalog(kg); print(f'bytes={len(text)} lines={len(text.splitlines())}'); print(text.splitlines()[0][:200])"`
Expected: `bytes=~66000 lines=218` and a sample row printed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): build_catalog — one-article-per-line prompt preamble"
```

---

## Task 10: System prompt template + renderer

**Files:**
- Create: `src/jurist/llm/__init__.py`
- Create: `src/jurist/llm/prompts/__init__.py`
- Create: `src/jurist/llm/prompts/statute_retriever.system.md`
- Create: `src/jurist/llm/prompts.py`
- Test: `tests/agents/test_statute_retriever_prompt.py`

- [ ] **Step 1: Create empty package init files**

```bash
mkdir -p src/jurist/llm/prompts
touch src/jurist/llm/__init__.py src/jurist/llm/prompts/__init__.py
```

- [ ] **Step 2: Write the prompt template**

Create `src/jurist/llm/prompts/statute_retriever.system.md` with the exact content from spec §6:

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

- [ ] **Step 3: Write failing test for the renderer**

Create `tests/agents/test_statute_retriever_prompt.py`:

```python
import pytest

from jurist.kg.networkx_kg import NetworkXKG
from jurist.llm.prompts import render_statute_retriever_system
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


@pytest.fixture
def tiny_kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="X1",
            bwb_id="BWBX",
            label="Art X1",
            title="Titel X1",
            body_text="Over huurverhoging.",
            outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    return NetworkXKG.from_snapshot(snap)


def test_render_contains_policies_and_catalog(tiny_kg):
    rendered = render_statute_retriever_system(tiny_kg, snippet_chars=200)
    assert "Dutch tenancy-law" in rendered
    assert "Target 3–6 cited articles" in rendered
    assert "{{ARTICLE_CATALOG}}" not in rendered  # substituted
    # Catalog line present
    assert '[X1] "Art X1" — Titel X1: Over huurverhoging.' in rendered


def test_render_is_deterministic(tiny_kg):
    a = render_statute_retriever_system(tiny_kg)
    b = render_statute_retriever_system(tiny_kg)
    assert a == b
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_prompt.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_statute_retriever_system'`.

- [ ] **Step 5: Implement the renderer**

Create `src/jurist/llm/prompts.py`:

```python
"""Prompt template loading + rendering."""
from __future__ import annotations

from pathlib import Path

from jurist.agents.statute_retriever_tools import build_catalog
from jurist.kg.interface import KnowledgeGraph

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def render_statute_retriever_system(
    kg: KnowledgeGraph,
    *,
    snippet_chars: int = 200,
) -> str:
    """Load statute_retriever.system.md and substitute the article catalog."""
    template = (_PROMPTS_DIR / "statute_retriever.system.md").read_text(encoding="utf-8")
    catalog = build_catalog(kg, snippet_chars=snippet_chars)
    return template.replace("{{ARTICLE_CATALOG}}", catalog)
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_prompt.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Register prompts as package data**

Edit `pyproject.toml` → `[tool.hatch.build.targets.wheel]` section:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/jurist"]

[tool.hatch.build.targets.wheel.force-include]
"src/jurist/llm/prompts/statute_retriever.system.md" = "jurist/llm/prompts/statute_retriever.system.md"
```

(Ensures the `.md` ships inside the wheel for any future packaging; during local dev with `uv sync --editable` the file is found via the filesystem.)

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/jurist/llm/ tests/agents/test_statute_retriever_prompt.py
git add src/jurist/llm/ tests/agents/test_statute_retriever_prompt.py pyproject.toml
git commit -m "feat(llm): system prompt template + renderer for statute retriever"
```

---

## Task 11: Turn types + Mock Anthropic client fixture

**Files:**
- Create: `src/jurist/llm/turn.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/mock_llm.py`

Centralize the turn dataclasses in `src/jurist/llm/` so later code (`client.py`, the mock, and the real streaming path) all share one source of truth without `src → tests` imports.

- [ ] **Step 1: Create turn types in src**

Create `src/jurist/llm/turn.py`:

```python
"""Typed shape of one assistant turn — shared by the mock and the real path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelToolUse:
    name: str
    args: dict[str, Any]


@dataclass
class ModelTurn:
    """One assistant reply. text_deltas stream first, then tool_uses."""

    text_deltas: list[str] = field(default_factory=list)
    tool_uses: list[ModelToolUse] = field(default_factory=list)
```

- [ ] **Step 2: Create fixtures package**

```bash
mkdir -p tests/fixtures
touch tests/fixtures/__init__.py
```

- [ ] **Step 3: Write the mock**

Create `tests/fixtures/mock_llm.py`:

```python
"""Scripted mock for Anthropic tool-use turns.

Re-exports ModelTurn/ModelToolUse as ScriptedTurn/ScriptedToolUse for
readability in tests. A script is a list of ScriptedTurn. Each turn
models one assistant reply. When the script is exhausted, the mock
returns an empty turn so the loop under test coerces on its own."""
from __future__ import annotations

from typing import Any

from jurist.llm.turn import ModelToolUse as ScriptedToolUse
from jurist.llm.turn import ModelTurn as ScriptedTurn


class MockAnthropicClient:
    """Replays scripted turns. The loop driver calls `next_turn(history)`
    and receives a `ScriptedTurn`. `history` is the full message list
    the real Anthropic client would have received."""

    def __init__(self, script: list[ScriptedTurn]) -> None:
        self._script = list(script)
        self.history_snapshots: list[list[dict[str, Any]]] = []

    def next_turn(self, history: list[dict[str, Any]]) -> ScriptedTurn:
        self.history_snapshots.append([dict(m) for m in history])
        if not self._script:
            return ScriptedTurn()
        return self._script.pop(0)


__all__ = ["MockAnthropicClient", "ScriptedToolUse", "ScriptedTurn"]
```

- [ ] **Step 4: Smoke-import**

Run: `uv run python -c "from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedTurn, ScriptedToolUse; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/llm/turn.py tests/fixtures/
git add src/jurist/llm/turn.py tests/fixtures/
git commit -m "test: ModelTurn types + MockAnthropicClient fixture for tool-use turns"
```

---

## Task 12: LoopEvent types + `run_tool_loop` happy path

**Files:**
- Create: `src/jurist/llm/client.py`
- Create: `tests/llm/__init__.py`
- Create: `tests/llm/test_client.py`

Per spec §7: one public function `run_tool_loop` that yields `LoopEvent`s. Happy path = single turn that emits one `tool_use` (get_article) followed by a second turn with `done`.

The client here consumes a callable that returns the next turn (for testability) plus a tool executor. The real Anthropic integration lives in the same module but is wired in Task 13.

- [ ] **Step 1: Create test package**

```bash
mkdir -p tests/llm
touch tests/llm/__init__.py
```

- [ ] **Step 2: Write failing test**

Create `tests/llm/test_client.py`:

```python
from typing import Any

import pytest

from jurist.agents.statute_retriever_tools import ToolExecutor
from jurist.kg.networkx_kg import NetworkXKG
from jurist.llm.client import (
    Coerced,
    Done,
    LoopEvent,
    TextDelta,
    ToolResultEvent,
    ToolUseStart,
    run_tool_loop,
)
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


def _kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="A",
            bwb_id="BWBX",
            label="Art A",
            title="T",
            body_text="body.",
            outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    return NetworkXKG.from_snapshot(snap)


@pytest.mark.asyncio
async def test_run_tool_loop_happy_path_terminates_on_done():
    kg = _kg()
    script = [
        ScriptedTurn(
            text_deltas=["Ik lees artikel A."],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        ),
        ScriptedTurn(
            text_deltas=["Klaar."],
            tool_uses=[ScriptedToolUse(
                name="done",
                args={"selected": [{"article_id": "A", "reason": "relevant"}]},
            )],
        ),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock,
        executor=executor,
        system="<sys>",
        tools=[],
        user_message="test",
        max_iters=15,
        wall_clock_cap_s=90.0,
    ):
        events.append(ev)

    # Event order: delta, tool_use_start, tool_result, delta, done
    types = [type(e).__name__ for e in events]
    assert "TextDelta" in types
    assert "ToolUseStart" in types
    assert "ToolResultEvent" in types
    assert types[-1] == "Done"
    final_done = events[-1]
    assert isinstance(final_done, Done)
    assert final_done.selected == [{"article_id": "A", "reason": "relevant"}]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/llm/test_client.py -v`
Expected: FAIL — import errors.

- [ ] **Step 4: Implement**

Create `src/jurist/llm/client.py`:

```python
"""Thin tool-use loop driver. Yields LoopEvents; callers translate to UI
events or TraceEvents as they see fit.

For M2, two implementations of the 'next turn' source exist:
  - scripted (MockAnthropicClient) for tests
  - real Anthropic streaming (added in Task 13)

This module hides that distinction behind a duck-typed `mock` parameter in
run_tool_loop. Task 13 wires a real-client path that lives in the same file.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from jurist.agents.statute_retriever_tools import ToolExecutor, ToolResult
from jurist.llm.turn import ModelToolUse, ModelTurn


# ---------------- LoopEvent ADT ----------------

@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUseStart:
    name: str
    args: dict[str, Any]


@dataclass
class ToolResultEvent:
    name: str
    args: dict[str, Any]
    result: ToolResult


@dataclass
class Done:
    selected: list[dict[str, Any]]


@dataclass
class Coerced:
    reason: str  # "max_iter" | "wall_clock" | "dup_loop"
    selected: list[dict[str, Any]]


LoopEvent = TextDelta | ToolUseStart | ToolResultEvent | Done | Coerced


# ---------------- Driver ----------------

async def run_tool_loop(
    *,
    mock: Any | None = None,   # MockAnthropicClient for tests
    executor: ToolExecutor,
    system: str,
    tools: list[dict[str, Any]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    """Drive a tool-use loop. `mock` is used when supplied; otherwise Task 13
    wires a real Anthropic call path here."""
    started = time.monotonic()
    history: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]
    for iter_idx in range(max_iters):
        if (time.monotonic() - started) > wall_clock_cap_s:
            yield Coerced(reason="wall_clock", selected=[])
            return
        turn = mock.next_turn(history)
        for delta in turn.text_deltas:
            yield TextDelta(text=delta)
        if not turn.tool_uses:
            # No tool calls, no text — model stalled. Coerce.
            if not turn.text_deltas:
                yield Coerced(reason="stall", selected=[])
                return
            # Text without tools and no done: keep looping; the model might
            # reply again next turn. Append an assistant-text record.
            history.append({
                "role": "assistant",
                "content": "".join(turn.text_deltas),
            })
            continue
        # Record the assistant turn (text + tool_uses) in history.
        history.append({
            "role": "assistant",
            "content": {
                "text": "".join(turn.text_deltas),
                "tool_uses": [
                    {"name": tu.name, "args": tu.args} for tu in turn.tool_uses
                ],
            },
        })
        for tu in turn.tool_uses:
            yield ToolUseStart(name=tu.name, args=tu.args)
            if tu.name == "done":
                result = await executor.execute("done", tu.args)
                yield ToolResultEvent(name="done", args=tu.args, result=result)
                if not result.is_error:
                    yield Done(selected=list(tu.args.get("selected", [])))
                    return
                # Error on done — caller (Task 14) will implement the
                # one-retry-then-coerce policy; for now, coerce immediately
                # with empty selection so the happy-path test stays simple.
                yield Coerced(reason="done_error", selected=[])
                return
            result = await executor.execute(tu.name, tu.args)
            yield ToolResultEvent(name=tu.name, args=tu.args, result=result)
            history.append({
                "role": "user",
                "content": {"tool_result": result.extra, "is_error": result.is_error},
            })
    # Loop exhausted without done.
    yield Coerced(reason="max_iter", selected=[])
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/llm/test_client.py -v`
Expected: 1 PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/jurist/llm/client.py tests/llm/test_client.py
git add src/jurist/llm/client.py tests/llm/
git commit -m "feat(llm): run_tool_loop happy path + LoopEvent ADT"
```

---

## Task 13: Real Anthropic call path + streaming

**Files:**
- Modify: `src/jurist/llm/client.py`
- Test: `tests/llm/test_client.py` (integration-lite: round-trip via a fake Anthropic layer; gated on no-op when API key absent)

This task adds the real streaming path — when `mock` is None, `run_tool_loop` calls `AsyncAnthropic.messages.stream()`. The mock path from Task 12 stays intact.

- [ ] **Step 1: Widen `run_tool_loop` signature**

Replace the `run_tool_loop` signature (keep body; we'll extend below):

```python
async def run_tool_loop(
    *,
    mock: Any | None = None,
    client: Any | None = None,  # AsyncAnthropic when real
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    executor: ToolExecutor,
    system: str,
    tools: list[dict[str, Any]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    ...
```

- [ ] **Step 2: Abstract the turn source**

Refactor the loop body so the "how do I get the next turn" step uses a small helper. Insert before the for loop:

```python
async def _next_turn(history: list[dict[str, Any]]) -> ModelTurn:
    if mock is not None:
        return mock.next_turn(history)  # ScriptedTurn is a ModelTurn alias
    # Real Anthropic path: stream a single message, assemble into a ModelTurn.
    # Uses the already-assembled `messages` list (derived from history).
    return await _anthropic_next_turn(
        client=client,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        messages=_history_to_anthropic_messages(history),
    )
```

and replace `turn = mock.next_turn(history)` with `turn = await _next_turn(history)`.

- [ ] **Step 3: Add the Anthropic translator functions**

Append to `src/jurist/llm/client.py` (the `ModelTurn`/`ModelToolUse` are already imported at the top from Task 12):

```python
def _history_to_anthropic_messages(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate our simple history into the Anthropic messages format.

    Our history uses a compact shape to keep the happy-path test readable;
    Anthropic expects a specific content-blocks structure."""
    out: list[dict[str, Any]] = []
    for msg in history:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant" and "tool_uses" in content:
            blocks: list[dict[str, Any]] = []
            if content.get("text"):
                blocks.append({"type": "text", "text": content["text"]})
            for idx, tu in enumerate(content["tool_uses"]):
                blocks.append({
                    "type": "tool_use",
                    "id": f"tu_{len(out)}_{idx}",
                    "name": tu["name"],
                    "input": tu["args"],
                })
            out.append({"role": "assistant", "content": blocks})
            continue
        if role == "user" and "tool_result" in content:
            # Attach tool_result block referencing the preceding tool_use id.
            last_assistant = next(
                (m for m in reversed(out) if m["role"] == "assistant"), None
            )
            if last_assistant is None:
                continue
            tu_block = next(
                (b for b in last_assistant["content"] if b.get("type") == "tool_use"),
                None,
            )
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tu_block["id"] if tu_block else "tu_missing",
                    "content": str(content["tool_result"]),
                    "is_error": bool(content.get("is_error")),
                }],
            })
            continue
        out.append({"role": role, "content": str(content)})
    return out


async def _anthropic_next_turn(
    *,
    client: Any,
    model: str,
    temperature: float,
    max_tokens: int,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> ModelTurn:
    """Stream one Anthropic turn and assemble a ModelTurn."""
    text_deltas: list[str] = []
    tool_uses: list[ModelToolUse] = []
    async with client.messages.stream(
        model=model,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=tools,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    ) as stream:
        async for event in stream:
            if event.type == "content_block_delta":
                delta = event.delta
                if getattr(delta, "type", None) == "text_delta":
                    text_deltas.append(delta.text)
                # input_json_delta for tool_use is assembled by the SDK —
                # we read the finalized block in message_stop below.
            elif event.type == "message_stop":
                pass
        final = await stream.get_final_message()
    for block in final.content:
        if getattr(block, "type", None) == "tool_use":
            tool_uses.append(ModelToolUse(name=block.name, args=dict(block.input)))
    return ModelTurn(text_deltas=text_deltas, tool_uses=tool_uses)
```

- [ ] **Step 4: Add a test that exercises the translator**

Append to `tests/llm/test_client.py`:

```python
from jurist.llm.client import _history_to_anthropic_messages


def test_history_translator_preserves_user_strings():
    out = _history_to_anthropic_messages([{"role": "user", "content": "hi"}])
    assert out == [{"role": "user", "content": "hi"}]


def test_history_translator_renders_tool_use_and_result():
    hist = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": {
            "text": "thinking",
            "tool_uses": [{"name": "get_article", "args": {"article_id": "A"}}],
        }},
        {"role": "user", "content": {
            "tool_result": {"body_text": "..."},
            "is_error": False,
        }},
    ]
    out = _history_to_anthropic_messages(hist)
    assert out[0] == {"role": "user", "content": "q"}
    asst = out[1]
    assert asst["role"] == "assistant"
    assert any(b.get("type") == "text" for b in asst["content"])
    assert any(b.get("type") == "tool_use" for b in asst["content"])
    tr = out[2]
    assert tr["role"] == "user"
    assert tr["content"][0]["type"] == "tool_result"
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v -k "not e2e"`
Expected: all tests pass; the happy-path loop test still works because it passes `mock=...` and never touches `_anthropic_next_turn`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/jurist/llm/client.py tests/llm/test_client.py
git add src/jurist/llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): real Anthropic streaming path + history translator"
```

---

## Task 14: `done` one-retry then coerce; max_iter coercion

**Files:**
- Modify: `src/jurist/llm/client.py`
- Test: `tests/llm/test_client.py`

Per spec §5: when `done` returns `is_error`, allow one regeneration (inject the tool_result back; let the model fix up). If it errors again, coerce with visit-recency-ordered selection capped at 8.

Also finalize max_iter coercion: on exhaustion, build a coerced selection from nodes touched by `get_article`/`follow_cross_ref` (recency-ordered, cap 8), not just empty.

- [ ] **Step 1: Write failing tests**

Append to `tests/llm/test_client.py`:

```python
@pytest.mark.asyncio
async def test_done_one_retry_then_accept():
    kg = _kg()
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "NOPE", "reason": "x"}]},
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Done)
    assert final.selected == [{"article_id": "A", "reason": "ok"}]


@pytest.mark.asyncio
async def test_done_two_errors_coerces():
    kg = _kg()
    bad = {"selected": [{"article_id": "NOPE", "reason": "x"}]}
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(name="done", args=bad)]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(name="done", args=bad)]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "done_error"


@pytest.mark.asyncio
async def test_max_iter_coerces_with_visited_recency_capped():
    # Build a KG with >8 nodes and a script that visits them all via
    # get_article, then never calls done.
    nodes = [
        ArticleNode(
            article_id=f"N{i}", bwb_id="BWBX", label=f"N{i}",
            title="t", body_text="b", outgoing_refs=[],
        )
        for i in range(10)
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    big_kg = NetworkXKG.from_snapshot(snap)
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="get_article", args={"article_id": f"N{i}"}
        )])
        for i in range(10)
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(big_kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=10, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "max_iter"
    # Most recent 8 visits, in recency order: N9, N8, ..., N2
    assert len(final.selected) == 8
    assert final.selected[0]["article_id"] == "N9"
    assert final.selected[-1]["article_id"] == "N2"
    for entry in final.selected:
        assert "coerced: max_iter" in entry["reason"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/llm/test_client.py -v`
Expected: 3 new tests FAIL.

- [ ] **Step 3: Implement**

In `run_tool_loop`, track visited nodes and done-retry state. Replace the body with:

```python
async def run_tool_loop(
    *,
    mock: Any | None = None,
    client: Any | None = None,
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    executor: ToolExecutor,
    system: str,
    tools: list[dict[str, Any]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    started = time.monotonic()
    history: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    # Visit-recency log of article_ids touched by get_article / follow_cross_ref.
    visited: list[str] = []
    done_errors = 0  # counts consecutive done failures

    async def _next_turn(hist: list[dict[str, Any]]) -> ModelTurn:
        if mock is not None:
            return mock.next_turn(hist)
        return await _anthropic_next_turn(
            client=client, model=model, temperature=temperature,
            max_tokens=max_tokens, system=system, tools=tools,
            messages=_history_to_anthropic_messages(hist),
        )

    def _coerce_selection(reason: str) -> list[dict[str, Any]]:
        # Deduplicate preserving last-occurrence (recency-ordered).
        seen: set[str] = set()
        recency: list[str] = []
        for aid in reversed(visited):
            if aid in seen:
                continue
            seen.add(aid)
            recency.append(aid)
        recency = recency[:8]
        return [{"article_id": aid, "reason": f"auto-selected (coerced: {reason})"}
                for aid in recency]

    for _ in range(max_iters):
        if (time.monotonic() - started) > wall_clock_cap_s:
            yield Coerced(reason="wall_clock", selected=_coerce_selection("wall_clock"))
            return
        turn = await _next_turn(history)
        for delta in turn.text_deltas:
            yield TextDelta(text=delta)
        if not turn.tool_uses:
            if not turn.text_deltas:
                yield Coerced(reason="stall", selected=_coerce_selection("stall"))
                return
            history.append({"role": "assistant", "content": "".join(turn.text_deltas)})
            continue
        history.append({
            "role": "assistant",
            "content": {
                "text": "".join(turn.text_deltas),
                "tool_uses": [
                    {"name": tu.name, "args": tu.args} for tu in turn.tool_uses
                ],
            },
        })
        for tu in turn.tool_uses:
            yield ToolUseStart(name=tu.name, args=tu.args)
            if tu.name == "done":
                result = await executor.execute("done", tu.args)
                yield ToolResultEvent(name="done", args=tu.args, result=result)
                if not result.is_error:
                    yield Done(selected=list(tu.args.get("selected", [])))
                    return
                done_errors += 1
                if done_errors >= 2:
                    yield Coerced(reason="done_error",
                                  selected=_coerce_selection("done_error"))
                    return
                # Inject the error tool_result for the model to correct next turn.
                history.append({
                    "role": "user",
                    "content": {"tool_result": result.extra or {"error": result.result_summary},
                                "is_error": True},
                })
                continue
            result = await executor.execute(tu.name, tu.args)
            yield ToolResultEvent(name=tu.name, args=tu.args, result=result)
            if result.kg_effect and "node_visited" in result.kg_effect:
                visited.append(result.kg_effect["node_visited"])
            history.append({
                "role": "user",
                "content": {
                    "tool_result": result.extra or {"error": result.result_summary},
                    "is_error": result.is_error,
                },
            })
    yield Coerced(reason="max_iter", selected=_coerce_selection("max_iter"))
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v -k "not e2e"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/llm/client.py
git add src/jurist/llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): done one-retry-then-coerce + max_iter coerced selection"
```

---

## Task 15: Wall-clock coercion test

**Files:**
- Test: `tests/llm/test_client.py`

The wall-clock branch already exists in Task 14's impl; this task adds an explicit test.

- [ ] **Step 1: Write test**

Append:

```python
import asyncio


class _SlowMock:
    """Sleeps on every turn so the wall-clock cap fires quickly."""

    def __init__(self) -> None:
        self.calls = 0

    def next_turn(self, history):
        self.calls += 1
        # Block the event loop briefly by yielding a synchronous turn
        # that does nothing; the loop advances monotonic time via sleeps
        # only when we await, so we inject an await via a sentinel. The
        # wall-clock test instead uses a very short cap.
        return ScriptedTurn(
            text_deltas=["…"],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        )


@pytest.mark.asyncio
async def test_wall_clock_coerces_on_tight_cap(monkeypatch):
    kg = _kg()
    mock = _SlowMock()
    executor = ToolExecutor(kg)

    # Force monotonic time to jump forward each call.
    import jurist.llm.client as client_mod

    times = iter([0.0, 0.0, 0.0, 1000.0])
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: next(times))

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=10.0,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "wall_clock"
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/llm/test_client.py -v -k wall_clock`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_client.py
git commit -m "test(llm): wall-clock coercion path"
```

---

## Task 16: Duplicate-call detector

**Files:**
- Modify: `src/jurist/llm/client.py`
- Test: `tests/llm/test_client.py`

Per spec §5: two consecutive identical calls (same tool name + identical args dict) → inject advisory `tool_result{is_error: true}` instead of executing. Three consecutive dupes → coerce done.

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_dup_two_consecutive_triggers_advisory():
    kg = _kg()
    call = ScriptedToolUse(name="get_article", args={"article_id": "A"})
    script = [
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),  # duplicate — should advisory
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        events.append(ev)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    # First get_article succeeds; second is an advisory error; done succeeds.
    assert tool_results[0].result.is_error is False
    assert tool_results[1].result.is_error is True
    assert "already" in tool_results[1].result.result_summary.lower()
    assert isinstance(events[-1], Done)


@pytest.mark.asyncio
async def test_dup_three_consecutive_coerces():
    kg = _kg()
    call = ScriptedToolUse(name="get_article", args={"article_id": "A"})
    script = [
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "dup_loop"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/llm/test_client.py -v -k dup`
Expected: 2 FAIL.

- [ ] **Step 3: Implement**

In `run_tool_loop`, track last-call signature + consecutive-dup count. Add before the `for _ in range(max_iters)` line:

```python
    last_call: tuple[str, str] | None = None
    dup_count = 0
```

And within the inner `for tu in turn.tool_uses:` loop, BEFORE the `if tu.name == "done":` branch, insert:

```python
            call_sig = (tu.name, repr(sorted(tu.args.items()) if isinstance(tu.args, dict) else tu.args))
            if last_call == call_sig:
                dup_count += 1
            else:
                dup_count = 0
            last_call = call_sig

            if dup_count >= 2:
                yield Coerced(reason="dup_loop",
                              selected=_coerce_selection("dup_loop"))
                return
            if dup_count == 1 and tu.name != "done":
                advisory = ToolResult(
                    result_summary=(
                        "You already called this tool with identical "
                        "arguments. Try get_article, follow_cross_ref, "
                        "list_neighbors, or done with a different plan."
                    ),
                    is_error=True,
                )
                yield ToolResultEvent(name=tu.name, args=tu.args, result=advisory)
                history.append({
                    "role": "user",
                    "content": {"tool_result": {"advice": advisory.result_summary},
                                "is_error": True},
                })
                continue
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/llm/test_client.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/llm/client.py
git add src/jurist/llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): duplicate-call detector — advisory at 2, coerce at 3"
```

---

## Task 17: Tool executor exception wrapping

**Files:**
- Modify: `src/jurist/llm/client.py`
- Test: `tests/llm/test_client.py`

Per spec §5: `try/except` around executor invocations; unexpected exceptions become `is_error=true` tool results. Loop continues.

- [ ] **Step 1: Write failing test**

Append:

```python
class _BoomExecutor(ToolExecutor):
    async def execute(self, name, args):
        if name == "get_article":
            raise RuntimeError("boom")
        return await super().execute(name, args)


@pytest.mark.asyncio
async def test_executor_exception_becomes_is_error():
    kg = _kg()
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="get_article", args={"article_id": "A"}
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = _BoomExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        events.append(ev)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    # get_article raised → is_error
    assert tool_results[0].result.is_error is True
    assert "boom" in tool_results[0].result.result_summary.lower()
    # Loop continued to done
    assert isinstance(events[-1], Done)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/llm/test_client.py -v -k executor_exception`
Expected: FAIL — `RuntimeError: boom` propagates.

- [ ] **Step 3: Implement — wrap executor calls**

Replace the two `result = await executor.execute(...)` lines (both the done branch and the general branch) with:

```python
            try:
                result = await executor.execute(tu.name, tu.args)
            except Exception as exc:  # noqa: BLE001 — wrap all
                result = ToolResult(
                    result_summary=f"internal error: {type(exc).__name__}: {exc}",
                    is_error=True,
                )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -v -k "not e2e"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/llm/client.py
git add src/jurist/llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): wrap executor exceptions as is_error tool_results"
```

---

## Task 18: Tool schemas for Anthropic `tools` array

**Files:**
- Modify: `src/jurist/agents/statute_retriever_tools.py`
- Test: `tests/agents/test_statute_retriever_tools.py`

Anthropic needs JSON-schema tool definitions in the `tools` parameter. Expose a function returning them — this keeps tool surface in one place.

- [ ] **Step 1: Write failing test**

Append:

```python
from jurist.agents.statute_retriever_tools import tool_definitions


def test_tool_definitions_include_all_five():
    tools = tool_definitions()
    names = {t["name"] for t in tools}
    assert names == {"search_articles", "list_neighbors", "get_article",
                     "follow_cross_ref", "done"}
    # Each has input_schema with required fields
    for t in tools:
        assert t["input_schema"]["type"] == "object"
        assert "properties" in t["input_schema"]


def test_done_schema_requires_selected_of_objects_with_article_id_and_reason():
    tools = tool_definitions()
    done = next(t for t in tools if t["name"] == "done")
    selected = done["input_schema"]["properties"]["selected"]
    assert selected["type"] == "array"
    assert selected["items"]["required"] == ["article_id", "reason"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v -k tool_definitions`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Append to `src/jurist/agents/statute_retriever_tools.py`:

```python
def tool_definitions() -> list[dict[str, Any]]:
    """Anthropic `tools` array for the statute retriever loop."""
    return [
        {
            "name": "search_articles",
            "description": "Lexical search over the article corpus. Use when the catalog doesn't show obvious candidates.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "list_neighbors",
            "description": "Return labels + titles for articles connected by outgoing cross-references. Cheap — use to survey before loading bodies.",
            "input_schema": {
                "type": "object",
                "properties": {"article_id": {"type": "string"}},
                "required": ["article_id"],
            },
        },
        {
            "name": "get_article",
            "description": "Return the full article body plus its outgoing_refs.",
            "input_schema": {
                "type": "object",
                "properties": {"article_id": {"type": "string"}},
                "required": ["article_id"],
            },
        },
        {
            "name": "follow_cross_ref",
            "description": "Same as get_article(to_id) but records the traversal. The edge (from_id, to_id) must exist in the corpus.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_id": {"type": "string"},
                    "to_id": {"type": "string"},
                },
                "required": ["from_id", "to_id"],
            },
        },
        {
            "name": "done",
            "description": "Terminate with selected articles. Each entry needs an article_id present in the corpus and a short reason.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selected": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "article_id": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["article_id", "reason"],
                        },
                    },
                },
                "required": ["selected"],
            },
        },
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/agents/test_statute_retriever_tools.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever_tools.py
git add src/jurist/agents/statute_retriever_tools.py tests/agents/test_statute_retriever_tools.py
git commit -m "feat(tools): tool_definitions() for Anthropic tools array"
```

---

## Task 19: Rewrite `statute_retriever` agent

**Files:**
- Modify: `src/jurist/agents/statute_retriever.py`
- Delete: `tests/agents/test_fake_statute_retriever.py` (fake removed)
- Create: `tests/agents/test_statute_retriever.py` (new test for the real agent)

The agent translates `LoopEvent`s to `TraceEvent`s per spec §4, builds `StatuteRetrieverOut`, and emits all events in the right order.

- [ ] **Step 1: Inspect the existing fake test**

Run: `cat tests/agents/test_fake_statute_retriever.py`
Note: we're deleting this file at the end of this task. Confirm there are no referenced-elsewhere imports (there shouldn't be).

- [ ] **Step 2: Write failing test for the real agent**

Create `tests/agents/test_statute_retriever.py`:

```python
import pytest

from jurist.agents import statute_retriever
from jurist.agents.statute_retriever_tools import ToolExecutor
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    KGSnapshot,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
)
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


@pytest.fixture
def small_kg():
    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="Art A", title="T",
            body_text="a body", outgoing_refs=["B"],
        ),
        ArticleNode(
            article_id="B", bwb_id="BWBX", label="Art B", title="T",
            body_text="b body", outgoing_refs=[],
        ),
    ]
    edges = [ArticleEdge(from_id="A", to_id="B", kind="explicit")]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=edges)
    return NetworkXKG.from_snapshot(snap)


@pytest.mark.asyncio
async def test_agent_emits_event_sequence(small_kg, monkeypatch):
    script = [
        ScriptedTurn(
            text_deltas=["Ik lees artikel A."],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        ),
        ScriptedTurn(
            text_deltas=["Volg naar B."],
            tool_uses=[ScriptedToolUse(
                name="follow_cross_ref", args={"from_id": "A", "to_id": "B"}
            )],
        ),
        ScriptedTurn(
            tool_uses=[ScriptedToolUse(name="done", args={"selected": [
                {"article_id": "A", "reason": "core"},
                {"article_id": "B", "reason": "procedure"},
            ]})],
        ),
    ]
    mock = MockAnthropicClient(script)
    ctx = RunContext(kg=small_kg, llm=mock)

    events = []
    async for ev in statute_retriever.run(
        StatuteRetrieverIn(
            sub_questions=["q?"], concepts=["huurverhoging"],
            intent="legality_check",
        ),
        ctx=ctx,
    ):
        events.append(ev)

    types = [e.type for e in events]
    # First and last
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    # Thinking, tool calls, node visits, edge traversal, done
    assert "agent_thinking" in types
    assert types.count("tool_call_started") >= 3
    assert types.count("tool_call_completed") >= 3
    assert "node_visited" in types
    assert "edge_traversed" in types
    # Output shape
    out = StatuteRetrieverOut.model_validate(events[-1].data)
    assert [c.article_id for c in out.cited_articles] == ["A", "B"]
    assert out.cited_articles[0].reason == "core"


@pytest.mark.asyncio
async def test_agent_node_visited_on_get_article_but_not_on_list_neighbors(small_kg):
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="list_neighbors", args={"article_id": "A"},
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    ctx = RunContext(kg=small_kg, llm=mock)
    events = []
    async for ev in statute_retriever.run(
        StatuteRetrieverIn(sub_questions=[], concepts=[], intent="other"),
        ctx=ctx,
    ):
        events.append(ev)
    # list_neighbors does NOT trigger node_visited
    assert not any(e.type == "node_visited" for e in events)
    # Hit ids / neighbor ids surface in tool_call_completed.data
    tcc = next(e for e in events if e.type == "tool_call_completed")
    assert "neighbor_ids" in tcc.data
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/agents/test_statute_retriever.py -v`
Expected: FAIL — old fake implementation has the wrong signature or fails.

- [ ] **Step 4: Implement**

Replace `src/jurist/agents/statute_retriever.py` entirely:

```python
"""Real statute retriever — Claude Sonnet tool-use loop over the huurrecht KG."""
from __future__ import annotations

import logging
import time
from typing import AsyncIterator

from jurist.agents.statute_retriever_tools import (
    ToolExecutor,
    tool_definitions,
)
from jurist.config import RunContext, settings
from jurist.llm.client import (
    Coerced,
    Done,
    TextDelta,
    ToolResultEvent,
    ToolUseStart,
    run_tool_loop,
)
from jurist.llm.prompts import render_statute_retriever_system
from jurist.schemas import (
    CitedArticle,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    TraceEvent,
)

logger = logging.getLogger(__name__)


def _build_user_message(inp: StatuteRetrieverIn) -> str:
    lines = [
        "User's question has been decomposed as follows:",
        "",
        "Sub-questions:",
        *[f"- {s}" for s in inp.sub_questions],
        "",
        "Concepts:",
        *[f"- {c}" for c in inp.concepts],
        "",
        f"Intent: {inp.intent}",
        "",
        "Select the articles from the catalog most relevant to these "
        "sub-questions and concepts. When ready, call `done`.",
    ]
    return "\n".join(lines)


async def run(
    input: StatuteRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system_prompt = render_statute_retriever_system(
        ctx.kg, snippet_chars=settings.statute_catalog_snippet_chars,
    )
    executor = ToolExecutor(ctx.kg, snippet_chars=settings.statute_catalog_snippet_chars)
    user_message = _build_user_message(input)

    started = time.monotonic()
    logger.info(
        "statute_retriever loop start: catalog_nodes=%d max_iters=%d cap_s=%.1f",
        len(ctx.kg.all_nodes()),
        settings.max_retriever_iters,
        settings.retriever_wall_clock_cap_s,
    )

    final_selected: list[dict] = []
    iter_count = 0

    async for ev in run_tool_loop(
        client=ctx.llm if not _is_mock(ctx.llm) else None,
        mock=ctx.llm if _is_mock(ctx.llm) else None,
        model=settings.model_retriever,
        executor=executor,
        system=system_prompt,
        tools=tool_definitions(),
        user_message=user_message,
        max_iters=settings.max_retriever_iters,
        wall_clock_cap_s=settings.retriever_wall_clock_cap_s,
    ):
        if isinstance(ev, TextDelta):
            yield TraceEvent(type="agent_thinking", data={"text": ev.text})
        elif isinstance(ev, ToolUseStart):
            iter_count += 1
            yield TraceEvent(
                type="tool_call_started",
                data={"tool": ev.name, "args": ev.args},
            )
        elif isinstance(ev, ToolResultEvent):
            completed_data = {
                "tool": ev.name,
                "args": ev.args,
                "result_summary": ev.result.result_summary,
                "is_error": ev.result.is_error,
                **ev.result.extra,
            }
            yield TraceEvent(type="tool_call_completed", data=completed_data)
            # KG effects
            if ev.result.kg_effect:
                if "node_visited" in ev.result.kg_effect:
                    yield TraceEvent(
                        type="node_visited",
                        data={"article_id": ev.result.kg_effect["node_visited"]},
                    )
                if "edge_traversed" in ev.result.kg_effect:
                    frm, to = ev.result.kg_effect["edge_traversed"]
                    yield TraceEvent(
                        type="edge_traversed",
                        data={"from_id": frm, "to_id": to},
                    )
        elif isinstance(ev, Done):
            final_selected = ev.selected
        elif isinstance(ev, Coerced):
            final_selected = ev.selected
            logger.warning(
                "statute_retriever coerced: reason=%s selected=%d",
                ev.reason,
                len(ev.selected),
            )
            # Emit synthetic done events so the UI shows a consistent terminator.
            args = {"coerced": True, "reason": ev.reason, "selected": ev.selected}
            yield TraceEvent(type="tool_call_started",
                             data={"tool": "done", "args": args})
            yield TraceEvent(
                type="tool_call_completed",
                data={
                    "tool": "done",
                    "args": args,
                    "result_summary": f"coerced ({ev.reason}), {len(ev.selected)} selected",
                    "is_error": False,
                    "selected_count": len(ev.selected),
                },
            )

    cited: list[CitedArticle] = []
    for entry in final_selected:
        aid = entry["article_id"]
        node = ctx.kg.get_node(aid)
        if node is None:
            logger.warning("dropping unknown article_id from final: %s", aid)
            continue
        cited.append(CitedArticle(
            bwb_id=node.bwb_id,
            article_id=aid,
            article_label=node.label,
            body_text=node.body_text,
            reason=entry["reason"],
        ))
    out = StatuteRetrieverOut(cited_articles=cited)
    logger.info(
        "statute_retriever loop end: cited=%d iters=%d elapsed_s=%.2f",
        len(cited), iter_count, time.monotonic() - started,
    )
    yield TraceEvent(type="agent_finished", data=out.model_dump())


def _is_mock(obj: object) -> bool:
    """Heuristic: the MockAnthropicClient exposes next_turn; AsyncAnthropic does not."""
    return hasattr(obj, "next_turn") and not hasattr(obj, "messages")
```

- [ ] **Step 5: Run the new test**

Run: `uv run pytest tests/agents/test_statute_retriever.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Delete the old fake test**

```bash
git rm tests/agents/test_fake_statute_retriever.py
```

- [ ] **Step 7: Run the full agents test suite**

Run: `uv run pytest tests/agents -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/jurist/agents/statute_retriever.py
git add src/jurist/agents/statute_retriever.py tests/agents/test_statute_retriever.py
git commit -m "feat(agent): real statute retriever driven by run_tool_loop"
```

---

## Task 20: Thread `RunContext` through orchestrator + app

**Files:**
- Modify: `src/jurist/api/orchestrator.py`
- Modify: `src/jurist/api/app.py`
- Modify: `tests/api/test_orchestrator.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add Anthropic client to app lifespan**

In `src/jurist/api/app.py`:

Add import at the top:

```python
from anthropic import AsyncAnthropic
```

Inside `lifespan`, after the existing KG-load block and before `yield`:

```python
    app.state.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    logger.info("Anthropic client ready (model: %s)", settings.model_retriever)
```

(`anthropic_api_key=None` is acceptable at init — the SDK will error only when a call is made without a key, which is fine for tests that never exercise the real path.)

- [ ] **Step 2: Update orchestrator signature + wrap retriever for run_failed on LLM errors**

Per spec §5: Anthropic 429/5xx is not retried; orchestrator emits `run_failed{reason: "llm_error", detail}`. Wrap only the statute_retriever pump — other agents stay as-is (fakes don't fail).

Edit `src/jurist/api/orchestrator.py`. Add import near the top:

```python
from jurist.config import RunContext
```

Change `run_question`'s signature and the statute_retriever block:

```python
async def run_question(
    question: str,
    run_id: str,
    buffer: EventBuffer,
    ctx: RunContext | None = None,
) -> None:
    """End-to-end run. In M2+ requires a RunContext for the statute retriever."""
    await buffer.put(
        TraceEvent(
            type="run_started",
            run_id=run_id,
            ts=_now_iso(),
            data={"question": question},
        )
    )

    # 1. Decomposer — fake
    dec_final = await _pump(
        "decomposer",
        decomposer.run(DecomposerIn(question=question)),
        run_id,
        buffer,
    )
    decomposer_out = DecomposerOut.model_validate(dec_final.data)

    # 2. Statute retriever — real in M2
    if ctx is None:
        raise RuntimeError(
            "run_question requires a RunContext in M2+. "
            "The API lifespan must provide one."
        )
    stat_in = StatuteRetrieverIn(
        sub_questions=decomposer_out.sub_questions,
        concepts=decomposer_out.concepts,
        intent=decomposer_out.intent,
    )
    try:
        stat_final = await _pump(
            "statute_retriever",
            statute_retriever.run(stat_in, ctx=ctx),
            run_id,
            buffer,
        )
    except Exception as exc:  # noqa: BLE001 — surface all LLM/network errors
        await buffer.put(
            TraceEvent(
                type="run_failed",
                run_id=run_id,
                ts=_now_iso(),
                data={"reason": "llm_error", "detail": f"{type(exc).__name__}: {exc}"},
            )
        )
        return
    stat_out = StatuteRetrieverOut.model_validate(stat_final.data)
    # ... rest of the function (case retriever / synthesizer / validator / run_finished)
    # stays unchanged.
```

Leave agents 3–5 and the trailing `run_finished` block alone.

- [ ] **Step 3: Update app.py call site**

In `src/jurist/api/app.py`'s `ask` endpoint:

```python
    ctx = RunContext(kg=app.state.kg, llm=app.state.anthropic)
    task = asyncio.create_task(run_question(req.question, question_id, buf, ctx))
```

Add the import: `from jurist.config import RunContext`.

- [ ] **Step 4: Update conftest to build a mock context**

Edit `tests/conftest.py`. If the file doesn't exist or doesn't export helpers, add:

```python
import pytest

from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


@pytest.fixture
def minimal_ctx_factory():
    """Returns a callable that builds a RunContext with a tiny KG and the
    supplied script. Use `ctx = factory(script)` in tests."""

    def _make(script):
        nodes = [
            ArticleNode(
                article_id="A", bwb_id="BWBX", label="Art A", title="T",
                body_text="body", outgoing_refs=[],
            ),
        ]
        snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
        kg = NetworkXKG.from_snapshot(snap)
        mock = MockAnthropicClient(script)
        return RunContext(kg=kg, llm=mock)

    return _make
```

- [ ] **Step 5: Update `tests/api/test_orchestrator.py`**

Rewrite to pass a `RunContext` built from a MockAnthropicClient that scripts a short successful retriever run:

```python
import pytest

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


def _orch_ctx() -> RunContext:
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
    return RunContext(kg=kg, llm=MockAnthropicClient(script))


@pytest.mark.asyncio
async def test_orchestrator_emits_run_started_and_run_finished():
    buf = EventBuffer()
    await run_question("Mag de huur 15% omhoog?", run_id="run_test",
                       buffer=buf, ctx=_orch_ctx())
    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"


@pytest.mark.asyncio
async def test_orchestrator_stamps_run_id_and_agent_on_every_event():
    buf = EventBuffer()
    await run_question("q", run_id="run_test", buffer=buf, ctx=_orch_ctx())
    async for ev in buf.subscribe():
        assert ev.run_id == "run_test"
        assert ev.ts != ""
        if ev.type not in {"run_started", "run_finished", "run_failed"}:
            assert ev.agent != ""


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_expected_order():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    agent_order = []
    async for ev in buf.subscribe():
        if ev.type == "agent_started":
            agent_order.append(ev.agent)
    assert agent_order == [
        "decomposer",
        "statute_retriever",
        "case_retriever",
        "synthesizer",
        "validator",
    ]


@pytest.mark.asyncio
async def test_orchestrator_run_finished_carries_final_answer():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    final = None
    async for ev in buf.subscribe():
        if ev.type == "run_finished":
            final = ev
    assert final is not None
    ans = final.data["final_answer"]
    assert "korte_conclusie" in ans
    assert "aanbeveling" in ans


class _BoomLLM:
    """Raises on first turn — simulates Anthropic 429/5xx."""

    def next_turn(self, history):
        raise RuntimeError("anthropic 503")


@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_llm_error():
    """Per spec §5: uncaught exception in statute_retriever → run_failed."""
    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="A", title="T",
            body_text="b", outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    kg = NetworkXKG.from_snapshot(snap)
    ctx = RunContext(kg=kg, llm=_BoomLLM())
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=ctx)
    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "llm_error"
    assert "anthropic 503" in final.data["detail"]
    # No run_finished emitted
    assert not any(e.type == "run_finished" for e in events)
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v -k "not e2e"`
Expected: all pass. If any pre-M2 test still called `run_question` without `ctx`, update it now.

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/jurist/ tests/
git add src/jurist/api/ src/jurist/config.py tests/ -u
git commit -m "feat(api): thread RunContext through orchestrator + lifespan wires AsyncAnthropic"
```

---

## Task 21: Integration test (real Anthropic, RUN_E2E gated)

**Files:**
- Create: `tests/integration/test_m2_statute_retriever_e2e.py`

- [ ] **Step 1: Check the existing integration directory**

Run: `ls tests/integration/`
Expected: at least `__init__.py` + prior integration tests.

- [ ] **Step 2: Write the test**

Create `tests/integration/test_m2_statute_retriever_e2e.py`:

```python
"""Real-Anthropic integration test for the M2 statute retriever.

Gated on RUN_E2E=1 to avoid burning tokens in normal test runs.
"""
from __future__ import annotations

import os

import pytest
from anthropic import AsyncAnthropic

from jurist.agents import statute_retriever
from jurist.agents.decomposer import run as decomposer_run
from jurist.config import RunContext, settings
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import DecomposerIn, DecomposerOut, StatuteRetrieverIn, StatuteRetrieverOut


LOCKED_QUESTION = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
A248_SUFFIX = "Artikel248"  # art. 7:248 BW


@pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "1",
    reason="gated on RUN_E2E=1 (real Anthropic call)",
)
@pytest.mark.asyncio
async def test_m2_retriever_finds_7_248_on_locked_question():
    # Load real KG (M1 output).
    kg = NetworkXKG.load_from_json(settings.kg_path)
    assert len(kg.all_nodes()) >= 200, "Expected the full M1 KG"

    # Real Anthropic client.
    client = AsyncAnthropic()  # picks ANTHROPIC_API_KEY from env

    # Drive the fake decomposer to get realistic canned input.
    dec_events = []
    async for ev in decomposer_run(DecomposerIn(question=LOCKED_QUESTION)):
        dec_events.append(ev)
    dec_out = DecomposerOut.model_validate(dec_events[-1].data)

    ctx = RunContext(kg=kg, llm=client)
    stat_in = StatuteRetrieverIn(
        sub_questions=dec_out.sub_questions,
        concepts=dec_out.concepts,
        intent=dec_out.intent,
    )

    events = []
    async for ev in statute_retriever.run(stat_in, ctx=ctx):
        events.append(ev)

    # Final output shape.
    out = StatuteRetrieverOut.model_validate(events[-1].data)
    assert len(out.cited_articles) >= 1, "retriever returned empty cited_articles"

    # Acceptance: 7:248 is cited.
    assert any(A248_SUFFIX in c.article_id for c in out.cited_articles), \
        f"expected art. 7:248 BW in cited_articles; got {[c.article_id for c in out.cited_articles]}"

    # Not coerced.
    coerced_events = [
        e for e in events
        if e.type == "tool_call_started"
        and e.data.get("tool") == "done"
        and e.data.get("args", {}).get("coerced") is True
    ]
    assert not coerced_events, "retriever terminated via coercion, not a clean done"

    # Visit path length >= 3 nodes.
    node_visits = [e for e in events if e.type == "node_visited"]
    unique_visits = {e.data["article_id"] for e in node_visits}
    assert len(unique_visits) >= 3, \
        f"expected visit path >= 3 nodes; got {len(unique_visits)}"

    # Zero is_error tool results.
    err_tcc = [e for e in events if e.type == "tool_call_completed"
               and e.data.get("is_error") is True]
    assert not err_tcc, f"unexpected tool errors: {[e.data for e in err_tcc]}"
```

- [ ] **Step 3: Run the test WITHOUT RUN_E2E**

Run: `uv run pytest tests/integration/test_m2_statute_retriever_e2e.py -v`
Expected: 1 SKIPPED with reason message.

- [ ] **Step 4: Run the test WITH RUN_E2E (optional, costs tokens)**

Only when ready for a real smoke test; ensure `.env` has `ANTHROPIC_API_KEY`:
Run: `RUN_E2E=1 uv run pytest tests/integration/test_m2_statute_retriever_e2e.py -v -s`
Expected: PASS. If it fails because the model didn't select 7:248, the failure message shows what it did pick — adjust the system prompt or seed hints only after confirming the failure is reproducible across ≥2 runs (LLM sampling variance).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_m2_statute_retriever_e2e.py
git commit -m "test(integration): M2 e2e retriever against locked question (RUN_E2E gated)"
```

---

## Task 22: Full suite + lint + smoke

**Files:** none (verification task)

- [ ] **Step 1: Lint**

Run: `uv run ruff check .`
Expected: no issues. Fix any.

- [ ] **Step 2: Full unit + orchestrator suite**

Run: `uv run pytest tests/ -v --ignore=tests/integration`
Expected: all pass. Approximate run time: ~75s (existing fakes still sleep between deltas).

- [ ] **Step 3: Start API + frontend; smoke the locked question**

In one terminal:

```bash
uv run python -m jurist.api
```

In another:

```bash
cd web && npm run dev
```

Open `http://localhost:5173`. Submit the locked question: *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*

Expected observations:
- TracePanel shows `statute_retriever` with real tool calls (`get_article`, possibly `follow_cross_ref`, `list_neighbors`).
- KGPanel lights up nodes as the retriever visits them; edges animate on `follow_cross_ref`.
- Final answer panel still shows the M0 canned answer — synthesizer is still fake in M2. This is expected.
- Check backend logs: `INFO  statute_retriever loop start` and `INFO  statute_retriever loop end: cited=N iters=M elapsed_s=...` appear.

If anything breaks:
- 500 from `/api/ask` → check the FastAPI lifespan logs; missing `ANTHROPIC_API_KEY` is the usual cause.
- Empty KG animation → confirm `get_article` / `follow_cross_ref` actually fire (check server logs). If the model only called `search_articles` and `list_neighbors`, that's a prompting issue, not a wiring issue — revisit the system prompt.

- [ ] **Step 4: Commit any remaining fixes**

If the smoke test surfaced changes (e.g., prompt tweaks), commit them with a clear message. Do not commit anything unrelated.

- [ ] **Step 5: Tag the milestone**

```bash
git tag -a m2-statute-retriever -m "M2 — Real statute retriever (Claude Sonnet tool-use loop over huurrecht KG)"
```

Do not push yet — that's a separate, reversible action best done after the user reviews the full branch.

---

## Self-review checklist (for the implementer before requesting review)

- [ ] All 22 tasks ticked off and committed.
- [ ] `uv run ruff check .` clean.
- [ ] `uv run pytest tests/ -v --ignore=tests/integration` — all pass.
- [ ] `RUN_E2E=1 uv run pytest tests/integration/test_m2_statute_retriever_e2e.py -v` — passes (or failure understood and documented).
- [ ] Manual smoke — locked question in the UI produces a real KG-walk animation.
- [ ] No new dependencies beyond `anthropic`.
- [ ] Spec §14 acceptance criteria — each box ticked.
