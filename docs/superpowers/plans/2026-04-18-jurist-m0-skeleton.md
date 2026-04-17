# Jurist v1 — M0 Implementation Plan (Skeleton with Fakes)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end plumbing — FastAPI + SSE + React Flow + Zustand — driven by fake agents that emit hardcoded events. No LLM calls, no data sources. Produces a runnable system that animates the KG, streams a fake trace, and renders a canned Dutch answer for the locked demo question.

**Architecture:** FastAPI backend with an async agent pipeline. Each agent is an async generator yielding typed `TraceEvent`s. The orchestrator chains agents, stamps events with `run_id` / `agent` / `ts`, and emits them over one SSE stream per run. The frontend is Vite + React with a Zustand store that reduces events into KG node state, edge state, trace log, and partial answer. Every agent in M0 is a fake that yields hardcoded events — real agents replace the fakes one at a time in M1–M4.

**Tech Stack:** Python 3.11+, uv, FastAPI, Uvicorn, Pydantic 2, pytest, pytest-asyncio, httpx, sse-starlette. Node 20+, React 18, TypeScript 5, Vite, @xyflow/react (React Flow), Zustand, Tailwind 3.

**Scope note:** This plan covers **M0 only** per the design spec. Milestones M1–M5 are planned separately after M0 is verified working, following the "end-to-end first, replace one piece at a time" principle.

**Authoritative design:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`.

---

## File structure

### Backend (new)

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | uv-managed deps and project metadata. |
| `.python-version` | Pins Python 3.11. |
| `src/jurist/__init__.py` | Package marker. |
| `src/jurist/config.py` | Reads env vars; exposes typed `Settings`. |
| `src/jurist/schemas.py` | All Pydantic types: `TraceEvent`, agent I/O, KG types, citation types. |
| `src/jurist/fakes.py` | Hardcoded `FAKE_KG`, `FAKE_CASES`, `FAKE_ANSWER` for use by fake agents. |
| `src/jurist/agents/__init__.py` | Package marker. |
| `src/jurist/agents/decomposer.py` | Fake `run()` — yields thinking + finished. |
| `src/jurist/agents/statute_retriever.py` | Fake KG walker — yields `node_visited` / `edge_traversed`. |
| `src/jurist/agents/case_retriever.py` | Fake RAG — yields `case_found` events from `FAKE_CASES`. |
| `src/jurist/agents/synthesizer.py` | Yields canned answer token-by-token. |
| `src/jurist/agents/validator_stub.py` | Returns `valid: true`. |
| `src/jurist/api/__init__.py` | Package marker. |
| `src/jurist/api/sse.py` | SSE formatter + in-memory event buffer per run. |
| `src/jurist/api/orchestrator.py` | Chains agents, stamps events, forwards to buffer. |
| `src/jurist/api/app.py` | FastAPI app; `POST /ask`, `GET /stream`. |
| `src/jurist/api/__main__.py` | `python -m jurist.api` — uvicorn entry. |
| `tests/__init__.py` | Package marker. |
| `tests/conftest.py` | pytest-asyncio registration + shared fixtures. |
| `tests/test_schemas.py` | Pydantic types instantiate and roundtrip. |
| `tests/agents/__init__.py` | Package marker. |
| `tests/agents/test_fake_decomposer.py` | Event sequence + payload. |
| `tests/agents/test_fake_statute_retriever.py` | Visit pattern + final output. |
| `tests/agents/test_fake_case_retriever.py` | Case events + final output. |
| `tests/agents/test_fake_synthesizer.py` | Token deltas + final answer. |
| `tests/agents/test_validator_stub.py` | Always valid. |
| `tests/api/__init__.py` | Package marker. |
| `tests/api/test_sse.py` | Envelope format + buffer semantics. |
| `tests/api/test_orchestrator.py` | Event stamping + agent chaining order. |
| `tests/api/test_endpoints.py` | Integration: POST /ask + GET /stream with httpx. |

### Frontend (new)

| Path | Responsibility |
| --- | --- |
| `web/package.json` | Node deps + scripts. |
| `web/vite.config.ts` | Vite config; proxies `/api` to `:8000`. |
| `web/tsconfig.json` | TypeScript config. |
| `web/tsconfig.node.json` | TS config for Vite config file. |
| `web/tailwind.config.js` | Tailwind content globs. |
| `web/postcss.config.js` | Tailwind + autoprefixer. |
| `web/index.html` | App root. |
| `web/src/main.tsx` | React entry. |
| `web/src/App.tsx` | Shell: input bar + 3-panel layout. |
| `web/src/index.css` | Tailwind directives. |
| `web/src/types/events.ts` | TypeScript mirror of backend event schemas. |
| `web/src/api/ask.ts` | POST /api/ask helper. |
| `web/src/api/sse.ts` | `subscribe(questionId, onEvent)` — EventSource wrapper. |
| `web/src/state/runStore.ts` | Zustand store; reducer per event type. |
| `web/src/components/KGPanel.tsx` | React Flow canvas with node/edge highlight states. |
| `web/src/components/TracePanel.tsx` | Per-agent streamed trace view. |
| `web/src/components/AnswerPanel.tsx` | Structured answer renderer. |
| `web/src/components/CitationLink.tsx` | Opens citation URL in new tab. |

---

## Tasks

### Task 1: Backend scaffold

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `src/jurist/__init__.py`

- [ ] **Step 1: Create `.python-version`**

```
3.11
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "jurist"
version = "0.1.0"
description = "Grounded Dutch huurrecht Q&A — multi-agent demo"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
    "sse-starlette>=2.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jurist"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
```

- [ ] **Step 3: Create package marker `src/jurist/__init__.py`**

```python
"""Jurist — Dutch huurrecht multi-agent Q&A demo."""
```

- [ ] **Step 4: Install deps**

Run: `uv sync --extra dev`
Expected: creates `.venv/`, installs all deps, writes `uv.lock`.

- [ ] **Step 5: Smoke test import**

Run: `uv run python -c "import jurist; print(jurist.__doc__)"`
Expected output:
```
Jurist — Dutch huurrecht multi-agent Q&A demo.
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .python-version src/jurist/__init__.py uv.lock
git commit -m "feat: backend scaffold (uv + FastAPI + pytest)"
```

---

### Task 2: Core schemas

**Files:**
- Create: `src/jurist/schemas.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Create empty `tests/__init__.py`**

```python
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared pytest configuration."""
```

(pytest-asyncio auto-discovers via `asyncio_mode = "auto"` in `pyproject.toml`.)

- [ ] **Step 3: Write failing test `tests/test_schemas.py`**

```python
from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    CitedCase,
    DecomposerIn,
    DecomposerOut,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    StructuredAnswer,
    SynthesizerIn,
    SynthesizerOut,
    TraceEvent,
    UitspraakCitation,
    ValidatorIn,
    ValidatorOut,
    WetArtikelCitation,
)


def test_trace_event_defaults_empty():
    ev = TraceEvent(type="agent_started")
    assert ev.type == "agent_started"
    assert ev.agent == ""
    assert ev.run_id == ""
    assert ev.ts == ""
    assert ev.data == {}


def test_trace_event_roundtrip():
    ev = TraceEvent(
        type="node_visited",
        agent="statute_retriever",
        run_id="run_abc",
        ts="2026-04-18T10:00:00Z",
        data={"article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"},
    )
    dumped = ev.model_dump()
    assert TraceEvent.model_validate(dumped) == ev


def test_decomposer_out_intent_literal():
    out = DecomposerOut(
        sub_questions=["Mag de huur omhoog?"],
        concepts=["huurverhoging"],
        intent="legality_check",
    )
    assert out.intent == "legality_check"


def test_cited_article_has_body_text():
    a = CitedArticle(
        bwb_id="BWBR0005290",
        article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        article_label="Boek 7, Artikel 248",
        body_text="Een verhuurder kan tot aan het tijdstip...",
        reason="Primary statute on huurprijsaanpassing.",
    )
    assert a.body_text.startswith("Een verhuurder")


def test_article_node_outgoing_refs_default_empty():
    node = ArticleNode(
        article_id="x/1",
        bwb_id="x",
        label="l",
        title="t",
        body_text="b",
    )
    assert node.outgoing_refs == []


def test_article_edge_kind_literal():
    e = ArticleEdge(from_id="a", to_id="b", kind="regex")
    assert e.kind == "regex"


def test_structured_answer_can_be_empty_lists():
    ans = StructuredAnswer(
        korte_conclusie="Dat mag niet zomaar.",
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling="Raadpleeg de Huurcommissie.",
    )
    assert ans.aanbeveling.startswith("Raadpleeg")


def test_validator_out_defaults_empty_issues():
    v = ValidatorOut(valid=True)
    assert v.issues == []


# Reference imports to silence unused warnings and confirm all types load.
_ = (
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedCase,
    DecomposerIn,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    SynthesizerIn,
    SynthesizerOut,
    UitspraakCitation,
    ValidatorIn,
    WetArtikelCitation,
)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.schemas'`.

