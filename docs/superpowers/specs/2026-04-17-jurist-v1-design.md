# Jurist v1 — Design

**Date:** 2026-04-17
**Status:** Approved. Implementation not yet started.
**Target:** Live walkthrough for a DAS AI-engineer interview.

---

## 1. Context and goals

**What this is.** A multi-agent demo system that answers one Dutch huurrecht question with grounded citations from real Dutch legal sources (wetten.overheid.nl, rechtspraak.nl). It is a portfolio artifact, not production software.

**The locked demo question:** *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*

**Success on v1.** From a clean `uv sync` + `npm install`, starting `python -m jurist.api` and `npm run dev`, a user submits the locked question and sees, in order:

1. The KG panel rendering real huurrecht articles as nodes and real cross-references as edges.
2. The decomposer streaming its reasoning into the trace panel.
3. The statute retriever running a real Claude tool-use loop — KG nodes light up as articles are visited (at minimum `art. 7:248 BW`), edges animate as cross-references are followed.
4. The case retriever returning top-3 similar rechtspraak with real ECLIs, real similarity scores, and Haiku-generated reason strings.
5. The synthesizer producing a structured Dutch answer with inline clickable citations that each resolve to the real source document.
6. No hallucinated BWB IDs. No hallucinated ECLIs.

Latency is not a hard cap. Target: under ~60 s end-to-end. Hard limit: whatever does not collapse the demo narrative.

## 2. Scope

**In.** Huurrecht only (Boek 7 Titel 4 BW + Uitvoeringswet huurprijzen woonruimte + Besluit huurprijzen woonruimte). Four live agents (decomposer, statute retriever, case retriever, synthesizer) plus a stubbed validator with realistic interface shape. Real KG from BWB XML. Real vector store of ~300 huurrecht uitspraken. Two-panel streaming frontend. Local development only.

**Out.** Other rechtsgebieden. Real validator. Live KG maintenance (the KG is generated offline; no "KG maintainer" agent exists or is implied). User accounts, persistence, query history. Evaluation harness. Deployment. Multi-question UX.

## 3. Architecture

### 3.1 Pipeline

```
POST /ask {question}
    → orchestrator allocates question_id, spawns async run
    ← {question_id}
GET  /stream?question_id=...  (Server-Sent Events)

  Decomposer           (Claude Haiku, forced tool schema for structured output)
      → DecomposerOut
  StatuteRetriever     (Claude Sonnet, tool-use loop, max 15 iterations)
      → StatuteRetrieverOut
  CaseRetriever        (bge-m3 embedding + LanceDB top-K + Haiku rerank)
      → CaseRetrieverOut
  Synthesizer          (Claude Sonnet, closed-set citation tool schema)
      → SynthesizerOut
  Validator (stub)     (no LLM; returns valid=true in v1)
      → ValidatorOut

  run_finished (final answer + full trace available for replay)
```

### 3.2 Sequencing

Sequential across agents. Within the statute retriever loop, Claude's parallel tool-use is accepted; the frontend renders each concurrent tool call live.

### 3.3 Agent interface

Every agent is an async generator with a uniform shape:

```python
async def run(input: InputModel) -> AsyncIterator[TraceEvent]:
    ...  # the final yielded event carries the typed output in its .payload
```

The orchestrator chains them, stamping each event with `run_id`, `ts`, and `agent` before it leaves the process.

## 4. Tech stack (locked)

