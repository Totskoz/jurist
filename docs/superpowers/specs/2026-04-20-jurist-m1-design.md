# Jurist M1 — Design (Statute ingestion + KG viewer)

**Date:** 2026-04-20
**Status:** Approved. Implementation not yet started.
**Parent:** [Jurist v1 design](2026-04-17-jurist-v1-design.md) — read first for system context, agent contracts, and event protocol.

---

## 1. Context

M0 is complete (tag `m0-skeleton`): the end-to-end pipeline, orchestrator, SSE transport, and frontend panels are driven by fake agents and a hardcoded in-memory KG. M1 is the first "replace-a-fake-with-real" milestone per the v1 spec's end-to-end-first principle.

**M1 replaces the `/api/kg` fake.** Everything else — decomposer, statute retriever, case retriever, synthesizer — stays on M0 fakes. The validator remains a stub per v1 scope.

**M1 delivers the ingestion pipeline that feeds the KG.** A new `python -m jurist.ingest.statutes` command fetches real BWB XML, parses it, extracts cross-references, and writes `data/kg/huurrecht.json`. The FastAPI app loads the JSON at startup and serves `/api/kg` from the real graph.

## 2. Scope

**In M1:**
- New `src/jurist/ingest/` package — fetches + parses BWB XML for 3 BWB sources; writes KG JSON + per-article markdown dumps.
- New `src/jurist/kg/` package — `KnowledgeGraph` Protocol (minimal) + NetworkX implementation.
- `src/jurist/api/app.py` — lifespan-load KG at startup; serve `/api/kg` from the loaded graph; hard-fail on missing KG file.
- Minimal frontend legibility tweaks in `KGPanel.tsx` (dagre params, hover tooltip, BWB border tint, inline legend).
- Layered tests — parser, xref extraction, idempotency, KG loader, API endpoint, end-to-end ingest, fake-path drift catch.

**Out of M1 (deferred to M1.5):**
- Widening the allowlist beyond the 3 "core" BWBs to the full ~8-BWB huurrecht corpus.
- KG panel clustering/filtering for large (~500-node) post-widen graphs.

**Out of v1 entirely** (unchanged from v1 spec §14): real validator, KG maintenance agent, parallel retrievers, multi-rechtsgebied, persistent query history, deployment.

## 3. Architecture

### 3.1 New modules

```
src/jurist/
├── ingest/
│   ├── __init__.py
│   ├── allowlist.py       # 3 core BWBs with display names (M1.5 widens this)
│   ├── fetch.py           # GET BWB XML → data/cache/bwb/{bwb_id}.xml
│   ├── parser.py          # lxml walk → list[ArticleNode]; structural article_id
│   ├── xrefs.py           # explicit <intref>/<extref> edges + same-BWB regex fallback
│   ├── statutes.py        # orchestrates fetch → parse → xrefs → write JSON + md dumps
│   └── __main__.py        # CLI entry
├── kg/
│   ├── __init__.py
│   ├── interface.py       # KnowledgeGraph Protocol
│   └── networkx_kg.py     # NetworkX DiGraph impl
```

### 3.2 Touched modules

- `src/jurist/api/app.py` — remove `FAKE_KG` import; add `lifespan` that loads KG; `/api/kg` reads `app.state.kg`.
- `src/jurist/config.py` — add `kg_path` property (`data_dir / "kg" / "huurrecht.json"`).
- `src/jurist/schemas.py` — add `KGSnapshot` Pydantic model (the file shape consumed by `NetworkXKG.load_from_json`: `generated_at`, `source_versions`, `nodes`, `edges`).
- `pyproject.toml` — add runtime deps: `lxml`, `httpx`, `networkx`.
- `web/src/components/KGPanel.tsx` — layout params, hover tooltip, BWB border tint, inline legend.
- `tests/ingest/`, `tests/kg/`, `tests/api/`, `tests/integration/` — new test packages.

### 3.3 Untouched modules

- `src/jurist/fakes.py` — stays as-is; fake agents still import from it.
- All fake agents (decomposer, statute_retriever, case_retriever, synthesizer, validator_stub) — no changes.
- `src/jurist/api/orchestrator.py` and `src/jurist/api/sse.py` — no changes.