- [ ] **Step 5: Implement `src/jurist/schemas.py`**

```python
"""All Pydantic types used across the backend."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------- Trace events ----------------

class TraceEvent(BaseModel):
    """A single event in an agent trace. Orchestrator fills agent/run_id/ts."""

    type: str
    agent: str = ""
    run_id: str = ""
    ts: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------- Knowledge graph ----------------

class ArticleNode(BaseModel):
    article_id: str
    bwb_id: str
    label: str
    title: str
    body_text: str
    outgoing_refs: list[str] = Field(default_factory=list)


class ArticleEdge(BaseModel):
    from_id: str
    to_id: str
    kind: Literal["explicit", "regex"] = "explicit"
    context: str | None = None


# ---------------- Retriever outputs ----------------

class CitedArticle(BaseModel):
    bwb_id: str
    article_id: str
    article_label: str
    body_text: str
    reason: str


class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str
    snippet: str
    similarity: float
    reason: str
    url: str


# ---------------- Agent I/O ----------------

class DecomposerIn(BaseModel):
    question: str


class DecomposerOut(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: Literal["legality_check", "calculation", "procedure", "other"]


class StatuteRetrieverIn(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: str


class StatuteRetrieverOut(BaseModel):
    cited_articles: list[CitedArticle]


class CaseRetrieverIn(BaseModel):
    sub_questions: list[str]
    statute_context: list[CitedArticle]


class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]


# ---------------- Structured answer ----------------

class WetArtikelCitation(BaseModel):
    bwb_id: str
    article_label: str
    quote: str
    explanation: str


class UitspraakCitation(BaseModel):
    ecli: str
    quote: str
    explanation: str


class StructuredAnswer(BaseModel):
    korte_conclusie: str
    relevante_wetsartikelen: list[WetArtikelCitation]
    vergelijkbare_uitspraken: list[UitspraakCitation]
    aanbeveling: str


class SynthesizerIn(BaseModel):
    question: str
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]


class SynthesizerOut(BaseModel):
    answer: StructuredAnswer


# ---------------- Validator ----------------

class ValidatorIn(BaseModel):
    question: str
    answer: StructuredAnswer
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]


class ValidatorOut(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/jurist/schemas.py tests/__init__.py tests/conftest.py tests/test_schemas.py
git commit -m "feat: Pydantic schemas (TraceEvent, agent I/O, KG + citation types)"
```

---

### Task 3: Fake data module

**Files:**
- Create: `src/jurist/fakes.py`
- Test: `tests/test_fakes.py`

- [ ] **Step 1: Write failing test `tests/test_fakes.py`**

```python
from jurist.fakes import FAKE_ANSWER, FAKE_CASES, FAKE_KG, FAKE_VISIT_PATH
from jurist.schemas import ArticleEdge, ArticleNode, CitedCase, StructuredAnswer


def test_fake_kg_has_minimum_nodes_and_edges():
    nodes, edges = FAKE_KG
    assert len(nodes) >= 8
    assert len(edges) >= 10
    assert all(isinstance(n, ArticleNode) for n in nodes)
    assert all(isinstance(e, ArticleEdge) for e in edges)


def test_fake_kg_contains_artikel_248():
    nodes, _ = FAKE_KG
    ids = [n.article_id for n in nodes]
    assert any("Artikel248" in i for i in ids)


def test_fake_kg_edges_reference_existing_nodes():
    nodes, edges = FAKE_KG
    ids = {n.article_id for n in nodes}
    for e in edges:
        assert e.from_id in ids, f"edge from {e.from_id} not in node set"
        assert e.to_id in ids, f"edge to {e.to_id} not in node set"


def test_fake_visit_path_is_subset_of_kg():
    nodes, _ = FAKE_KG
    ids = {n.article_id for n in nodes}
    assert len(FAKE_VISIT_PATH) >= 3
    for aid in FAKE_VISIT_PATH:
        assert aid in ids


def test_fake_cases_three_entries_with_real_looking_ecli():
    assert len(FAKE_CASES) == 3
    assert all(isinstance(c, CitedCase) for c in FAKE_CASES)
    assert all(c.ecli.startswith("ECLI:NL:") for c in FAKE_CASES)


def test_fake_answer_has_citations_matching_fake_kg():
    assert isinstance(FAKE_ANSWER, StructuredAnswer)
    nodes, _ = FAKE_KG
    bwb_ids = {n.bwb_id for n in nodes}
    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        assert cit.bwb_id in bwb_ids
    ecli_set = {c.ecli for c in FAKE_CASES}
    for cit in FAKE_ANSWER.vergelijkbare_uitspraken:
        assert cit.ecli in ecli_set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fakes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.fakes'`.

- [ ] **Step 3: Implement `src/jurist/fakes.py`**

```python
"""Hardcoded fake data used by M0 fake agents.

Every ID, article label, and ECLI here is illustrative. Real data comes in M1+.
"""
from __future__ import annotations

from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CitedCase,
    StructuredAnswer,
    UitspraakCitation,
    WetArtikelCitation,
)

BWB_BW7 = "BWBR0005290"
BWB_UHW = "BWBR0002888"


def _node(aid: str, label: str, title: str, body: str, refs: list[str]) -> ArticleNode:
    return ArticleNode(
        article_id=aid,
        bwb_id=aid.split("/", 1)[0],
        label=label,
        title=title,
        body_text=body,
        outgoing_refs=refs,
    )


_A248 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel248"
_A249 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel249"
_A250 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel250"
_A252 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel252"
_A253 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel253"
_A254 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel254"
_A255 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel255"
_UHW6 = f"{BWB_UHW}/Artikel6"
_UHW10 = f"{BWB_UHW}/Artikel10"

_NODES: list[ArticleNode] = [
    _node(_A248, "Boek 7, Artikel 248",
          "Jaarlijkse huurverhoging — bevoegdheid verhuurder",
          "De verhuurder kan tot aan het tijdstip dat ... (fake body text)",
          [_A249, _A252, _UHW6]),
    _node(_A249, "Boek 7, Artikel 249",
          "Huurverhoging — voorwaarden en kennisgeving",
          "Een voorstel tot huurverhoging ... (fake body text)",
          [_A248, _A250]),
    _node(_A250, "Boek 7, Artikel 250",
          "Bezwaar huurder tegen huurverhoging",
          "De huurder kan ... (fake body text)",
          [_A249, _A254]),
    _node(_A252, "Boek 7, Artikel 252",
          "Geliberaliseerde huurovereenkomst",
          "In geval van een geliberaliseerde ... (fake body text)",
          [_A253]),
    _node(_A253, "Boek 7, Artikel 253",
          "Maximale huurprijs",
          "De maximale huurprijs wordt bepaald ... (fake body text)",
          [_UHW10]),
    _node(_A254, "Boek 7, Artikel 254",
          "Huurcommissie — geschillen",
          "Een geschil over huurprijs kan ... (fake body text)",
          [_A255]),
    _node(_A255, "Boek 7, Artikel 255",
          "Beroep tegen uitspraak huurcommissie",
          "Beroep staat open bij de kantonrechter ... (fake body text)",
          []),
    _node(_UHW6, "Uhw, Artikel 6",
          "Huurverhogingspercentage",
          "Het maximale huurverhogingspercentage ... (fake body text)",
          [_UHW10]),
    _node(_UHW10, "Uhw, Artikel 10",
          "Puntenstelsel woonruimte",
          "Het puntenstelsel bepaalt ... (fake body text)",
          []),
]


def _edge(a: str, b: str, kind: str = "explicit") -> ArticleEdge:
    return ArticleEdge(from_id=a, to_id=b, kind=kind)  # type: ignore[arg-type]


_EDGES: list[ArticleEdge] = [
    _edge(_A248, _A249),
    _edge(_A248, _A252),
    _edge(_A248, _UHW6),
    _edge(_A249, _A248),
    _edge(_A249, _A250),
    _edge(_A250, _A249),
    _edge(_A250, _A254),
    _edge(_A252, _A253),
    _edge(_A253, _UHW10),
    _edge(_A254, _A255),
    _edge(_UHW6, _UHW10),
]

FAKE_KG: tuple[list[ArticleNode], list[ArticleEdge]] = (_NODES, _EDGES)

FAKE_VISIT_PATH: list[str] = [_A248, _A249, _A250, _UHW6, _A252]

FAKE_CASES: list[CitedCase] = [
    CitedCase(
        ecli="ECLI:NL:HR:2020:1234",
        court="Hoge Raad",
        date="2020-09-11",
        snippet="De verhuurder mag de huur niet eenzijdig met een hoger percentage ...",
        similarity=0.87,
        reason="Leidende uitspraak over maximale huurverhoging bij gereguleerde huur.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
    ),
    CitedCase(
        ecli="ECLI:NL:RBAMS:2022:5678",
        court="Rechtbank Amsterdam",
        date="2022-03-14",
        snippet="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
        similarity=0.81,
        reason="Feitelijk zeer vergelijkbaar — huurder bezwaart succesvol tegen 15% verhoging.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
    ),
    CitedCase(
        ecli="ECLI:NL:GHARL:2023:9012",
        court="Gerechtshof Arnhem-Leeuwarden",
        date="2023-06-22",
        snippet="Bij geliberaliseerde huur geldt een andere norm, maar de redelijkheid ...",
        similarity=0.74,
        reason="Relevant voor onderscheid gereguleerd / geliberaliseerd.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:GHARL:2023:9012",
    ),
]

FAKE_ANSWER: StructuredAnswer = StructuredAnswer(
    korte_conclusie=(
        "Een huurverhoging van 15% is in de meeste gevallen niet toegestaan. "
        "Bij gereguleerde woonruimte geldt een jaarlijks maximum dat door de minister wordt vastgesteld; "
        "15% zal dit vrijwel zeker overschrijden. Bij geliberaliseerde woonruimte moet de verhoging redelijk zijn "
        "en aansluiten bij wat in de huurovereenkomst is afgesproken."
    ),
    relevante_wetsartikelen=[
        WetArtikelCitation(
            bwb_id=BWB_BW7,
            article_label="Boek 7, Artikel 248",
            quote="De verhuurder kan tot aan het tijdstip dat ...",
            explanation=(
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse huurverhoging voor te stellen "
                "binnen de wettelijke kaders."
            ),
        ),
        WetArtikelCitation(
            bwb_id=BWB_UHW,
            article_label="Uhw, Artikel 6",
            quote="Het maximale huurverhogingspercentage ...",
            explanation=(
                "Stelt het maximale percentage vast; 15% ligt daar ruim boven voor gereguleerde huur."
            ),
        ),
    ],
    vergelijkbare_uitspraken=[
        UitspraakCitation(
            ecli="ECLI:NL:RBAMS:2022:5678",
            quote="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
            explanation=(
                "Feitelijk zeer vergelijkbaar — rechtbank wijst het voorstel af als buitensporig."
            ),
        ),
    ],
    aanbeveling=(
        "Maak binnen zes weken na ontvangst van het voorstel bezwaar bij de verhuurder; "
        "kom je er niet uit, leg het geschil voor aan de Huurcommissie."
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fakes.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/fakes.py tests/test_fakes.py
git commit -m "feat: fake KG, cases, and canned answer for M0 demo"
```