| Layer | Choice | Why |
| --- | --- | --- |
| Python | 3.11+ | Anthropic SDK, `lxml`, `sentence-transformers` work cleanly on Windows. |
| Package manager | `uv` | Fast, correct lockfile, single-call install on Windows. |
| Web framework | FastAPI + Uvicorn | Native async; SSE is trivial. |
| LLM provider | Anthropic, `anthropic` Python SDK | Tool use, streaming, prompt caching — native. No `claude -p`. |
| Decomposer model | `claude-haiku-4-5-20251001` | Small structured-output task. |
| Statute retriever model | `claude-sonnet-4-6` | Good tool-use reasoning; cheaper than Opus across a 15-iter loop. |
| Case rerank model | `claude-haiku-4-5-20251001` | 3-of-20 rerank — small, cheap, fast. |
| Synthesizer model | `claude-sonnet-4-6` | Dutch structured generation with closed-set citations. |
| Prompt caching | Enabled | System prompts + KG article catalog are stable across the retriever loop. |
| Embeddings | `BAAI/bge-m3` via `sentence-transformers` (local) | Single-vendor footprint (Anthropic is the only remote dependency); strong multilingual; works offline. |
| Vector store | LanceDB (embedded) | Local files, metadata filters, no container. |
| Knowledge graph | NetworkX DiGraph, loaded from `data/kg/huurrecht.json`, behind a `KnowledgeGraph` Protocol | ~100 nodes does not justify a graph DB engine. Protocol preserves a Neo4j swap path. |
| Frontend | React + TypeScript + Vite | |
| KG viz | React Flow | Native fit for node/edge state animation; healthy ecosystem. |
| Styling | Tailwind, default palette | "Ship ugly" — polish is M5. |
| State | Zustand store keyed by `run_id`; React Query for non-stream server state | No Redux. |

No agent framework. No Docker, no `docker-compose.yml` in v1.

## 5. Agent contracts

### 5.1 Decomposer

**Purpose.** Break the user question into sub-questions and legal concepts; classify intent.

**Input.**
```python
class DecomposerIn(BaseModel):
    question: str
```

**Output.**
```python
class DecomposerOut(BaseModel):
    sub_questions: list[str]                                          # 1–5
    concepts: list[str]                                               # Dutch terms: "huurverhoging", "geliberaliseerd", ...
    intent: Literal["legality_check", "calculation", "procedure", "other"]
```

**Implementation.** Single Anthropic call with a forced tool `emit_decomposition` used as a structured-output schema. Haiku. System prompt marked cacheable.

**Events.**
- `agent_started { agent: "decomposer" }`
- `agent_thinking { text }` (deltas)
- `agent_finished { agent, payload: DecomposerOut }`

### 5.2 StatuteRetriever

**Purpose.** Traverse the huurrecht KG via LLM-driven tool use and return the set of relevant articles with reasoning.

**Input.**
```python
class StatuteRetrieverIn(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: str
```

**Output.**
```python
class CitedArticle(BaseModel):
    bwb_id: str                  # "BWBR0005290"
    article_id: str              # "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"
    article_label: str           # "Boek 7, Artikel 248"
    body_text: str               # matches ArticleNode.body_text from the KG
    reason: str                  # model's justification for inclusion

class StatuteRetrieverOut(BaseModel):
    cited_articles: list[CitedArticle]
```

The traversal path is reconstructable from the event log (`node_visited` / `edge_traversed` in order) and is not duplicated on each cited article.

**Tools exposed to the LLM.**

| Tool | Signature | Returns |
| --- | --- | --- |
| `search_articles` | `(query: str, top_k: int = 5)` | list of `{article_id, label, title, snippet}` — hybrid lexical (BM25-ish) + vector over article text. |
| `get_article` | `(article_id: str)` | `{article_id, label, title, full_text, outgoing_refs: list[article_id]}`. |
| `follow_cross_ref` | `(from_id: str, to_id: str)` | same as `get_article(to_id)`, but emits an `edge_traversed` event for the frontend. |
| `done` | `(selected_ids: list[str], reasoning: str)` | terminates the loop. |

**Guardrails.**
- **Max iterations:** 15. If exceeded without `done`, orchestrator coerces `done` using the articles visited so far (preferring those touched by `get_article` / `follow_cross_ref` over those merely surfaced by `search_articles`).
- **Duplicate-call detector:** if the same tool is called with the same args twice consecutively, the orchestrator inserts a `tool_result` with an advisory message pointing the model forward.
- **Tool errors** are returned as `tool_result` with `is_error=true` — the model sees and can recover.

**Events.**
- `agent_started`
- `agent_thinking { text }`
- `tool_call_started { tool, args }`
- `tool_call_completed { tool, args, result_summary }`
- `node_visited { article_id }` — emitted alongside `get_article` / `follow_cross_ref`
- `edge_traversed { from_id, to_id }` — emitted alongside `follow_cross_ref`
- `agent_finished { payload: StatuteRetrieverOut }`

**Prompt caching.** System prompt + the full KG article catalog (`[article_id, label, title, ≤200-char summary]` for all articles, ~100 rows) are marked as a single cache block. This lets the model pick seeds without always issuing an initial `search_articles` call.