## 4. Allowlist

`src/jurist/ingest/allowlist.py` is the single scope knob. M1 version:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class BWBEntry:
    name: str                               # full legal title
    label_prefix: str                       # human-readable prefix for ArticleNode.label
    filter_titel: list[str] | None = None   # None = no filter; e.g., ["4"] = only Titel 4

BWB_ALLOWLIST: dict[str, BWBEntry] = {
    "BWBR0005290": BWBEntry(
        name="Burgerlijk Wetboek Boek 7",
        label_prefix="Boek 7",
        filter_titel=["4"],   # Huur only
    ),
    "BWBR0002888": BWBEntry(
        name="Uitvoeringswet huurprijzen woonruimte",
        label_prefix="Uhw",
    ),
    "BWBR0003402": BWBEntry(
        name="Besluit huurprijzen woonruimte",
        label_prefix="Besluit huurprijzen",
    ),
}
```

**M1.5 will add (without parser code changes):** BW Boek 6, Wet doorstroming huurmarkt 2015, Wet goed verhuurderschap, Overlegwet, Huisvestingswet 2014.

The parser is schema-conformant (walks the XML tree generically); widening the allowlist must not require parser changes. If M1.5 uncovers BWB XML patterns the parser doesn't handle, that's a parser bug — an edge case the schema-conformant walk missed.

## 5. Ingestion

### 5.1 Fetch (`fetch.py`)

Single entry point:

```python
def fetch_bwb_xml(bwb_id: str) -> bytes: ...
```

- URL template lives as a module-level constant (`BWB_XML_URL_TEMPLATE`). The exact URL is confirmed during implementation — KOOP / wetten.overheid.nl endpoint shapes have shifted over the years. Candidates: `https://wetten.overheid.nl/xml.php?regelingid={bwb_id}`, or the KOOP FRBR repository URL pattern. The spec commits to the function signature, not the URL.
- Cache path: `data/cache/bwb/{bwb_id}.xml`. Overwritten on `--refresh`.
- `--no-fetch` mode: cache-only; raises `FileNotFoundError` if missing.
- HTTP client: `httpx.Client` (sync — ingest is a one-shot CLI).

### 5.2 Parser (`parser.py`)

Walk the parsed tree with `lxml.etree.iter("artikel")`. For each `<artikel>`:

- **Skip** if `status="vervallen"` on the element, or if the `<kop>` contains only `"[Vervallen]"`.
- **article_id**: structural path from ancestor chain. Walk `iterancestors()`, collect container elements (`boek`, `titel`, `afdeling`, `hoofdstuk`, `paragraaf`), reverse to top-down order, emit `{Tag}{nr}` segments. Prefix with BWB ID.
  - Example (BW7): `BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248`
  - Example (UHW, flat under root): `BWBR0002888/Artikel6`
- **Suffix handling**: `artikel nr="248a"` → `Artikel248a` (letter preserved verbatim).
- **bwb_id**: derived from `article_id.split("/")[0]`.
- **label**: `f"{entry.label_prefix}, Artikel {nr}"`. Example: `"Boek 7, Artikel 248"`, `"Uhw, Artikel 6"`, `"Besluit huurprijzen, Artikel 1"`. Matches the convention already established in `FAKE_KG`.
- **title**: `<kop><titel>` text if present, else `""`.
- **body_text**: concatenation of all `<lid><al>` text across paragraphs, `\n\n`-separated. Empty `<al>` elements skipped.

**Titel filter** (applied per `BWBEntry.filter_titel`): drop articles whose `<titel>` ancestor has `nr` not in the filter list. This narrows BWBR0005290 from ~300 articles to ~100 (Titel 4 only).

### 5.3 Cross-reference extraction (`xrefs.py`)

Two-layer extraction; `kind="explicit"` wins in dedup.

**Layer 1 — explicit from reference elements.** Walk `<intref>` (same-BWB) and `<extref>` (cross-BWB) inside each article's body. Resolve `href` to an article_id in the parsed node set. Emit `ArticleEdge(from_id=source, to_id=target, kind="explicit", context=None)`. If target isn't in the parsed nodes (out-of-allowlist or vervallen), drop silently.