---

### Task 4: Fake decomposer agent

**Files:**
- Create: `src/jurist/agents/__init__.py`
- Create: `src/jurist/agents/decomposer.py`
- Create: `tests/agents/__init__.py`
- Test: `tests/agents/test_fake_decomposer.py`

- [ ] **Step 1: Create package markers**

`src/jurist/agents/__init__.py`:
```python
```

`tests/agents/__init__.py`:
```python
```

- [ ] **Step 2: Write failing test `tests/agents/test_fake_decomposer.py`**

```python
import pytest

from jurist.agents.decomposer import run
from jurist.schemas import DecomposerIn, DecomposerOut


@pytest.mark.asyncio
async def test_decomposer_emits_started_thinking_finished_in_order():
    events = []
    async for ev in run(DecomposerIn(question="Mag de huur 15% omhoog?")):
        events.append(ev)
    types = [e.type for e in events]
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert "agent_thinking" in types


@pytest.mark.asyncio
async def test_decomposer_finished_payload_validates_as_decomposer_out():
    final = None
    async for ev in run(DecomposerIn(question="Mag de huur 15% omhoog?")):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = DecomposerOut.model_validate(final.data)
    assert out.intent in {"legality_check", "calculation", "procedure", "other"}
    assert len(out.sub_questions) >= 1
    assert len(out.concepts) >= 1


@pytest.mark.asyncio
async def test_decomposer_thinking_events_carry_text():
    thinking = []
    async for ev in run(DecomposerIn(question="q")):
        if ev.type == "agent_thinking":
            thinking.append(ev)
    assert len(thinking) >= 2
    assert all("text" in ev.data for ev in thinking)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_fake_decomposer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.agents.decomposer'`.

- [ ] **Step 4: Implement `src/jurist/agents/decomposer.py`**

```python
"""M0 fake decomposer — yields hardcoded thinking + a fixed decomposition."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.schemas import DecomposerIn, DecomposerOut, TraceEvent


async def run(input: DecomposerIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    deltas = [
        "De vraag gaat over huurverhoging — ",
        "specifiek een eenzijdig voorstel van 15%. ",
        "Subvragen: is de woning gereguleerd of geliberaliseerd, ",
        "en wat is het maximale jaarlijkse huurverhogingspercentage?",
    ]
    for d in deltas:
        await asyncio.sleep(0.25)
        yield TraceEvent(type="agent_thinking", data={"text": d})

    out = DecomposerOut(
        sub_questions=[
            "Is de woning gereguleerd of geliberaliseerd?",
            "Wat is het maximale jaarlijkse huurverhogingspercentage?",
            "Wat kan de huurder doen bij bezwaar?",
        ],
        concepts=["huurverhoging", "geliberaliseerd", "puntenstelsel", "Huurcommissie"],
        intent="legality_check",
    )
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_fake_decomposer.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/agents/__init__.py src/jurist/agents/decomposer.py \
        tests/agents/__init__.py tests/agents/test_fake_decomposer.py
git commit -m "feat: fake decomposer agent (M0 skeleton)"
```

---

### Task 5: Fake statute retriever agent

**Files:**
- Create: `src/jurist/agents/statute_retriever.py`
- Test: `tests/agents/test_fake_statute_retriever.py`

- [ ] **Step 1: Write failing test `tests/agents/test_fake_statute_retriever.py`**

```python
import pytest

from jurist.agents.statute_retriever import run
from jurist.fakes import FAKE_VISIT_PATH
from jurist.schemas import StatuteRetrieverIn, StatuteRetrieverOut


def _input() -> StatuteRetrieverIn:
    return StatuteRetrieverIn(
        sub_questions=["Wat is het max %?"],
        concepts=["huurverhoging"],
        intent="legality_check",
    )


@pytest.mark.asyncio
async def test_statute_retriever_emits_node_visited_for_each_step_of_path():
    visited = []
    async for ev in run(_input()):
        if ev.type == "node_visited":
            visited.append(ev.data["article_id"])
    assert visited == FAKE_VISIT_PATH


@pytest.mark.asyncio
async def test_statute_retriever_emits_edges_between_consecutive_visits():
    edges = []
    async for ev in run(_input()):
        if ev.type == "edge_traversed":
            edges.append((ev.data["from_id"], ev.data["to_id"]))
    # At least len(path)-1 edges between successive visits.
    assert len(edges) >= len(FAKE_VISIT_PATH) - 1


@pytest.mark.asyncio
async def test_statute_retriever_tool_call_events_wrap_visits():
    tool_starts = tool_completes = 0
    async for ev in run(_input()):
        if ev.type == "tool_call_started":
            tool_starts += 1
        if ev.type == "tool_call_completed":
            tool_completes += 1
    assert tool_starts > 0
    assert tool_starts == tool_completes


@pytest.mark.asyncio
async def test_statute_retriever_final_payload_validates():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = StatuteRetrieverOut.model_validate(final.data)
    assert len(out.cited_articles) >= 2
    ids = [a.article_id for a in out.cited_articles]
    assert all(aid in FAKE_VISIT_PATH for aid in ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_fake_statute_retriever.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/jurist/agents/statute_retriever.py`**

```python
"""M0 fake statute retriever — walks the fake KG on a hardcoded path."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.fakes import FAKE_KG, FAKE_VISIT_PATH
from jurist.schemas import (
    CitedArticle,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    TraceEvent,
)


async def run(input: StatuteRetrieverIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    nodes, _ = FAKE_KG
    by_id = {n.article_id: n for n in nodes}

    # Brief thinking before the first tool call.
    yield TraceEvent(
        type="agent_thinking",
        data={"text": "Ik zoek eerst de bepalingen over jaarlijkse huurverhoging."},
    )

    previous: str | None = None
    for aid in FAKE_VISIT_PATH:
        await asyncio.sleep(0.4)
        if previous is None:
            tool = "search_articles"
            args = {"query": "huurverhoging maximum percentage", "top_k": 5}
        else:
            tool = "follow_cross_ref"
            args = {"from_id": previous, "to_id": aid}

        yield TraceEvent(type="tool_call_started", data={"tool": tool, "args": args})
        await asyncio.sleep(0.2)
        node = by_id[aid]
        yield TraceEvent(
            type="tool_call_completed",
            data={
                "tool": tool,
                "args": args,
                "result_summary": f"{node.label}: {node.title}",
            },
        )
        yield TraceEvent(type="node_visited", data={"article_id": aid})
        if previous is not None:
            yield TraceEvent(
                type="edge_traversed",
                data={"from_id": previous, "to_id": aid},
            )
        previous = aid

    # Final "done" tool call.
    selected = [FAKE_VISIT_PATH[0], FAKE_VISIT_PATH[3]]
    yield TraceEvent(
        type="tool_call_started",
        data={"tool": "done", "args": {"selected_ids": selected}},
    )
    yield TraceEvent(
        type="tool_call_completed",
        data={
            "tool": "done",
            "args": {"selected_ids": selected},
            "result_summary": f"{len(selected)} articles selected.",
        },
    )

    cited = [
        CitedArticle(
            bwb_id=by_id[aid].bwb_id,
            article_id=aid,
            article_label=by_id[aid].label,
            body_text=by_id[aid].body_text,
            reason="Primary rule governing this question."
            if i == 0
            else "Sets the maximum percentage this question depends on.",
        )
        for i, aid in enumerate(selected)
    ]
    out = StatuteRetrieverOut(cited_articles=cited)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_fake_statute_retriever.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/statute_retriever.py tests/agents/test_fake_statute_retriever.py
git commit -m "feat: fake statute retriever (walks FAKE_KG)"
```