### 5.3 CaseRetriever

**Purpose.** Return top-3 relevant huurrecht uitspraken, each with a natural-language reason.

**Input.**
```python
class CaseRetrieverIn(BaseModel):
    sub_questions: list[str]
    statute_context: list[CitedArticle]
```

**Output.**
```python
class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str                    # ISO 8601
    snippet: str
    similarity: float
    reason: str                  # from the Haiku rerank pass
    url: str                     # uitspraken.rechtspraak.nl/...

class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]
```

**Implementation.**
1. Embed the concatenated `sub_questions` with bge-m3; normalize to unit length.
2. LanceDB cosine top-20 with filter `rechtsgebied == "Huurrecht"`.
3. Deduplicate to one chunk per ECLI (keep the highest-similarity chunk).
4. Haiku rerank: prompt includes the statute context (titles + one-line explanations) and the 20 candidate snippets; returns top-3 as `[{ecli, reason}]` via a forced tool schema.
5. Return the top-3 in score order, reason strings attached.

**Events.** `agent_started`, `search_started`, `case_found { ecli, similarity }` (one per result), `reranked { kept: [ecli, ...] }`, `agent_finished`.

### 5.4 Synthesizer

**Purpose.** Produce the final structured Dutch answer with **closed-set** citations.

**Input.**
```python
class SynthesizerIn(BaseModel):
    question: str
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]
```

**Output.**
```python
class WetArtikelCitation(BaseModel):
    bwb_id: str                  # per-request Literal over cited_articles
    article_label: str
    quote: str                   # verbatim excerpt from the article text
    explanation: str

class UitspraakCitation(BaseModel):
    ecli: str                    # per-request Literal over cited_cases
    quote: str
    explanation: str

class StructuredAnswer(BaseModel):
    korte_conclusie: str
    relevante_wetsartikelen: list[WetArtikelCitation]
    vergelijkbare_uitspraken: list[UitspraakCitation]
    aanbeveling: str

class SynthesizerOut(BaseModel):
    answer: StructuredAnswer
```

**Grounding mechanism.**
- The Anthropic tool schema for synthesis is built per-request with `bwb_id` typed as `Literal[<exact retrieved ids>]` and `ecli` typed as `Literal[<exact retrieved eclis>]`. Tool-schema validation rejects generations that do not match.
- After generation, every citation is resolved against the KG / vector store to confirm both the ID exists and the `quote` appears in the source text.
- On resolution failure: **one** regeneration attempt is made, with an added instruction listing the valid IDs and any quotes that failed lookup. If still failing, the run emits `run_failed { reason: "citation_grounding" }` and the UI renders a visible error. No silent fallback path.

**Events.** `agent_started`, `answer_delta { text }`, `citation_resolved { kind, id, resolved_url }` (one per citation once resolved), `agent_finished`.

### 5.5 Validator (stub)

**Purpose.** Placeholder boundary in the pipeline; always returns valid in v1.

**Input.**
```python
class ValidatorIn(BaseModel):
    question: str
    answer: StructuredAnswer
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]
```

**Output.**
```python
class ValidatorOut(BaseModel):
    valid: bool                  # always True in v1
    issues: list[str]            # always empty in v1
```

**Implementation.** No LLM call. Returns `ValidatorOut(valid=True, issues=[])`. The module's docstring names the intended v2 checks: schema validity, citation resolution against a fresh index, presence of `korte_conclusie` and `aanbeveling`, explicit contradiction detection between articles and cases.

**Events.** `agent_started`, `agent_finished`.

## 6. Streaming protocol

### 6.1 Transport

One SSE stream per question.

- `POST /ask {question}` returns `{question_id}` immediately and spawns the run as a background task.
- Frontend opens `GET /stream?question_id=...` right after; the backend writes a short ring buffer (≤100 events) until the stream is opened, then flushes and streams live.
- On client disconnect, the orchestrator completes the run in the background and holds the buffered events for 60 s for reconnect-replay with the same `question_id`.

### 6.2 Envelope

```json
{
  "ts": "2026-04-17T14:22:10.123Z",
  "run_id": "run_abc",
  "agent": "statute_retriever",
  "type": "node_visited",
  "data": { "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248" }
}
```