**Layer 2 — regex fallback over body_text.** Pattern:

```python
r'artikel(?:en)?\s+(\d+[a-z]?)(?:\s+(?:eerste|tweede|derde|vierde|vijfde|zesde|zevende|achtste|negende|tiende|\d+e)\s+lid)?'
```

- Matches `"artikel 248"`, `"artikel 248a"`, `"artikel 249 lid 2"` (lid ignored — edges are article-level). **Compound refs like `"artikelen 249 en 250"` match only the leading number** (`"249"`); the trailing `"250"` is expected to be picked up by an explicit `<intref>` element or accepted as a false negative. The regex is the fallback layer, not exhaustive; explicit refs are the reliable provenance.
- **Same-BWB resolution only.** Each regex hit is assumed to refer to an article in the source article's BWB. Cross-law references in free text are rare in BWB corpora; `<extref>` covers the important cross-law cases.
- Emits `ArticleEdge(..., kind="regex")`. Targets not in the parsed node set → drop silently.

**Deduplication.** Key by `(from_id, to_id)`. If both layers produce the same edge, keep `kind="explicit"`. If a layer produces the same edge twice, keep the first.

### 5.4 Idempotency

KG JSON has top-level `source_versions: {bwb_id: date_str}`. Date is extracted from the BWB XML root's `vigerend-sinds` attribute (or equivalent — confirmed during implementation).

On ingest re-run:
- Compare fetched BWB's `vigerend-sinds` against the existing `source_versions[bwb_id]` in the current `huurrecht.json`.
- If all match, log `"no changes; skipping parse"` and exit 0 without rewriting JSON.
- `--refresh` forces re-fetch and re-parse regardless.

### 5.5 Output

- `data/kg/huurrecht.json` — spec v1 §7.3 shape (`generated_at` UTC ISO 8601, `source_versions`, `nodes`, `edges`). Written atomically via temp file + `os.replace`.
- `data/articles/{bwb_id}/{flat_filename}.md` — per-article markdown dump. `flat_filename` replaces path separators with `-`, e.g., `Boek7-Titel4-Afdeling5-Artikel248.md`. Content: YAML frontmatter (article_id, label, title, outgoing_refs) + body_text as markdown.
- `data/` is gitignored. Ingest output is rebuilt on every fresh clone.

**Why produce markdown dumps in M1?** M2's statute retriever (`get_article` tool) will want raw article text to return to the LLM; M4's synthesizer will want it to verify verbatim quotes. The parser already has the content; dumping it now costs ~30 extra lines and removes work from downstream milestones.

### 5.6 CLI

```
uv run python -m jurist.ingest.statutes [OPTIONS]

Options:
  --refresh         force re-fetch + re-parse (bypass source_versions check)
  --no-fetch        cache-only; fail if cache missing
  --bwb BWB_ID      restrict to specific BWB IDs (debug; repeatable)
  --limit N         cap articles per BWB (debug)
  -v, --verbose     print per-step summary
```

**Default behavior:** check cache → fetch missing → parse → dedup edges → write JSON + markdown dumps. Print terminal summary on completion:

```
Ingest complete: 73 articles, 112 edges from 3 sources (Boek 7, Uhw, Besluit) in 3.4 s.
Output: data/kg/huurrecht.json (24 KB)
```

## 6. KG module

### 6.1 Protocol (`interface.py`)

```python
from typing import Protocol
from jurist.schemas import ArticleNode, ArticleEdge

class KnowledgeGraph(Protocol):
    def all_nodes(self) -> list[ArticleNode]: ...
    def all_edges(self) -> list[ArticleEdge]: ...
    def get_node(self, article_id: str) -> ArticleNode | None: ...
```

Minimal surface for M1 consumers (`/api/kg`, drift-catch test). M2 will grow the Protocol with `search_articles(query, top_k)`, `successors(article_id)`, `get_edges_from(article_id)` as the statute retriever's tool implementations need them. Widening a Protocol is backward-compatible when the concrete impl grows in lockstep.

### 6.2 Implementation (`networkx_kg.py`)