---

### Task 6: Fake case retriever agent

**Files:**
- Create: `src/jurist/agents/case_retriever.py`
- Test: `tests/agents/test_fake_case_retriever.py`

- [ ] **Step 1: Write failing test `tests/agents/test_fake_case_retriever.py`**

```python
import pytest

from jurist.agents.case_retriever import run
from jurist.fakes import FAKE_CASES
from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut


def _input() -> CaseRetrieverIn:
    return CaseRetrieverIn(sub_questions=["huur 15% verhogen"], statute_context=[])


@pytest.mark.asyncio
async def test_case_retriever_emits_search_started_and_cases():
    types = []
    async for ev in run(_input()):
        types.append(ev.type)
    assert "search_started" in types
    assert types.count("case_found") == len(FAKE_CASES)


@pytest.mark.asyncio
async def test_case_retriever_reranked_event_lists_kept_eclis():
    kept = None
    async for ev in run(_input()):
        if ev.type == "reranked":
            kept = ev.data["kept"]
    assert kept is not None
    assert set(kept).issubset({c.ecli for c in FAKE_CASES})


@pytest.mark.asyncio
async def test_case_retriever_final_payload_validates():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = CaseRetrieverOut.model_validate(final.data)
    assert len(out.cited_cases) == len(FAKE_CASES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_fake_case_retriever.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/jurist/agents/case_retriever.py`**

```python
"""M0 fake case retriever — yields the three hardcoded FAKE_CASES."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.fakes import FAKE_CASES
from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut, TraceEvent


async def run(input: CaseRetrieverIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    yield TraceEvent(type="search_started")

    for case in FAKE_CASES:
        await asyncio.sleep(0.3)
        yield TraceEvent(
            type="case_found",
            data={"ecli": case.ecli, "similarity": case.similarity},
        )

    yield TraceEvent(
        type="reranked",
        data={"kept": [c.ecli for c in FAKE_CASES]},
    )

    out = CaseRetrieverOut(cited_cases=list(FAKE_CASES))
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_fake_case_retriever.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/case_retriever.py tests/agents/test_fake_case_retriever.py
git commit -m "feat: fake case retriever (emits FAKE_CASES)"
```

---

### Task 7: Fake synthesizer agent

**Files:**
- Create: `src/jurist/agents/synthesizer.py`
- Test: `tests/agents/test_fake_synthesizer.py`

- [ ] **Step 1: Write failing test `tests/agents/test_fake_synthesizer.py`**

```python
import pytest

from jurist.agents.synthesizer import run
from jurist.fakes import FAKE_ANSWER, FAKE_CASES
from jurist.schemas import SynthesizerIn, SynthesizerOut


def _input() -> SynthesizerIn:
    return SynthesizerIn(
        question="Mag de huur 15% omhoog?",
        cited_articles=[],
        cited_cases=list(FAKE_CASES),
    )


@pytest.mark.asyncio
async def test_synthesizer_streams_answer_deltas_before_finishing():
    types = []
    async for ev in run(_input()):
        types.append(ev.type)
    delta_count = types.count("answer_delta")
    assert delta_count >= 5
    assert types[-1] == "agent_finished"
    last_delta_idx = max(i for i, t in enumerate(types) if t == "answer_delta")
    assert last_delta_idx < types.index("agent_finished")


@pytest.mark.asyncio
async def test_synthesizer_emits_citation_resolved_events():
    resolved = []
    async for ev in run(_input()):
        if ev.type == "citation_resolved":
            resolved.append(ev.data)
    # One per wetsartikel + one per uitspraak in FAKE_ANSWER.
    expected = len(FAKE_ANSWER.relevante_wetsartikelen) + len(FAKE_ANSWER.vergelijkbare_uitspraken)
    assert len(resolved) == expected
    kinds = {r["kind"] for r in resolved}
    assert kinds == {"artikel", "uitspraak"}


@pytest.mark.asyncio
async def test_synthesizer_final_payload_equals_fake_answer():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = SynthesizerOut.model_validate(final.data)
    assert out.answer == FAKE_ANSWER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_fake_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/jurist/agents/synthesizer.py`**

```python
"""M0 fake synthesizer — streams the canned FAKE_ANSWER token-by-token."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.fakes import FAKE_ANSWER
from jurist.schemas import SynthesizerIn, SynthesizerOut, TraceEvent

_ARTIKEL_URL = "https://wetten.overheid.nl/{bwb_id}"
_UITSPRAAK_URL = "https://uitspraken.rechtspraak.nl/details?id={ecli}"


def _tokenize(text: str) -> list[str]:
    # Word-level chunks with trailing spaces so reassembly reproduces the text.
    words = text.split(" ")
    return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]


async def run(input: SynthesizerIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    full_text = " ".join(
        [
            FAKE_ANSWER.korte_conclusie,
            *[c.quote + " " + c.explanation for c in FAKE_ANSWER.relevante_wetsartikelen],
            *[c.quote + " " + c.explanation for c in FAKE_ANSWER.vergelijkbare_uitspraken],
            FAKE_ANSWER.aanbeveling,
        ]
    )
    for tok in _tokenize(full_text):
        await asyncio.sleep(0.02)
        yield TraceEvent(type="answer_delta", data={"text": tok})

    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": cit.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=cit.bwb_id),
            },
        )
    for cit in FAKE_ANSWER.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": cit.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=cit.ecli),
            },
        )

    out = SynthesizerOut(answer=FAKE_ANSWER)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_fake_synthesizer.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/synthesizer.py tests/agents/test_fake_synthesizer.py
git commit -m "feat: fake synthesizer (streams FAKE_ANSWER + citation_resolved)"
```

---

### Task 8: Validator stub

**Files:**
- Create: `src/jurist/agents/validator_stub.py`
- Test: `tests/agents/test_validator_stub.py`

- [ ] **Step 1: Write failing test `tests/agents/test_validator_stub.py`**

```python
import pytest

from jurist.agents.validator_stub import run
from jurist.fakes import FAKE_ANSWER, FAKE_CASES
from jurist.schemas import ValidatorIn, ValidatorOut


@pytest.mark.asyncio
async def test_validator_stub_always_valid():
    inp = ValidatorIn(
        question="q",
        answer=FAKE_ANSWER,
        cited_articles=[],
        cited_cases=list(FAKE_CASES),
    )
    events = []
    async for ev in run(inp):
        events.append(ev)
    assert events[0].type == "agent_started"
    assert events[-1].type == "agent_finished"
    out = ValidatorOut.model_validate(events[-1].data)
    assert out.valid is True
    assert out.issues == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_validator_stub.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/jurist/agents/validator_stub.py`**

```python
"""M0 validator stub — always returns valid=True.

v2 will check: schema validity, citation resolution, presence of conclusion,
and explicit contradiction detection between statutes and cases.
"""
from __future__ import annotations

from typing import AsyncIterator

from jurist.schemas import TraceEvent, ValidatorIn, ValidatorOut


async def run(input: ValidatorIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    out = ValidatorOut(valid=True, issues=[])
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_validator_stub.py -v`
Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/agents/validator_stub.py tests/agents/test_validator_stub.py
git commit -m "feat: validator stub (always valid in v1; v2 interface shape)"
```

---

### Task 9: SSE helper + event buffer

**Files:**
- Create: `src/jurist/api/__init__.py`
- Create: `src/jurist/api/sse.py`
- Create: `tests/api/__init__.py`
- Test: `tests/api/test_sse.py`

- [ ] **Step 1: Create package markers**

`src/jurist/api/__init__.py`:
```python
```

`tests/api/__init__.py`:
```python
```

- [ ] **Step 2: Write failing test `tests/api/test_sse.py`**

```python
import asyncio

import pytest

from jurist.api.sse import EventBuffer, format_sse
from jurist.schemas import TraceEvent


def test_format_sse_json_payload():
    ev = TraceEvent(type="agent_started", agent="decomposer", run_id="r1", ts="t")
    out = format_sse(ev)
    # SSE frames are "data: <json>\n\n".
    assert out.endswith("\n\n")
    assert out.startswith("data: ")
    body = out[len("data: "):-2]
    assert '"type":"agent_started"' in body