### 6.3 Event types (authoritative)

| Type | From | Data |
| --- | --- | --- |
| `run_started` | orchestrator | `{ question }` |
| `agent_started` | any agent | `{}` |
| `agent_thinking` | any agent | `{ text }` (delta) |
| `tool_call_started` | statute_retriever | `{ tool, args }` |
| `tool_call_completed` | statute_retriever | `{ tool, args, result_summary }` |
| `node_visited` | statute_retriever | `{ article_id }` |
| `edge_traversed` | statute_retriever | `{ from_id, to_id }` |
| `search_started` | case_retriever | `{}` |
| `case_found` | case_retriever | `{ ecli, similarity }` |
| `reranked` | case_retriever | `{ kept: [ecli, ...] }` |
| `answer_delta` | synthesizer | `{ text }` |
| `citation_resolved` | synthesizer | `{ kind, id, resolved_url }` |
| `agent_finished` | any agent | `{ payload }` — the agent's typed output |
| `run_finished` | orchestrator | `{ final_answer: StructuredAnswer }` |
| `run_failed` | orchestrator | `{ reason, detail }` |

## 7. Data model

### 7.1 Article (KG node)

```python
class ArticleNode(BaseModel):
    article_id: str              # "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"
    bwb_id: str                  # "BWBR0005290"
    label: str                   # "Boek 7, Artikel 248"
    title: str                   # header text, if present
    body_text: str
    outgoing_refs: list[str]     # destination article_ids
```

### 7.2 Cross-reference (KG edge)

```python
class ArticleEdge(BaseModel):
    from_id: str
    to_id: str
    kind: Literal["explicit", "regex"]   # provenance
    context: str | None                   # surrounding sentence, for the "regex" kind
```

### 7.3 KG snapshot

`data/kg/huurrecht.json`:
```json
{
  "generated_at": "2026-04-17T10:00:00Z",
  "source_versions": { "BWBR0005290": "2026-01-01" },
  "nodes": [ ArticleNode, ... ],
  "edges": [ ArticleEdge, ... ]
}
```

### 7.4 Case chunk (LanceDB row)

```python
class CaseChunk(BaseModel):
    ecli: str
    court: str
    date: str
    rechtsgebied: str
    chunk_idx: int
    text: str
    embedding: list[float]       # 1024-dim (bge-m3)
    url: str
```

## 8. Data ingestion

### 8.1 Statutes — `python -m jurist.ingest.statutes`

**Scope (allowlist).** The full allowlist lives in `src/jurist/ingest/allowlist.py`; it is the single point of scope control.

| BWB ID | Name |
| --- | --- |
| `BWBR0005290` | Burgerlijk Wetboek Boek 7 (filtered to Titel 4 — Huur) |
| `BWBR0002888` | Uitvoeringswet huurprijzen woonruimte |
| `BWBR0003402` | Besluit huurprijzen woonruimte (puntenstelsel) |

**Steps.**
1. Fetch BWB XML from the wetten.overheid.nl open-data endpoint per BWB ID.
2. Parse with `lxml`. Walk `<boek>` → `<titel>` → `<afdeling>` → `<artikel>`. Extract `article_id`, `bwb_id`, `label`, `title`, `body_text`.
3. Cross-references: explicit `<verwijzing>` elements → `edge(kind="explicit")`. Regex pass over body_text for `artikel\s+\d+[a-z]?(?:,\s+(?:eerste|tweede|derde|vierde|vijfde|zesde|zevende|achtste|negende|tiende|\d+e)\s+lid)?` patterns → `edge(kind="regex")`. Deduplicate by `(from_id, to_id)`.
4. Emit `data/kg/huurrecht.json` and `data/articles/{article_id}.md` for linking and debug.
5. Idempotent: re-runs compare `source_versions`; unchanged sources are skipped. `--refresh` forces.

### 8.2 Case law — `python -m jurist.ingest.caselaw`

**Scope.** rechtspraak.nl open-data ECLI search:
- `rechtsgebied = "Huurrecht"`
- `instantie ∈ {Huurcommissie, Rechtbank, Gerechtshof}`
- `datum` descending
- first N (default 300; `--limit` overrides)