```python
class NetworkXKG:
    _graph: networkx.DiGraph   # node attrs = ArticleNode fields; edge attrs = kind + context

    @classmethod
    def load_from_json(cls, path: Path) -> "NetworkXKG":
        # Reads file as UTF-8, validates shape via Pydantic KGSnapshot, populates DiGraph.
        # Propagates FileNotFoundError and pydantic.ValidationError.

    def all_nodes(self) -> list[ArticleNode]: ...
    def all_edges(self) -> list[ArticleEdge]: ...
    def get_node(self, article_id: str) -> ArticleNode | None: ...
```

`load_from_json` validates the JSON against a new Pydantic `KGSnapshot` model (added to `schemas.py`) that mirrors the v1 spec §7.3 shape. Duplicate node IDs or edges → `ValueError`.

## 7. API integration

### 7.1 Startup

FastAPI `lifespan` context manager:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.kg = NetworkXKG.load_from_json(settings.kg_path)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"KG not found at {settings.kg_path}. "
            f"Run: uv run python -m jurist.ingest.statutes"
        ) from e
    logger.info(
        "Loaded KG: %d nodes, %d edges from %s",
        len(app.state.kg.all_nodes()),
        len(app.state.kg.all_edges()),
        settings.kg_path,
    )
    yield
```

Uvicorn boot fails on missing KG with the `RuntimeError` message visible in the terminal — the developer sees exactly what to run. No silent empty-KG fallback.

### 7.2 `/api/kg` endpoint

```python
@app.get("/api/kg")
async def kg(request: Request) -> dict:
    g: KnowledgeGraph = request.app.state.kg
    return {
        "nodes": [n.model_dump() for n in g.all_nodes()],
        "edges": [e.model_dump() for e in g.all_edges()],
    }
```

Same JSON shape as M0. The frontend consumes it unchanged.

### 7.3 `fakes.py` and fake-agent compatibility

`src/jurist/fakes.py` is untouched. Fake agents continue to import `FAKE_KG`, `FAKE_VISIT_PATH`, `FAKE_CASES`, `FAKE_ANSWER`.

**Risk.** `FAKE_VISIT_PATH` emits `node_visited` events with article_ids like `BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248`. These must match the format the real parser produces. If the parser drifts — different ancestor segmentation, different suffix handling — the frontend silently no-ops on unknown IDs, which looks like a broken animation. **Mitigation:** the drift-catch test in §9 asserts `FAKE_VISIT_PATH ⊂ parsed_node_set` at CI time.

## 8. Frontend tweaks

`web/src/components/KGPanel.tsx` — no new components, no click handlers.

- **Dagre params:** `{ rankdir: 'LR', nodesep: 40, ranksep: 90 }` (up from M0's `30` / `60`). Denser per-rank, more generous between ranks for ~80-node graphs.
- **Hover tooltip:** wrap node label in `<div title={title}>`. Native browser tooltip shows the article title (e.g., `"Huurverhoging — voorwaarden"`).
- **BWB-source border tint** (applied only in `default` state — state-driven colors still win when the agent is running):

```ts
const BWB_COLORS: Record<string, string> = {
  'BWBR0005290': '#1e40af',  // Boek 7 — blue
  'BWBR0002888': '#be185d',  // Uhw — pink
  'BWBR0003402': '#047857',  // Besluit — green
};
const bwbBorder = (article_id: string) =>
  BWB_COLORS[article_id.split('/')[0]] ?? '#6b7280';
```

- **Inline legend:** small 3-entry legend in a corner of the KGPanel (colored dot + BWB short name). ~10 lines of JSX within the same file.

**Explicitly not in M1:** node click → detail side panel (v2, spec §14); BWB clustering via React Flow compound nodes (M5); filter/search/focus-subgraph UI.

## 9. Tests

### 9.1 Layering

```
tests/
├── ingest/
│   ├── fixtures/
│   │   ├── BWBR0005290_excerpt.xml    # BW7 Titel 4, includes art. 246-265
│   │   ├── BWBR0002888_excerpt.xml    # UHW, incl. art. 6 + 10
│   │   └── BWBR0003402_excerpt.xml    # Besluit, minimal
│   ├── test_parser.py
│   ├── test_xrefs.py
│   └── test_idempotency.py
├── kg/
│   └── test_networkx_kg.py
├── api/
│   └── test_kg_endpoint.py
└── integration/
    ├── test_ingest_end_to_end.py
    └── test_fake_paths_in_real_kg.py