@pytest.mark.asyncio
async def test_buffer_replays_then_streams_live():
    buf = EventBuffer(max_history=10)
    await buf.put(TraceEvent(type="run_started"))
    await buf.put(TraceEvent(type="agent_started", agent="decomposer"))

    collected: list[TraceEvent] = []

    async def consumer():
        async for ev in buf.subscribe():
            collected.append(ev)
            if ev.type == "run_finished":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await buf.put(TraceEvent(type="agent_finished", agent="decomposer"))
    await buf.put(TraceEvent(type="run_finished"))
    await asyncio.wait_for(task, timeout=1.0)

    types = [e.type for e in collected]
    assert types == ["run_started", "agent_started", "agent_finished", "run_finished"]


@pytest.mark.asyncio
async def test_buffer_drops_oldest_when_history_full():
    buf = EventBuffer(max_history=3)
    for i in range(5):
        await buf.put(TraceEvent(type=f"e{i}"))

    collected: list[str] = []

    async def consumer():
        async for ev in buf.subscribe():
            collected.append(ev.type)
            if ev.type == "done":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await buf.put(TraceEvent(type="done"))
    await asyncio.wait_for(task, timeout=1.0)

    # Only last 3 history events + "done" are seen (e2, e3, e4, done).
    assert collected == ["e2", "e3", "e4", "done"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/api/test_sse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.api.sse'`.

- [ ] **Step 4: Implement `src/jurist/api/sse.py`**

The buffer tracks a monotonic `_total_put` counter so a late subscriber knows which events it has missed even after `max_history` has dropped the oldest. Exactly one subscriber per buffer is supported (one SSE stream per question).

```python
"""SSE formatting and per-run event buffer with bounded history + live fan-out."""
from __future__ import annotations

import asyncio
from collections import deque
from typing import AsyncIterator

from jurist.schemas import TraceEvent


def format_sse(event: TraceEvent) -> str:
    """Serialize a TraceEvent as a single SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


class EventBuffer:
    """Bounded per-run event buffer with replay + live streaming.

    - Holds up to `max_history` events so a late subscriber can replay.
    - After the last history event, streams live puts until a terminal event
      (`run_finished` or `run_failed`) is observed, then closes.
    - Exactly one subscriber per buffer is supported.
    """

    _TERMINAL = {"run_finished", "run_failed"}

    def __init__(self, max_history: int = 100) -> None:
        self._history: deque[TraceEvent] = deque(maxlen=max_history)
        self._total_put = 0
        self._new_event = asyncio.Event()
        self._closed = False

    async def put(self, event: TraceEvent) -> None:
        if self._closed:
            return
        self._history.append(event)
        self._total_put += 1
        self._new_event.set()
        if event.type in self._TERMINAL:
            self._closed = True

    async def subscribe(self) -> AsyncIterator[TraceEvent]:
        seen_total = 0
        while True:
            history = list(self._history)
            first_in_history_total = self._total_put - len(history)
            # Start from whichever is later: what we've seen, or the oldest still held.
            start_total = max(seen_total, first_in_history_total)
            start_idx = start_total - first_in_history_total
            for ev in history[start_idx:]:
                yield ev
                start_total += 1
                seen_total = start_total
                if ev.type in self._TERMINAL:
                    return
            if self._closed:
                return
            self._new_event.clear()
            await self._new_event.wait()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_sse.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/api/__init__.py src/jurist/api/sse.py tests/api/__init__.py tests/api/test_sse.py
git commit -m "feat: SSE formatter and bounded event buffer with replay"
```

---

### Task 10: Orchestrator

**Files:**
- Create: `src/jurist/api/orchestrator.py`
- Test: `tests/api/test_orchestrator.py`

- [ ] **Step 1: Write failing test `tests/api/test_orchestrator.py`**

```python
import pytest

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer


@pytest.mark.asyncio
async def test_orchestrator_emits_run_started_and_run_finished():
    buf = EventBuffer()
    await run_question("Mag de huur 15% omhoog?", run_id="run_test", buffer=buf)

    # Consume the whole buffer history.
    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"


@pytest.mark.asyncio
async def test_orchestrator_stamps_run_id_and_agent_on_every_event():
    buf = EventBuffer()
    await run_question("q", run_id="run_test", buffer=buf)
    async for ev in buf.subscribe():
        assert ev.run_id == "run_test"
        assert ev.ts != ""
        if ev.type not in {"run_started", "run_finished", "run_failed"}:
            assert ev.agent != ""


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_expected_order():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf)
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
    await run_question("q", run_id="r", buffer=buf)
    final = None
    async for ev in buf.subscribe():
        if ev.type == "run_finished":
            final = ev
    assert final is not None
    ans = final.data["final_answer"]
    assert "korte_conclusie" in ans
    assert "aanbeveling" in ans
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.api.orchestrator'`.

- [ ] **Step 3: Implement `src/jurist/api/orchestrator.py`**

```python
"""Chains the four fake agents + validator stub; stamps events; emits to a buffer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from jurist.agents import (
    case_retriever,
    decomposer,
    statute_retriever,
    synthesizer,
    validator_stub,
)
from jurist.api.sse import EventBuffer
from jurist.schemas import (
    CaseRetrieverIn,
    CaseRetrieverOut,
    DecomposerIn,
    DecomposerOut,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    StructuredAnswer,
    SynthesizerIn,
    SynthesizerOut,
    TraceEvent,
    ValidatorIn,
    ValidatorOut,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _pump(
    agent_name: str,
    stream: AsyncIterator[TraceEvent],
    run_id: str,
    buffer: EventBuffer,
) -> TraceEvent:
    """Forward every event from `stream` into `buffer`, stamped. Return the final event."""
    final: TraceEvent | None = None
    async for ev in stream:
        ev.agent = agent_name
        ev.run_id = run_id
        ev.ts = _now_iso()
        await buffer.put(ev)
        if ev.type == "agent_finished":
            final = ev
    if final is None:
        raise RuntimeError(f"Agent {agent_name} ended without agent_finished")
    return final


async def run_question(question: str, run_id: str, buffer: EventBuffer) -> None:
    """End-to-end M0 run driven by fake agents. Writes all events to `buffer`."""
    await buffer.put(
        TraceEvent(
            type="run_started",
            run_id=run_id,
            ts=_now_iso(),
            data={"question": question},
        )
    )

    # 1. Decomposer
    dec_final = await _pump(
        "decomposer",
        decomposer.run(DecomposerIn(question=question)),
        run_id,
        buffer,
    )
    decomposer_out = DecomposerOut.model_validate(dec_final.data)

    # 2. Statute retriever
    stat_in = StatuteRetrieverIn(
        sub_questions=decomposer_out.sub_questions,
        concepts=decomposer_out.concepts,
        intent=decomposer_out.intent,
    )
    stat_final = await _pump(
        "statute_retriever",
        statute_retriever.run(stat_in),
        run_id,
        buffer,
    )
    stat_out = StatuteRetrieverOut.model_validate(stat_final.data)

    # 3. Case retriever
    case_in = CaseRetrieverIn(
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

    # 4. Synthesizer
    synth_in = SynthesizerIn(
        question=question,
        cited_articles=stat_out.cited_articles,
        cited_cases=case_out.cited_cases,
    )
    synth_final = await _pump(
        "synthesizer",
        synthesizer.run(synth_in),
        run_id,
        buffer,
    )
    synth_out = SynthesizerOut.model_validate(synth_final.data)

    # 5. Validator stub
    val_in = ValidatorIn(
        question=question,
        answer=synth_out.answer,
        cited_articles=stat_out.cited_articles,
        cited_cases=case_out.cited_cases,
    )
    val_final = await _pump(
        "validator",
        validator_stub.run(val_in),
        run_id,
        buffer,
    )
    _ = ValidatorOut.model_validate(val_final.data)

    await buffer.put(
        TraceEvent(
            type="run_finished",
            run_id=run_id,
            ts=_now_iso(),
            data={"final_answer": synth_out.answer.model_dump()},
        )
    )


__all__ = ["run_question"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_orchestrator.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run the entire backend test suite**

Run: `uv run pytest -v`
Expected: all tests from Tasks 2–10 PASS (approximately 25 tests).

- [ ] **Step 6: Commit**

```bash
git add src/jurist/api/orchestrator.py tests/api/test_orchestrator.py
git commit -m "feat: orchestrator chains fake agents, stamps events, emits to buffer"
```

---

### Task 11: FastAPI app — /ask and /stream

**Files:**
- Create: `src/jurist/config.py`
- Create: `src/jurist/api/app.py`
- Test: `tests/api/test_endpoints.py`

- [ ] **Step 1: Create `src/jurist/config.py`**

```python
"""Minimal settings object; expands in M1+ (model IDs, data paths, etc.)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    max_history_per_run: int = int(os.getenv("JURIST_MAX_HISTORY_PER_RUN", "200"))
    cors_allow_origin: str = os.getenv("JURIST_CORS_ORIGIN", "http://localhost:5173")


settings = Settings()
```

- [ ] **Step 2: Write failing test `tests/api/test_endpoints.py`**

```python
import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from jurist.api.app import app


@pytest.mark.asyncio
async def test_post_ask_returns_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "question_id" in body
        assert body["question_id"].startswith("run_")


@pytest.mark.asyncio
async def test_stream_yields_run_started_through_run_finished():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        qid = resp.json()["question_id"]

        events: list[dict] = []
        async with client.stream("GET", f"/api/stream?question_id={qid}") as s:
            assert s.status_code == 200
            async for line in s.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[len("data: "):])
                events.append(payload)
                if payload["type"] in {"run_finished", "run_failed"}:
                    break

    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert "answer_delta" in types


@pytest.mark.asyncio
async def test_stream_returns_404_for_unknown_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stream?question_id=run_does_not_exist")
        assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/api/test_endpoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jurist.api.app'`.

- [ ] **Step 4: Implement `src/jurist/api/app.py`**

```python
"""FastAPI app: POST /api/ask + GET /api/stream (SSE)."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer, format_sse
from jurist.config import settings

app = FastAPI(title="Jurist", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question_id: str


# In-memory registry of active runs. One buffer per question_id.
_runs: dict[str, EventBuffer] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    question_id = f"run_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=settings.max_history_per_run)
    _runs[question_id] = buf
    task = asyncio.create_task(run_question(req.question, question_id, buf))
    _tasks[question_id] = task
    return AskResponse(question_id=question_id)


@app.get("/api/stream")
async def stream(question_id: str):
    buf = _runs.get(question_id)
    if buf is None:
        raise HTTPException(status_code=404, detail="unknown question_id")

    async def gen():
        async for ev in buf.subscribe():
            yield format_sse(ev)

    return EventSourceResponse(gen())


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_endpoints.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/config.py src/jurist/api/app.py tests/api/test_endpoints.py
git commit -m "feat: POST /api/ask and GET /api/stream (SSE) endpoints"
```

---

### Task 12: API entrypoint

**Files:**
- Create: `src/jurist/api/__main__.py`

- [ ] **Step 1: Implement `src/jurist/api/__main__.py`**

```python
"""`python -m jurist.api` — launches uvicorn with the FastAPI app."""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "jurist.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual smoke test — start the server**

Run: `uv run python -m jurist.api`
Expected console output includes:
```
Uvicorn running on http://127.0.0.1:8000
```
Leave it running in one terminal.

- [ ] **Step 3: Manual smoke test — hit endpoints**

In a second terminal:
```bash
curl -s -X POST http://127.0.0.1:8000/api/ask \
     -H "content-type: application/json" \
     -d '{"question":"Mag de huur 15% omhoog?"}'
```
Expected: `{"question_id":"run_<hex>"}`.

```bash
curl -N "http://127.0.0.1:8000/api/stream?question_id=<paste id from above>"
```
Expected: stream of `data: {...}` SSE frames ending with `"type":"run_finished"`.

- [ ] **Step 4: Stop the server (Ctrl-C) and commit**

```bash
git add src/jurist/api/__main__.py
git commit -m "feat: python -m jurist.api entrypoint (uvicorn)"
```

---

### Task 13: Frontend scaffold

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/tailwind.config.js`
- Create: `web/postcss.config.js`
- Create: `web/index.html`
- Create: `web/src/index.css`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx` (initial placeholder)

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "jurist-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@xyflow/react": "^12.3.5",
    "dagre": "^0.8.5",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.2"
  },
  "devDependencies": {
    "@types/dagre": "^0.7.52",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.5.0",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.6.3",
    "vite": "^5.4.11"
  }
}
```

- [ ] **Step 2: Create `web/vite.config.ts`**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 3: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "useDefineForClassFields": true,
    "allowSyntheticDefaultImports": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create `web/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create `web/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 6: Create `web/postcss.config.js`**

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 7: Create `web/index.html`**

```html
<!doctype html>
<html lang="nl">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Jurist</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Create `web/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; }
body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; }
```