**Steps.**
1. Query the ECLI search API; collect ECLIs.
2. For each ECLI, fetch the open-data XML; extract `ecli`, `date`, `court`, `rechtsgebied`, `tekst`, `url`.
3. Chunk `tekst` into ~500-token chunks with 50-token overlap using an in-house paragraph-aware recursive splitter (`src/jurist/ingest/splitter.py`; ~30 lines, stdlib-only). Respects paragraph boundaries first, then sentence, then character. No LangChain dependency — strict adherence to the "no agent framework" non-goal.
4. Embed each chunk with bge-m3 (`sentence_transformers.SentenceTransformer("BAAI/bge-m3")`). Normalize.
5. Insert into LanceDB at `data/lancedb/cases.lance`.
6. Dump `data/cases/{ecli}.md` for linking and debug.
7. Idempotent: skip ECLIs already present unless `--refresh`.

## 9. Frontend

### 9.1 Layout

```
┌──────────────────────────────────────┐
│  [question input]            [ask]   │
├─────────────────┬────────────────────┤
│                 │                    │
│   KG panel      │   Trace panel      │
│   (React Flow)  │   (agent stream)   │
│                 │                    │
├─────────────────┴────────────────────┤
│   Answer panel (structured Dutch)    │
└──────────────────────────────────────┘
```

### 9.2 Components

- **`App.tsx`** — shell, layout, SSE subscription management, question submit.
- **`KGPanel.tsx`** — React Flow canvas. Node state ∈ `{default, current, visited, cited}`. Edge state ∈ `{default, traversed}`. Auto-layout via `dagre` on KG load.
- **`TracePanel.tsx`** — per-agent sections; each event rendered as a line with agent name, time, summary. `tool_call_*` groups expand/collapse. `agent_thinking` deltas append into a single streamed block per agent.
- **`AnswerPanel.tsx`** — renders `StructuredAnswer` with four subsections; inline `CitationLink` components.
- **`CitationLink.tsx`** — on click, opens `resolved_url` in a new tab.
- **`runStore.ts`** — Zustand store keyed by `run_id`. Reducer consumes `TraceEvent` and updates `kgState: Map<article_id, NodeState>`, `edgeState: Map<edge_key, EdgeState>`, `traceLog: TraceEvent[]`, `answer: Partial<StructuredAnswer>`, `status ∈ {idle, running, finished, failed}`.

### 9.3 Animation timing

Node state transitions: Tailwind transition, ~300 ms. Edge traversals: SVG `stroke-dashoffset` over ~400 ms. Events are not throttled — the server emits at real pace and the UI reflects live.

## 10. Repo layout

```
jurist/
├── pyproject.toml
├── .gitignore
├── README.md
├── .env.example                            # ANTHROPIC_API_KEY=
├── docs/
│   └── superpowers/specs/
│       └── 2026-04-17-jurist-v1-design.md  # this file
├── data/                                   # generated; gitignored
│   ├── kg/huurrecht.json
│   ├── articles/*.md
│   ├── cases/*.md
│   └── lancedb/
├── src/jurist/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py                          # all Pydantic types + TraceEvent + AgentProtocol
│   ├── kg/
│   │   ├── __init__.py
│   │   ├── interface.py                    # KnowledgeGraph Protocol
│   │   └── networkx_kg.py
│   ├── vectorstore.py                      # concrete LanceDB module (no interface — YAGNI)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py                       # Anthropic wrapper (prompt-caching aware)
│   │   └── prompts/
│   │       ├── decomposer.system.md
│   │       ├── statute_retriever.system.md
│   │       ├── case_rerank.system.md
│   │       └── synthesizer.system.md
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── decomposer.py
│   │   ├── statute_retriever.py
│   │   ├── case_retriever.py
│   │   ├── synthesizer.py
│   │   └── validator_stub.py
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── allowlist.py
│   │   ├── statutes.py
│   │   ├── caselaw.py
│   │   └── __main__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                          # FastAPI app
│   │   ├── orchestrator.py                 # chains agents, stamps + routes events
│   │   └── sse.py                          # SSE helpers
│   └── cli/
│       ├── __init__.py
│       └── ask.py                          # same pipeline, no HTTP — for local debugging
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/sse.ts
│       ├── components/
│       │   ├── KGPanel.tsx
│       │   ├── TracePanel.tsx
│       │   ├── AnswerPanel.tsx
│       │   └── CitationLink.tsx
│       └── state/runStore.ts
└── tests/
    ├── __init__.py
    ├── ingest/
    │   ├── test_statutes_parser.py
    │   └── test_caselaw_parser.py
    ├── agents/
    │   ├── test_statute_retriever_tools.py
    │   └── test_synthesizer_grounding.py
    └── e2e/
        └── test_locked_question.py
```