```

Fixtures are real BWB XML, trimmed to the minimum articles needed to cover the test cases. They are obtained once during M1 implementation (run `fetch.py` against the live endpoint, then hand-trim the result) and committed to the repo. Fixture size target: each excerpt ≤100 KB.

### 9.2 Per-file cases

**`test_parser.py`** — spec-required `test_parses_art_7_248_bw()` asserts the parsed node has id `BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248`, label `"Boek 7, Artikel 248"`, non-empty body, expected outgoing refs. Plus: `test_skips_vervallen`, `test_preserves_article_suffix` (`248a`), `test_flat_bwb_article_id` (UHW), `test_body_text_concatenates_leden`, `test_titel_filter_applied`.

**`test_xrefs.py`** — table-driven regex: `"artikel 249"` → one match, `"artikel 249 lid 2"` → one match (lid ignored), `"artikel 249a"` → one match (suffix preserved), `"artikelen 249 en 250"` → one match for leading `249` only (documents the compound-ref limitation per §5.3), `"in 249 gevallen"` → no match (prose false-positive guard). Dedup: explicit + regex same edge → one output with `kind="explicit"`. Out-of-allowlist `<extref>` → dropped silently.

**`test_idempotency.py`** — matching `source_versions` → short-circuit (fetcher mocked). `--refresh` → force re-parse.

**`test_networkx_kg.py`** — JSON roundtrip: node count, edge count; `get_node(known)` returns the right `ArticleNode`; `get_node(unknown)` returns `None`; malformed JSON → `pydantic.ValidationError`; duplicate node IDs in JSON → `ValueError`.

**`test_kg_endpoint.py`** — `TestClient` with `settings.kg_path` pointing to a small fixture JSON; `GET /api/kg` returns expected shape and node/edge counts. Missing KG file → `TestClient` context manager raises `RuntimeError` during startup (the hard-fail contract).

**`test_ingest_end_to_end.py`** — runs the full ingest pipeline in-process against the 3 fixture XMLs; asserts output JSON validates against the v1 §7.3 shape; markdown dumps written for each parsed article.

**`test_fake_paths_in_real_kg.py`** — runs the same in-process ingest, then asserts every article_id in `FAKE_VISIT_PATH` and every `(bwb_id, article_label)` in `FAKE_ANSWER.relevante_wetsartikelen` resolves to a parsed node. Drift-catch for the M1→M2 transition.

### 9.3 CI vs. acceptance

CI tests verify parser and extraction correctness against fixture XMLs. The v1 spec §11.M1 success criteria — **≥50 nodes, ≥50 edges** — are **acceptance checks against full real BWB XML**, verified once during M1 implementation by running `uv run python -m jurist.ingest.statutes` and inspecting the terminal summary. Not a CI test (full BWB XMLs are not committed).

All existing M0 tests must pass unchanged.

## 10. Spec deltas to v1 design

### 10.1 v1 design §2 — Scope

Widen the `In.` clause from 3 BWBs to the ~8-BWB target corpus (BW Boek 7 Titel 4, Uitvoeringswet huurprijzen woonruimte, Besluit huurprijzen woonruimte, BW Boek 6, Wet doorstroming huurmarkt 2015, Wet goed verhuurderschap, Overlegwet, Huisvestingswet 2014). Note that M1 ships the first three ("core") and M1.5 widens to the rest.

### 10.2 v1 design §11 — Milestones

Insert new milestone **M1.5 — Full-corpus widen** between M1 and M2:

> **M1.5 — Full-corpus widen**
>
> Done when:
> - `src/jurist/ingest/allowlist.py` widens to the full huurrecht corpus (8 BWBs): the three M1 cores plus BW Boek 6, Wet doorstroming huurmarkt 2015, Wet goed verhuurderschap, Overlegwet, Huisvestingswet 2014.
> - `uv run python -m jurist.ingest.statutes --refresh` runs without parser code changes (schema-conformance check).
> - Output KG contains ≥400 article nodes with cross-references across BWBs.
> - KG panel still loads without crash; dense-layout readability is a separate concern (post-M1.5 polish if needed).

### 10.3 `CLAUDE.md`

On M1 landing (not as part of the spec delta — as part of the implementation commit):
- Flip the `/api/kg` row in the "fake vs. real" table to `"real (loads data/kg/huurrecht.json at startup)"`.
- Add `uv run python -m jurist.ingest.statutes` to the commands section as a prerequisite before `uv run python -m jurist.api`.

## 11. Risks and open items

- **BWB XML endpoint URL.** Confirmed during implementation, not in this spec. Contract: `fetch_bwb_xml(bwb_id) -> bytes`. If the endpoint requires authentication, breaks under load, or changes shape, fall back to "manually download via browser → drop into `data/cache/bwb/`". The `--no-fetch` mode exists for exactly this scenario.
- **Parser schema-conformance assumption.** M1 tests parser correctness on 3 BWB excerpts. M1.5 extends to 5 more BWBs, potentially uncovering parser bugs on less-common XML shapes (older legislation with deprecated tags, mixed namespace versions, bijlage-style structures). The parser's fixture-agnostic tree walk is designed for this, but M1.5 is the real test.
- **Fake-path drift.** If the real parser produces `article_id` formats that don't match `FAKE_VISIT_PATH`, the drift-catch test fails at CI time. Fix: align the parser output, or update `FAKE_VISIT_PATH` to match real output. The fakes are scaffolding; they're allowed to change.
- **KG panel legibility at M1.5.** 3-BWB KG at ~80 nodes renders fine with dagre LR. 8-BWB KG at ~500 nodes will be visually dense. Not an M1 concern, but the v1 spec's "readable on a laptop screen" promise will need compound-nodes / cluster-by-BWB work as part of M5 polish.

## 12. Decisions log

| # | Decision | Alternatives considered | Reason |
| --- | --- | --- | --- |
| 1 | Corpus goal widens to ~8 BWBs; M1 ships 3 | Keep 3 permanently; widen to all 8 in M1 | Widen-goal keeps the portfolio demo ambitious (whole huurrecht); M1-narrow keeps the first milestone testable. |
| 2 | XML fetch is hybrid (cache + live-on-miss) | Live every run; commit XML fixtures to repo | Reproducible offline after first run; one-line URL config for endpoint changes; `--no-fetch` is the safety valve for demo day. |
| 3 | Same-BWB regex only; no cross-law regex | Regex with BWB-alias map | `<extref>` covers cross-law refs; regex-plus-alias is brittle and adds little value for the effort. |
| 4 | Dedup prefers `kind="explicit"` over `kind="regex"` | Keep both as separate edges | `(from_id, to_id)` is the identity; explicit is the more reliable provenance. |
| 5 | Out-of-allowlist edge targets dropped silently | Keep as dangling edges with `null` target | The KG is a closed set; dangling edges clutter the viz and confuse the retriever. |
| 6 | Article markdown dumps produced in M1 | Defer to M2 when needed | Parser already has the content; ~30 extra lines; saves work in M2/M4. |
| 7 | Startup hard-fails on missing KG | Serve empty KG with warning | Demo-loud failure with an exact run-this message beats a silent broken demo. |
| 8 | Minimal `KnowledgeGraph` Protocol in M1 | Full Protocol (with search_*/successors) up front | Premature surface; methods and their impls land together as M2 consumes them. |
| 9 | Frontend option (b): legibility tweaks, no side panel | No frontend change; add click-to-detail side panel | (a) risks ugly demo; (c) pre-builds v2. (b) is ~25 lines of change that materially improves the demo. |
| 10 | Drift-catch test asserts `FAKE_VISIT_PATH ⊂` real KG | No test; manually verify | Silent no-op on unknown IDs is a demo failure mode; CI catches the drift cheaply. |
| 11 | Title-filter lives in allowlist entry, not parser | Hardcode BW7 Titel 4 filter in parser | Keeps parser generic; widening via allowlist.py stays a data change. |

---

*End of spec.*