- [ ] **Step 9: Create `web/src/main.tsx`**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import '@xyflow/react/dist/style.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 10: Create initial `web/src/App.tsx`**

```tsx
export default function App() {
  return (
    <div className="h-full p-6">
      <h1 className="text-2xl font-semibold">Jurist (M0 scaffold)</h1>
      <p className="text-gray-600">Components wire up in the next tasks.</p>
    </div>
  );
}
```

- [ ] **Step 11: Install deps**

Run: `cd web && npm install`
Expected: `node_modules/` populated, `package-lock.json` generated.

- [ ] **Step 12: Smoke test — start dev server**

Run: `cd web && npm run dev`
Expected: Vite prints `Local: http://localhost:5173/`. Visiting that URL renders the placeholder heading. Stop the server.

- [ ] **Step 13: Commit**

```bash
git add web/package.json web/package-lock.json web/vite.config.ts web/tsconfig.json \
        web/tsconfig.node.json web/tailwind.config.js web/postcss.config.js \
        web/index.html web/src/main.tsx web/src/App.tsx web/src/index.css
git commit -m "feat: frontend scaffold (Vite, React, Tailwind, xyflow, Zustand)"
```

---

### Task 14: Frontend event types + API client

**Files:**
- Create: `web/src/types/events.ts`
- Create: `web/src/api/ask.ts`
- Create: `web/src/api/sse.ts`

- [ ] **Step 1: Create `web/src/types/events.ts`**

```ts
// Mirror of backend StructuredAnswer + TraceEvent shapes.
// Keep in sync with src/jurist/schemas.py.

export type Intent = 'legality_check' | 'calculation' | 'procedure' | 'other';

export interface WetArtikelCitation {
  bwb_id: string;
  article_label: string;
  quote: string;
  explanation: string;
}

export interface UitspraakCitation {
  ecli: string;
  quote: string;
  explanation: string;
}

export interface StructuredAnswer {
  korte_conclusie: string;
  relevante_wetsartikelen: WetArtikelCitation[];
  vergelijkbare_uitspraken: UitspraakCitation[];
  aanbeveling: string;
}

export type AgentName =
  | 'decomposer'
  | 'statute_retriever'
  | 'case_retriever'
  | 'synthesizer'
  | 'validator'
  | '';

export interface TraceEvent {
  type: string;
  agent: AgentName;
  run_id: string;
  ts: string;
  data: Record<string, unknown>;
}
```

- [ ] **Step 2: Create `web/src/api/ask.ts`**

```ts
export interface AskResponse {
  question_id: string;
}

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    throw new Error(`ask failed: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 3: Create `web/src/api/sse.ts`**

```ts
import type { TraceEvent } from '../types/events';

export interface Subscription {
  close: () => void;
}

export function subscribe(
  questionId: string,
  onEvent: (ev: TraceEvent) => void,
  onError?: (err: Event) => void,
): Subscription {
  const es = new EventSource(`/api/stream?question_id=${encodeURIComponent(questionId)}`);
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as TraceEvent;
      onEvent(ev);
      if (ev.type === 'run_finished' || ev.type === 'run_failed') {
        es.close();
      }
    } catch (e) {
      console.error('bad SSE payload', msg.data, e);
    }
  };
  es.onerror = (err) => {
    if (onError) onError(err);
  };
  return { close: () => es.close() };
}
```

- [ ] **Step 4: Manual smoke test**

No runnable test at this point — but `cd web && npx tsc --noEmit` should produce no errors.
Run: `cd web && npx tsc --noEmit`
Expected: no output (exit 0).

- [ ] **Step 5: Commit**

```bash
git add web/src/types/events.ts web/src/api/ask.ts web/src/api/sse.ts
git commit -m "feat: frontend event types, ask() and subscribe() helpers"
```

---

### Task 15: Zustand run store

**Files:**
- Create: `web/src/state/runStore.ts`

- [ ] **Step 1: Create `web/src/state/runStore.ts`**