## 11. Milestones

Each milestone leaves the system runnable (if ugly). End-to-end first; no milestone touches content until the skeleton is proven.

### M0 — Skeleton with fakes

Done when:
- FastAPI server starts on `:8000`. `POST /ask` and `GET /stream` implemented.
- Vite dev server on `:5173`, proxies to `:8000`.
- Typing the locked question triggers a hardcoded ~10-second "run": decomposer emits three fake thinking deltas; statute retriever emits `node_visited` / `edge_traversed` for a hardcoded path on a hardcoded KG; case retriever emits three fake `case_found`; synthesizer emits a canned Dutch answer token-by-token.
- KGPanel animates correctly, TracePanel renders events in order, AnswerPanel renders a structured answer with clickable (stub-URL) citations.
- Zero LLM calls, zero data-source dependencies.

### M1 — Statute ingestion + KG viewer

Done when:
- `python -m jurist.ingest.statutes` populates `data/kg/huurrecht.json` from real BWB XML for the allowlisted sources.
- KG JSON contains ≥50 article nodes and ≥50 cross-reference edges.
- `python -m jurist.api` loads the KG at startup; KGPanel renders real nodes and real edges with `dagre` layout, readable on a laptop screen.
- Unit test: parser extracts `art. 7:248 BW` correctly, including its outgoing refs.

### M2 — Real statute retriever

Done when:
- `StatuteRetriever` runs a real Claude tool-use loop.
- On the locked question: the retriever terminates via `done` (not max-iter exhaustion) in ≤15 iterations; `cited_articles` includes `art. 7:248 BW`; `visit_path` is non-trivial (≥3 nodes); the KG animation matches.
- Guardrail test: forcing a duplicate-call loop triggers the detector and advances.
- Unit tests: each tool implementation (`search_articles`, `get_article`, `follow_cross_ref`) against a fixture KG.

### M3 — Case ingestion + case retriever

Done when:
- `python -m jurist.ingest.caselaw --limit 300` populates LanceDB with huurrecht ECLIs.
- `CaseRetriever` returns top-3 on the locked question. All returned ECLIs exist in LanceDB. Similarity scores are real. Rerank reasons are non-trivial.
- Citation click opens `uitspraken.rechtspraak.nl/...` in a new tab.
- Unit test: bge-m3 embedding is deterministic across runs for the same input.

### M4 — Decomposer + Synthesizer + grounding

Done when:
- Full chain runs on real LLMs for the locked question end-to-end without developer intervention.
- The structured Dutch answer renders. Every citation resolves. Clicking each citation navigates to the correct source.
- Grounding guard test (unit-level on the synthesizer): given `cited_articles = [A, B, C]` and a prompt that attempts to steer toward an imagined citation `D`, the per-request `Literal` enum blocks it at schema-validation time; the synthesizer produces a valid output or, after one regeneration still failing, the run emits `run_failed { reason: "citation_grounding" }` and the UI shows the error. No silent hallucination in either path.

### M5 — Validator stub + polish + README

Done when:
- `ValidatorStub` is wired in and emits `agent_finished` with `valid: true`. TracePanel shows the validator step as its own section.
- Failure paths (citation grounding failure, tool-error exhaustion, LanceDB unavailable, Anthropic 5xx) render a readable error in the UI instead of a white screen.
- README covers: what this is, how to run from a fresh Windows clone (uv sync, npm install, `.env`, ingestion, server, frontend), the demo question, expected behavior, known limitations, v2 ideas.

### v1 acceptance

All of the above, from a fresh clone, with `ANTHROPIC_API_KEY` set. No manual interventions during a live demo other than clicking **Ask** and waiting.

## 12. Testing strategy

- **Unit.** BWB XML parser, rechtspraak XML parser, cross-reference regex. Tool implementations against a fixture KG. Synthesizer grounding (per-request `Literal` enforcement + post-hoc resolution). Orchestrator event emission order.
- **Integration.** One end-to-end test on the locked question, spanning the real KG, a small fixture LanceDB (pre-generated, checked into `tests/fixtures/`), and real Anthropic calls. Gated on `RUN_E2E=1` so it does not burn tokens by default.
- **Out of scope for v1.** Golden dataset, multi-question eval, LLM-as-judge, regression tracking — all are v2 items per the scope doc.

## 13. Configuration

Environment variables (`.env`):

- `ANTHROPIC_API_KEY` — required.
- `JURIST_DATA_DIR` — default `./data`.
- `JURIST_MODEL_DECOMPOSER` — default `claude-haiku-4-5-20251001`.
- `JURIST_MODEL_RETRIEVER` — default `claude-sonnet-4-6`.
- `JURIST_MODEL_RERANK` — default `claude-haiku-4-5-20251001`.
- `JURIST_MODEL_SYNTH` — default `claude-sonnet-4-6`.
- `JURIST_MAX_RETRIEVER_ITERS` — default `15`.
- `JURIST_CASELAW_LIMIT` — default `300`.

`.env.example` is committed. No secrets are committed.

## 14. Deferred to v2 / open questions

- Real validator (schema + citation resolution + contradiction detection + LLM-as-judge correctness pass).
- KG maintenance agent that watches for BWB updates and re-ingests.
- Parallel tool use within the retriever loop, with concurrent UI animations (already permitted — just not exercised in v1 planning).
- Parallel execution of statute and case retrievers.
- Multi-rechtsgebied support.
- Side-panel preview of retrieved article/case text instead of new-tab navigation.
- Persistent query history; user accounts.
- Golden dataset + evaluation harness.
- Deployment.

## 15. Decisions log

| # | Decision | Alternatives considered | Reason |
| --- | --- | --- | --- |
| 1 | Statute retrieval is an LLM tool-use loop | Hybrid (LLM seeds + deterministic walk); fully deterministic | Makes live KG reasoning genuinely LLM-driven; user explicitly relaxed latency in exchange. |
| 2 | KG is NetworkX from JSON, not Neo4j | Real Neo4j in Docker; Kuzu embedded | ~100 nodes does not justify a graph-DB engine; Protocol preserves Neo4j swap path. |
| 3 | Anthropic is the only remote vendor | Voyage or Cohere hosted embeddings | Minimizes external-vendor footprint for a demo. |
| 4 | Embeddings: bge-m3 local | Voyage `multilingual-2`; Cohere `multilingual-v3` | Consequence of #3; bge-m3 is strong enough for this corpus and works offline. |
| 5 | Case retriever is vector search + Haiku rerank, not a tool-use loop | Symmetric tool-use loop on the case side | Keeps the trace narrative single-threaded; KG is the interesting side of the story. |
| 6 | Statute and case retrievers run sequentially | Parallel | Cleaner trace UX; parallel saves little with relaxed latency. |
| 7 | LLM backend uses the Anthropic SDK directly | `claude -p` CLI wrapping Claude Code, with custom tools exposed via MCP | SDK gives direct tool use, streaming, prompt caching, predictable auth; `claude -p` would require an MCP server and hide control. |
| 8 | opendataloader-pdf is not used | Adopt as universal document loader | Data sources are XML (BWB, rechtspraak), not PDF; no exercised use. |
| 9 | Citation grounding via per-request `Literal` enums + post-hoc resolution; one regen, then hard-fail | Post-hoc only; retry without schema change | Schema-level enforcement blocks the easy hallucination path before generation. |
| 10 | One SSE stream per run, with a short ring buffer | Per-agent streams; WebSocket; polled fetch | Simpler frontend state; reconnect-replay makes a live demo robust. |
| 11 | No agent framework | LangChain, LangGraph, CrewAI, AutoGen | User-specified non-goal; direct Pydantic + SDK calls make the contract readable. |
| 12 | One `KnowledgeGraph` Protocol interface; no `CaseStore` interface | Full symmetry with vector store Protocol | Only the KG has a stated swap path (Neo4j). The vector store has no such path, so an interface there is premature abstraction. |

---

*End of spec.*