```ts
import { create } from 'zustand';
import type { StructuredAnswer, TraceEvent } from '../types/events';

export type NodeState = 'default' | 'current' | 'visited' | 'cited';
export type EdgeState = 'default' | 'traversed';
export type RunStatus = 'idle' | 'running' | 'finished' | 'failed';

export interface CaseHit {
  ecli: string;
  similarity: number;
}

export interface CitationResolution {
  kind: 'artikel' | 'uitspraak';
  id: string;
  resolved_url: string;
}

interface RunState {
  runId: string | null;
  status: RunStatus;
  question: string;

  kgState: Map<string, NodeState>;
  edgeState: Map<string, EdgeState>;

  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];

  start: (runId: string, question: string) => void;
  apply: (ev: TraceEvent) => void;
  reset: () => void;
}

const edgeKey = (from: string, to: string): string => `${from}::${to}`;

export const useRunStore = create<RunState>((set, get) => ({
  runId: null,
  status: 'idle',
  question: '',
  kgState: new Map(),
  edgeState: new Map(),
  traceLog: [],
  thinkingByAgent: {},
  answerText: '',
  finalAnswer: null,
  cases: [],
  resolutions: [],

  start: (runId, question) =>
    set({
      runId,
      question,
      status: 'running',
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
    }),

  reset: () =>
    set({
      runId: null,
      status: 'idle',
      question: '',
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
    }),

  apply: (ev) => {
    const s = get();
    const traceLog = [...s.traceLog, ev];

    switch (ev.type) {
      case 'node_visited': {
        const aid = ev.data.article_id as string;
        const next = new Map(s.kgState);
        // Demote prior "current" to "visited".
        for (const [k, v] of next) {
          if (v === 'current') next.set(k, 'visited');
        }
        next.set(aid, 'current');
        set({ traceLog, kgState: next });
        return;
      }
      case 'edge_traversed': {
        const from = ev.data.from_id as string;
        const to = ev.data.to_id as string;
        const next = new Map(s.edgeState);
        next.set(edgeKey(from, to), 'traversed');
        set({ traceLog, edgeState: next });
        return;
      }
      case 'agent_thinking': {
        const agent = ev.agent;
        const delta = (ev.data.text as string) ?? '';
        set({
          traceLog,
          thinkingByAgent: {
            ...s.thinkingByAgent,
            [agent]: (s.thinkingByAgent[agent] ?? '') + delta,
          },
        });
        return;
      }
      case 'answer_delta': {
        set({ traceLog, answerText: s.answerText + ((ev.data.text as string) ?? '') });
        return;
      }
      case 'case_found': {
        set({
          traceLog,
          cases: [
            ...s.cases,
            {
              ecli: ev.data.ecli as string,
              similarity: ev.data.similarity as number,
            },
          ],
        });
        return;
      }
      case 'citation_resolved': {
        set({
          traceLog,
          resolutions: [
            ...s.resolutions,
            {
              kind: ev.data.kind as 'artikel' | 'uitspraak',
              id: ev.data.id as string,
              resolved_url: ev.data.resolved_url as string,
            },
          ],
        });
        return;
      }
      case 'run_finished': {
        // Demote any "current" to "cited" on the retriever's selected set.
        const next = new Map(s.kgState);
        for (const [k, v] of next) {
          if (v === 'current' || v === 'visited') next.set(k, 'cited');
        }
        const finalAnswer = (ev.data.final_answer as StructuredAnswer) ?? null;
        set({ traceLog, kgState: next, status: 'finished', finalAnswer });
        return;
      }
      case 'run_failed': {
        set({ traceLog, status: 'failed' });
        return;
      }
      default: {
        set({ traceLog });
      }
    }
  },
}));

export const edgeStateKey = edgeKey;
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/state/runStore.ts
git commit -m "feat: Zustand runStore — reducer for every TraceEvent type"
```

---

### Task 16: CitationLink component

**Files:**
- Create: `web/src/components/CitationLink.tsx`

- [ ] **Step 1: Implement `web/src/components/CitationLink.tsx`**

```tsx
import { useRunStore } from '../state/runStore';

interface Props {
  kind: 'artikel' | 'uitspraak';
  id: string;
  children: React.ReactNode;
}

export default function CitationLink({ kind, id, children }: Props) {
  const resolved = useRunStore((s) => s.resolutions.find((r) => r.kind === kind && r.id === id));
  if (!resolved) {
    return <span className="text-gray-500 italic">{children}</span>;
  }
  return (
    <a
      href={resolved.resolved_url}
      target="_blank"
      rel="noreferrer"
      className="text-blue-700 underline hover:text-blue-900"
    >
      {children}
    </a>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/CitationLink.tsx
git commit -m "feat: CitationLink component (opens resolved URL in new tab)"
```

---

### Task 17: KGPanel (React Flow)

**Files:**
- Create: `web/src/components/KGPanel.tsx`

- [ ] **Step 1: Implement `web/src/components/KGPanel.tsx`**

This panel needs the list of nodes/edges to render — for M0 we fetch it from a new backend endpoint `GET /api/kg` that returns `FAKE_KG`. Add a small backend route first.

**Sub-step 1a:** Add to `src/jurist/api/app.py` (after the `/api/health` handler):

```python
from jurist.fakes import FAKE_KG


@app.get("/api/kg")
async def kg() -> dict:
    nodes, edges = FAKE_KG
    return {
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }
```

**Sub-step 1b:** Add to `src/jurist/api/app.py` import block:
the `from jurist.fakes import FAKE_KG` line above should land at the top of the module alongside other imports (move it if your editor didn't).

**Sub-step 1c:** Write the component in `web/src/components/KGPanel.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import dagre from 'dagre';
import { useRunStore } from '../state/runStore';

interface KgArticle {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
  body_text: string;
  outgoing_refs: string[];
}
interface KgEdge {
  from_id: string;
  to_id: string;
  kind: 'explicit' | 'regex';
}

const NODE_W = 220;
const NODE_H = 64;

function layout(nodes: KgArticle[], edges: KgEdge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 60 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.article_id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.from_id, e.to_id);
  dagre.layout(g);

  const rfNodes: Node[] = nodes.map((n) => {
    const pos = g.node(n.article_id);
    return {
      id: n.article_id,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: { label: n.label, title: n.title },
      type: 'default',
      style: { width: NODE_W, height: NODE_H, padding: 8, fontSize: 12 },
    };
  });
  const rfEdges: Edge[] = edges.map((e) => ({
    id: `${e.from_id}__${e.to_id}`,
    source: e.from_id,
    target: e.to_id,
    animated: false,
  }));
  return { nodes: rfNodes, edges: rfEdges };
}

const stateStyle = {
  default: { background: '#fff', border: '1px solid #d1d5db' },
  current: { background: '#fde68a', border: '2px solid #d97706' },
  visited: { background: '#e5e7eb', border: '1px solid #6b7280' },
  cited: { background: '#bbf7d0', border: '2px solid #047857' },
} as const;

export default function KGPanel() {
  const [base, setBase] = useState<{ nodes: Node[]; edges: Edge[] } | null>(null);
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);

  useEffect(() => {
    void fetch('/api/kg')
      .then((r) => r.json())
      .then((d: { nodes: KgArticle[]; edges: KgEdge[] }) => setBase(layout(d.nodes, d.edges)));
  }, []);

  const rfNodes = useMemo(() => {
    if (!base) return [];
    return base.nodes.map((n) => {
      const st = kgState.get(n.id) ?? 'default';
      return { ...n, style: { ...(n.style as object), ...stateStyle[st], transition: 'all 300ms' } };
    });
  }, [base, kgState]);

  const rfEdges = useMemo(() => {
    if (!base) return [];
    return base.edges.map((e) => {
      const traversed = edgeState.get(`${e.source}::${e.target}`) === 'traversed';
      return {
        ...e,
        animated: traversed,
        style: { stroke: traversed ? '#047857' : '#9ca3af', strokeWidth: traversed ? 2 : 1 },
      };
    });
  }, [base, edgeState]);

  if (!base) {
    return <div className="p-4 text-gray-500">Loading KG…</div>;
  }
  return (
    <div className="h-full w-full border rounded">
      <ReactFlow nodes={rfNodes} edges={rfEdges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/KGPanel.tsx src/jurist/api/app.py
git commit -m "feat: KGPanel renders FAKE_KG with state-driven styling; add /api/kg"
```

---

### Task 18: TracePanel

**Files:**
- Create: `web/src/components/TracePanel.tsx`

- [ ] **Step 1: Implement `web/src/components/TracePanel.tsx`**

```tsx
import { useRunStore } from '../state/runStore';
import type { TraceEvent } from '../types/events';

const AGENT_ORDER = [
  'decomposer',
  'statute_retriever',
  'case_retriever',
  'synthesizer',
  'validator',
] as const;
type AgentName = (typeof AGENT_ORDER)[number];

function eventLine(ev: TraceEvent): string | null {
  switch (ev.type) {
    case 'agent_started':
      return 'started';
    case 'agent_finished':
      return 'finished';
    case 'tool_call_started':
      return `→ ${ev.data.tool}(${JSON.stringify(ev.data.args)})`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary}`;
    case 'node_visited':
      return `visited ${ev.data.article_id}`;
    case 'edge_traversed':
      return `traversed ${ev.data.from_id} → ${ev.data.to_id}`;
    case 'search_started':
      return 'vector search';
    case 'case_found':
      return `case ${ev.data.ecli} (sim=${(ev.data.similarity as number).toFixed(2)})`;
    case 'reranked':
      return `kept ${(ev.data.kept as string[]).join(', ')}`;
    case 'answer_delta':
      // Rendered in the AnswerPanel, not as a trace line.
      return null;
    case 'citation_resolved':
      return `resolved ${ev.data.kind} ${ev.data.id}`;
    default:
      return ev.type;
  }
}

export default function TracePanel() {
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);

  const byAgent: Record<string, TraceEvent[]> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

  return (
    <div className="h-full w-full overflow-y-auto border rounded p-3 text-sm">
      {AGENT_ORDER.map((agent: AgentName) => {
        const events = byAgent[agent] ?? [];
        if (events.length === 0) return null;
        return (
          <div key={agent} className="mb-4">
            <div className="font-semibold text-gray-800">{agent}</div>
            {thinkingByAgent[agent] && (
              <div className="mt-1 pl-3 border-l-2 border-amber-400 text-amber-900 whitespace-pre-wrap">
                {thinkingByAgent[agent]}
              </div>
            )}
            <ul className="mt-1 pl-3 space-y-0.5 font-mono text-xs text-gray-700">
              {events.map((ev, i) => {
                const line = eventLine(ev);
                if (line === null) return null;
                return <li key={i}>{line}</li>;
              })}
            </ul>
          </div>
        );
      })}
      {traceLog.length === 0 && (
        <div className="text-gray-500">Waiting for a question…</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/TracePanel.tsx
git commit -m "feat: TracePanel — per-agent streamed trace with thinking deltas"
```

---

### Task 19: AnswerPanel

**Files:**
- Create: `web/src/components/AnswerPanel.tsx`

- [ ] **Step 1: Implement `web/src/components/AnswerPanel.tsx`**

```tsx
import { useRunStore } from '../state/runStore';
import CitationLink from './CitationLink';

export default function AnswerPanel() {
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const streaming = useRunStore((s) => s.answerText);
  const status = useRunStore((s) => s.status);

  if (status === 'idle') {
    return (
      <div className="p-4 border rounded text-gray-500">
        Answer appears here after you ask a question.
      </div>
    );
  }

  if (!finalAnswer) {
    return (
      <div className="p-4 border rounded">
        <div className="text-sm text-gray-500 mb-2">Synthesizer is streaming…</div>
        <p className="whitespace-pre-wrap">{streaming}</p>
      </div>
    );
  }

  return (
    <div className="p-4 border rounded space-y-4">
      <section>
        <h2 className="font-semibold text-lg">Korte conclusie</h2>
        <p>{finalAnswer.korte_conclusie}</p>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Relevante wetsartikelen</h2>
        <ul className="list-disc list-inside space-y-2">
          {finalAnswer.relevante_wetsartikelen.map((c, i) => (
            <li key={`${c.bwb_id}-${i}`}>
              <CitationLink kind="artikel" id={c.bwb_id}>
                {c.article_label}
              </CitationLink>{' '}
              — <em>"{c.quote}"</em> {c.explanation}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Vergelijkbare uitspraken</h2>
        <ul className="list-disc list-inside space-y-2">
          {finalAnswer.vergelijkbare_uitspraken.map((c, i) => (
            <li key={`${c.ecli}-${i}`}>
              <CitationLink kind="uitspraak" id={c.ecli}>
                {c.ecli}
              </CitationLink>{' '}
              — <em>"{c.quote}"</em> {c.explanation}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Aanbeveling</h2>
        <p>{finalAnswer.aanbeveling}</p>
      </section>

      <p className="text-xs text-gray-400 pt-4 border-t">
        Demo. Geen juridisch advies.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/AnswerPanel.tsx
git commit -m "feat: AnswerPanel — structured answer with CitationLinks + streaming fallback"
```

---

### Task 20: Wire App.tsx

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Replace `web/src/App.tsx` with the full shell**

```tsx
import { useState } from 'react';
import AnswerPanel from './components/AnswerPanel';
import KGPanel from './components/KGPanel';
import TracePanel from './components/TracePanel';
import { ask } from './api/ask';
import { subscribe } from './api/sse';
import { useRunStore } from './state/runStore';

const LOCKED_QUESTION =
  'Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?';

export default function App() {
  const [input, setInput] = useState(LOCKED_QUESTION);
  const status = useRunStore((s) => s.status);
  const start = useRunStore((s) => s.start);
  const apply = useRunStore((s) => s.apply);

  const submit = async () => {
    const q = input.trim();
    if (!q) return;
    const { question_id } = await ask(q);
    start(question_id, q);
    subscribe(question_id, (ev) => apply(ev));
  };

  return (
    <div className="h-full flex flex-col">
      <header className="flex gap-2 items-center p-3 border-b">
        <h1 className="font-semibold text-lg">Jurist</h1>
        <input
          className="flex-1 border rounded px-3 py-2"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={status === 'running'}
        />
        <button
          className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-gray-400"
          onClick={() => void submit()}
          disabled={status === 'running'}
        >
          {status === 'running' ? 'Running…' : 'Ask'}
        </button>
      </header>

      <main className="grid grid-cols-2 gap-3 p-3 flex-1 min-h-0">
        <KGPanel />
        <TracePanel />
      </main>

      <section className="p-3 border-t max-h-96 overflow-y-auto">
        <AnswerPanel />
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add web/src/App.tsx
git commit -m "feat: App.tsx shell wires KG/Trace/Answer panels + ask() submit"
```

---

### Task 21: Backend + frontend end-to-end manual verification

This task is the M0 acceptance check. No code changes.

- [ ] **Step 1: Run full backend test suite**

Run: `uv run pytest -v`
Expected: all tests PASS. Count should be ~27–30 tests.

- [ ] **Step 2: Typecheck frontend**

Run: `cd web && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Start backend**

In a terminal: `uv run python -m jurist.api`
Expected: uvicorn listening on `http://127.0.0.1:8000`. Leave it running.

- [ ] **Step 4: Start frontend**

In another terminal: `cd web && npm run dev`
Expected: Vite on `http://localhost:5173`.

- [ ] **Step 5: Browser walk-through**

Open `http://localhost:5173`. Verify:
- The KG panel renders the 9 fake articles as nodes with cross-reference edges, laid out left-to-right via dagre.
- The trace panel shows "Waiting for a question…".
- The answer panel shows the idle placeholder.
- The question input is pre-filled with the locked demo question.

Click **Ask**. Verify, in order:
- `decomposer` section appears in the trace panel with streamed Dutch thinking text.
- `statute_retriever` section appears; one node at a time turns amber (`current`), prior ones go gray (`visited`); edges connecting consecutive visits turn green and animate.
- `case_retriever` section appears; three cases listed with ECLI + similarity.
- `synthesizer` section appears; the answer panel transitions from the streaming text view to the structured view with four subsections.
- Citations in the answer are blue underlined links; clicking each opens a new tab to `wetten.overheid.nl/...` or `uitspraken.rechtspraak.nl/...`.
- `validator` section appears with `started` / `finished`.
- All `visited`/`current` nodes settle into green (`cited`) after `run_finished`.
- The **Ask** button re-enables.

- [ ] **Step 6: Record any issues**

If anything misbehaves, open a task in the M1 plan as a carry-over. If blocking (e.g., stream never starts), halt and fix before claiming M0 done.

- [ ] **Step 7: Tag the milestone**

```bash
git tag -a m0-skeleton -m "M0 complete: skeleton with fakes runs end-to-end"
```

---

## Self-review

**Spec coverage.** Every M0 acceptance criterion in the design spec's section 11 (M0) is covered:
- FastAPI server on :8000 with `/api/ask` and `/api/stream` — Tasks 11, 12.
- Vite dev server on :5173 proxying to :8000 — Task 13.
- Hardcoded run emits all expected event types — Tasks 4–8, 10.
- KGPanel animates, TracePanel renders in order, AnswerPanel renders structured answer with clickable citations — Tasks 16–20.
- Zero LLM calls, zero data-source dependencies — confirmed; no `anthropic`, `lancedb`, `lxml`, `sentence-transformers` imported anywhere in M0.

**Event type coverage** against spec section 6.3: `run_started`, `agent_started`, `agent_thinking`, `tool_call_started`, `tool_call_completed`, `node_visited`, `edge_traversed`, `search_started`, `case_found`, `reranked`, `answer_delta`, `citation_resolved`, `agent_finished`, `run_finished` — all emitted by the fake pipeline and handled by `runStore.apply`. `run_failed` is wired in the store reducer but not emitted by fakes (it's a real-agent path for M4 grounding failures).

**Type consistency.** `article_id`, `bwb_id`, `CitedArticle.body_text`, `CitedCase.ecli` used identically across schemas, fakes, fake agents, and frontend types. `FAKE_VISIT_PATH` drives both the test assertion and the statute retriever's walk — no duplication.

**Placeholder scan.** No "TBD", "TODO", or "implement later" in any step. Every step has either real code, a real command with expected output, or a concrete manual-verification criterion.

---

## What's next (preview, not this plan's scope)

Once M0 is tagged and pushed, subsequent plans will land in `docs/superpowers/plans/` one at a time:

- **M1 plan** — statute ingestion (BWB XML → `data/kg/huurrecht.json`) + KG loaded into the real `KnowledgeGraph` interface + KGPanel fed from real data instead of `FAKE_KG`.
- **M2 plan** — real statute retriever (Claude Sonnet tool-use loop; replaces fake agent).
- **M3 plan** — case law ingestion (rechtspraak XML → bge-m3 → LanceDB) + real case retriever.
- **M4 plan** — real decomposer + real synthesizer with closed-set citation grounding.
- **M5 plan** — error-path polish, README, full acceptance.

Each subsequent plan will follow the same TDD + commit-per-task cadence.
