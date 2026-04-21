# M3a — Caselaw Ingestion — Design

**Date:** 2026-04-21
**Status:** Approved. Implementation not yet started.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§5.3, §7.4, §8.2, §11 M3)
**Branch:** `m3a-caselaw-ingestion`

---

## 1. Context and goals

Parent spec §11 lumps "case ingestion + case retriever" into one M3 milestone. We split it: **M3a** ships the ingestion pipeline and a populated LanceDB; **M3b** (future spec) replaces the fake `case_retriever` agent with the real bge-m3 + Haiku-rerank flow over that index. The split mirrors the M1→M2 rhythm (statute ingest, then statute retrieve) and gives each half a clean "done" gate.

**M3a is done when** a fresh-clone developer can run `uv run python -m jurist.ingest.caselaw`, watch ≥100 unique huur-related ECLIs get fetched from rechtspraak.nl, chunked, embedded with bge-m3, and written to LanceDB — with zero LLM calls. The `case_retriever` agent remains the M0 fake; no orchestrator or frontend changes.

**In scope.** A new `jurist.ingest.caselaw` CLI + pipeline, the `embedding.py` bge-m3 wrapper (shared with M3b), `vectorstore.py` LanceDB CRUD, a stdlib chunker, a lenient keyword filter, test fixtures, and a parent-spec amendment documenting the verified rechtspraak.nl data-source shape.

**Out of scope.** Real case retriever (M3b). Huurcommissie as a data source (v2 scope — see §13). Frontend changes. Decomposer/synthesizer. Any LLM use in the ingestion path. Advanced filter strategies (BM25 over abstracts, etc.).

## 2. Verified data-source shape

The parent spec §8.2 premise — "rechtsgebied = 'Huurrecht'" as a subject filter — does not hold. Live probing on 2026-04-21 established:

**Verified (works):**
- `GET https://data.rechtspraak.nl/uitspraken/zoeken` returns an Atom feed. Total corpus: ~3.67M ECLIs.
- `GET https://data.rechtspraak.nl/uitspraken/content?id=ECLI:...&return=META` returns RDF/XML metadata (identifier, date, creator/instantie, subject URI, zaaknummer, deeplink).
- `GET https://data.rechtspraak.nl/uitspraken/content?id=ECLI:...` (no `return=META`) returns the full uitspraak XML body.
- `GET https://data.rechtspraak.nl/Waardelijst/Rechtsgebieden` is the authoritative taxonomy list.
- Citation URL pattern: `https://uitspraken.rechtspraak.nl/details?id=ECLI:...` (present as `<link rel="alternate">` on every search-feed entry).
- Subject URI shape: `http://psi.rechtspraak.nl/rechtsgebied#{camelCase_path}`, e.g., `civielRecht`, `civielRecht_verbintenissenrecht`, `civielRecht_arbeidsrecht`, `bestuursrecht_omgevingsrecht`.

**Does not exist:**
- No `huurrecht`, `civielrecht_huurrecht`, or `civielRecht_huurrecht` subject URI (each returns 0 hits).
- Huurcommissie is not a `creator` URI in the open-data corpus (publishes separately, not through rechtspraak.nl).
- The zoeken endpoint does not accept a keyword/`q` parameter.

**Not usable:**
- `POST https://uitspraken.rechtspraak.nl/api/zoek` (the SPA's private backing API) returns HTTP 411 / 302→"mededeling" redirect against scripted clients. Probably WAF/CSRF. Undocumented. Out of scope for ingestion.

**Chosen filter:** `subject=http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht` + `modified` date floor + local keyword fence on downloaded body text. Verbintenissenrecht is huurrecht's taxonomic parent in Dutch law (Boek 7 Titel 4 is a verbintenissenrechtelijke afdeling). Volumes observed 2026-04-21:

| Filter | Hits |
|---|---|
| `civielRecht_verbintenissenrecht` (all time) | 53,389 |
| `civielRecht_verbintenissenrecht` + `modified>=2024-01-01` | 19,840 |

Default ingestion window is `modified>=2024-01-01` → ~20k ECLIs pulled, locally keyword-filtered to a few hundred huur-relevant cases. Acceptable for a one-shot batch job.

## 3. Architecture

### 3.1 File changes

**Added:**
- `src/jurist/ingest/caselaw.py` — pipeline orchestrator `run_ingest()`.
- `src/jurist/ingest/caselaw_fetch.py` — HTTP: list endpoint pagination + content endpoint + disk cache.
- `src/jurist/ingest/caselaw_parser.py` — RDF metadata + body text extraction.
- `src/jurist/ingest/caselaw_filter.py` — lenient keyword fence (pure function).
- `src/jurist/ingest/splitter.py` — paragraph-aware chunker (stdlib, ~40 lines).
- `src/jurist/ingest/caselaw_profiles.py` — `{profile_name → (subject_uri, keyword_terms)}` registry. Ships with `huurrecht` populated; extensibility hook for future rechtsgebieden.
- `src/jurist/embedding.py` — `Embedder` class wrapping `sentence-transformers` bge-m3. Shared with M3b retriever.
- `src/jurist/vectorstore.py` — `CaseStore` concrete class over LanceDB (CRUD + query). No interface — parent spec §15 decision #12.
- `tests/fixtures/caselaw/*.xml` — 2–3 committed real ECLI content fixtures.
- `tests/ingest/test_caselaw_fetch.py`, `test_caselaw_parser.py`, `test_caselaw_filter.py`, `test_splitter.py`, `test_caselaw.py`.
- `tests/embedding/test_embedding.py`.
- `tests/vectorstore/test_vectorstore.py`.
- `tests/integration/test_m3a_ingestion_e2e.py` (RUN_E2E gated).

**Modified:**
- `src/jurist/ingest/__main__.py` — dispatch between `statutes` and `caselaw` subcommands.
- `src/jurist/schemas.py` — add `CaseChunkRow` (storage schema).
- `src/jurist/config.py` — add M3a tunables (§10).
- `pyproject.toml` — add `sentence-transformers`, `lancedb` dependencies.
- `README.md` — first-run model-download note, ingestion command, expected wall-clock.

**Unchanged:** Orchestrator, `RunContext`, all agents (including the still-fake `case_retriever`), `app.py`, `sse.py`, frontend. M3a is purely data-prep.

### 3.2 Pipeline stages

`caselaw.run_ingest()` drives nine stages sequentially:

1. **Warm model** — instantiate `Embedder("BAAI/bge-m3")` *first*, before any HTTP work. Triggers the HuggingFace download on a fresh machine; user sees one "Loading BAAI/bge-m3…" log line; subsequent runs hit HF cache. Doing this first means if the model fails, no wasted fetches.
2. **List** — paginate `zoeken?subject=<uri>&modified=<since>&max=1000&from=N` until an empty page. Collect `[(ecli, modified_ts), …]`. Sequential (cursor is position-dependent). Optional `--max-list N` cap for debugging.
3. **Resume gate** — build set of ECLIs already in LanceDB + disk cache. Skip unless `--refresh`.
4. **Fetch content** — for each fresh ECLI, `GET uitspraken/content?id=ECLI:...` → write to `data/cases/{ecli}.xml`. **5-way parallel** via `concurrent.futures.ThreadPoolExecutor`. Polite `User-Agent: jurist-demo/0.1 (portfolio project)`. Non-200 → one retry with 2 s backoff, then skip + log WARNING.
5. **Parse** — extract RDF metadata (ECLI, ISO date, court, subject_uri, zaaknummer, modified, deeplink URL) + body text (strip XML tags, collapse whitespace, preserve paragraph breaks).
6. **Filter** — `caselaw_filter.passes(body)` lenient fence: case-folded substring match against `{"huur", "verhuur", "woonruimte", "huurcommissie"}`. Log stats.
7. **Chunk** — `splitter.split(body, target_words=500, overlap_words=50)` → list of chunk strings.
8. **Embed** — `embedder.encode(chunks, batch=32)` → L2-normalized 1024-d float arrays.
9. **Write** — batch-append `CaseChunkRow` rows to LanceDB. Deduplicate on `(ecli, chunk_idx)`.

Pipeline reports to stderr at each stage transition with counts. Final summary: listed / fetched (from-cache) / surviving filter / total chunks / unique ECLIs / wall-clock.

### 3.3 Concurrency model

| Stage | Mode | Reason |
|---|---|---|
| Warm model | Sync | One-shot startup |
| List | Sequential | Pagination cursor |
| Fetch content | `ThreadPoolExecutor(max_workers=5)` | Network-bound; polite to rechtspraak.nl |
| Parse | Sequential | Fast; trivial CPU |
| Filter | Sequential | Trivial CPU |
| Chunk | Sequential | Trivial CPU |
| Embed | Batched sequential (bge-m3 batch=32) | GPU/CPU-bound inside the model |
| Write | Sequential batch-append | Avoids LanceDB write contention |

No `asyncio` anywhere in ingestion — matches the sync statutes ingester style. A batch job doesn't need FastAPI-style concurrency.

### 3.4 Idempotency

Two caches short-circuit work:
- **Disk cache** at `data/cases/{ecli}.xml`: skip stage 4 download if present.
- **LanceDB row presence** check by ECLI: skip stages 7–9 for already-embedded cases.

`--refresh` deletes `data/cases/` and `data/lancedb/cases.lance`, then re-runs. No in-place merge; start fresh.

Modified-timestamp updates do not trigger re-ingestion in M3a (a changed uitspraak under an existing ECLI would remain cached). V2 concern.

### 3.5 CLI

```
uv run python -m jurist.ingest.caselaw
  [--profile huurrecht]              # default; selects subject_uri + keyword_terms
  [--since 2024-01-01]
  [--subject-uri URI]                # override profile
  [--max-list N]                     # debug cap
  [--fetch-workers 5]
  [--refresh]
  [-v]
```

Routed via `jurist.ingest.__main__` — `python -m jurist.ingest.statutes …` and `python -m jurist.ingest.caselaw …` both work; `__main__` dispatches by the first argv.

## 4. Data model

### 4.1 `CaseChunkRow` — LanceDB row schema

```python
class CaseChunkRow(BaseModel):
    # identity
    ecli: str                    # "ECLI:NL:RBAMS:2026:1234"
    chunk_idx: int               # 0-based within the case

    # metadata (from RDF)
    court: str                   # "Rechtbank Amsterdam"
    date: str                    # ISO 8601 "2026-04-01"
    zaaknummer: str              # "C/13/123456 / HA ZA 25-001"
    subject_uri: str             # "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    modified: str                # ISO 8601 last-modified timestamp

    # content
    text: str                    # chunk body (verbatim slice of the uitspraak)
    embedding: list[float]       # 1024-d bge-m3, L2-normalized

    # display
    url: str                     # "https://uitspraken.rechtspraak.nl/details?id=ECLI:..."
```

**Logical primary key:** `(ecli, chunk_idx)`. LanceDB doesn't enforce uniqueness; the ingester deduplicates on write.

**Deltas from parent spec §7.4 `CaseChunk`:**
- Renamed `CaseChunk` → `CaseChunkRow` to mark it as a storage type (not the query-result `CitedCase`).
- Added `zaaknummer` (needed for display; part of the case identity).
- Added `subject_uri` (preserves extensibility to other rechtsgebieden).
- Added `modified` (supports future freshness weighting without re-ingest).
- Dropped `rechtsgebied` (label field — `subject_uri` is canonical).

### 4.2 Chunker — `src/jurist/ingest/splitter.py`

Paragraph-aware recursive split, stdlib only, ~40 lines.

- **Target 500 words / overlap 50 words.** Word-count as token proxy — 1 token ≈ 1 word for Dutch legal prose; within bge-m3's 8192-token input window comfortably. Avoids `tiktoken` dep.
- **Algorithm:**
  1. Split body on blank-line boundaries → paragraphs.
  2. Greedily pack paragraphs into chunks up to 500 words.
  3. Single paragraph >500 words → recurse on sentence boundaries (`. `, `? `, `! `, skipping known Dutch abbreviations: `art.`, `artt.`, `lid`, `jo.`, `Hof`, `Mr.`, `Dr.`, etc.).
  4. Single sentence >500 words (malformed XML edge case) → character-split at word boundary.
- Overlap: last 50 words of chunk N prepended to chunk N+1.
- Output: `list[str]`; caller assigns `chunk_idx` in order.
- Pure function, no side effects, unit-testable against handcrafted fixtures.

### 4.3 Keyword filter — `src/jurist/ingest/caselaw_filter.py`

```python
HUURRECHT_TERMS = ("huur", "verhuur", "woonruimte", "huurcommissie")

def passes(body_text: str, terms: tuple[str, ...] = HUURRECHT_TERMS) -> bool:
    lower = body_text.casefold()
    return any(term in lower for term in terms)
```

Lenient substring match (not word-boundary) — catches `huurprijs`, `huurders`, `verhuurder`, `woonruimten`, etc., without a morphology/lemmatization list. `caselaw_profiles.py` binds term tuples to profile names so M3b (or a future milestone) can extend without touching filter code.

**What we are NOT filtering on:**
- Morphology (`huur-` prefix detection with regex word boundary) — rejected; substring catches inflections cheaply.
- `pacht` — adjacent regime, but out of huurrecht proper for v1.
- Instantie filter — kept permissive; all `civielRecht_verbintenissenrecht` cases regardless of court (kantonrechter, hof, RB) are candidates.

## 5. Embedder — `src/jurist/embedding.py`

```python
class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3") -> None: ...

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        """Returns (N, 1024) float32, L2-normalized."""
```

- Wraps `sentence_transformers.SentenceTransformer`. Returns numpy arrays (not Python lists). The ingester calls `.tolist()` on each row before constructing `CaseChunkRow` for LanceDB insertion (`CaseChunkRow.embedding: list[float]`).
- `normalize_embeddings=True` passed to underlying `encode()`.
- **First-run UX.** `Embedder()` constructor triggers HuggingFace download (~2.3 GB) via the sentence-transformers lazy load. Called as the first pipeline stage in `run_ingest()` so the download is foregrounded, not hidden behind other work. Subsequent runs hit `~/.cache/huggingface/hub/` automatically.
- **Shared with M3b.** The future case retriever imports the same class to encode the query vector. One module, no duplication.
- **Module deterministic check** (integration test, RUN_E2E gated): embedding the same Dutch string twice returns bit-equal vectors. Parent spec §11 M3 requirement.

## 6. Vector store — `src/jurist/vectorstore.py`

```python
class CaseStore:
    def __init__(self, lance_path: Path) -> None: ...

    def open_or_create(self) -> None:
        """Open existing table, or create empty one with CaseChunkRow schema."""

    def contains_ecli(self, ecli: str) -> bool: ...

    def all_eclis(self) -> set[str]: ...

    def add_rows(self, rows: list[CaseChunkRow]) -> None:
        """Batch append. Deduplicates on (ecli, chunk_idx)."""

    def query(
        self,
        vector: np.ndarray,
        *,
        top_k: int = 20,
        subject_filter: str | None = None,
    ) -> list[CaseChunkRow]:
        """Cosine top-K. Used by M3b, but method shipped in M3a for round-trip tests."""

    def drop(self) -> None:
        """--refresh path."""
```

No abstract interface over this — parent spec §15 decision #12 keeps CaseStore concrete (only the KG has a stated swap path). LanceDB is the single implementation.

The `query()` method ships in M3a only so round-trip unit tests can verify cosine-top-K behavior. M3b wires it to the retriever agent.

## 7. Caselaw profiles — `src/jurist/ingest/caselaw_profiles.py`

Nod to the user goal "extendable to other rechtsgebieden":

```python
@dataclass(frozen=True)
class CaselawProfile:
    name: str
    subject_uri: str
    keyword_terms: tuple[str, ...]

PROFILES: dict[str, CaselawProfile] = {
    "huurrecht": CaselawProfile(
        name="huurrecht",
        subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
        keyword_terms=("huur", "verhuur", "woonruimte", "huurcommissie"),
    ),
}
```

Only `huurrecht` is populated in M3a. Adding a second profile is a dict-entry diff, not a refactor.

## 8. Testing

### 8.1 Unit

**`tests/ingest/test_caselaw_fetch.py`**
- Paginates the list endpoint correctly (cursor advances by `max`; terminates on empty page).
- Polite User-Agent header present.
- Disk-cache hit short-circuits re-fetch.
- Non-200 → one retry → skip with WARNING (use a stdlib `http.server` fixture).

**`tests/ingest/test_caselaw_parser.py`**
- Against committed fixture XMLs: extracts ECLI, date (ISO), court, subject_uri, zaaknummer, modified, URL, body_text.
- Handles sparse fixture (missing `<dcterms:abstract>`, missing zaaknummer).
- Body text strip: no XML tags, whitespace collapsed, paragraph breaks preserved.

**`tests/ingest/test_caselaw_filter.py`**
- Hand-crafted bodies: keyword present → True; absent → False; case-folding works; empty body → False.

**`tests/ingest/test_splitter.py`**
- 500/50 chunks; each ≤500 words; overlap correct.
- Paragraph-preserving for small corpus.
- Long-paragraph → sentence split.
- Pathological single-sentence >500 words → char-split fallback.
- Dutch abbreviation list respected (no false sentence break on `art.`, `Hof`).

**`tests/ingest/test_caselaw.py`**
- Smoke: `run_ingest()` with mocked fetch + mocked encoder; verifies stage order, counts, idempotency, `--refresh` semantics.

**`tests/embedding/test_embedding.py`**
- Mocked `SentenceTransformer` returning deterministic (hash-based) 1024-d unit vectors. Verifies normalization + batch handling. Real model determinism check is integration-only.

**`tests/vectorstore/test_vectorstore.py`**
- In-memory LanceDB: `add_rows` → `contains_ecli` → `query` → `drop` round-trip.
- Cosine top-K correctness on known vectors.
- Deduplication on `(ecli, chunk_idx)`.

### 8.2 Integration — `tests/integration/test_m3a_ingestion_e2e.py`

Gated on `RUN_E2E=1`. Real rechtspraak.nl + real bge-m3.

- Run `run_ingest(profile="huurrecht", max_list=10, since="2025-01-01")`.
- Assert: ≥1 unique ECLI in LanceDB; all rows have 1024-d unit-norm embeddings; every row's body contains a huur-term.
- Re-run without `--refresh` → "0 new" reported; no duplicate rows.
- `--refresh` → wipes and re-ingests.
- Determinism: embed `"huurverhoging per jaar"` twice; bytes equal.

### 8.3 Committed fixtures

`tests/fixtures/caselaw/` — 2–3 real public ECLI content XMLs, one per shape variation:
- `ECLI_NL_RBxxx_2025_yyy.xml` (kantonrechter huurprijs case, with zaaknummer + abstract)
- `ECLI_NL_GHxxx_2025_zzz.xml` (gerechtshof, different RDF structure)
- `sparse_case.xml` (hand-trimmed: missing `<dcterms:abstract>`, etc., for robustness tests)

No pre-built LanceDB committed. Integration tests build it lazily; unit tests use mocked encoder. Keeps the repo binary-free.

## 9. Observability

Stdlib `logging`, stderr sink:

- **INFO** at each stage transition with running counts.
- **INFO** once at ingester start: model name, HF cache path, profile selection.
- **WARNING** per-ECLI parse/fetch failure (skip that ECLI, continue).
- **ERROR** on unrecoverable failure (LanceDB open fails, HF model download fails).
- **DEBUG** per-ECLI filter decision with matched term (verbose mode only).

Example output:

```
[ingest.caselaw] loading BAAI/bge-m3 (cache: /home/x/.cache/huggingface/hub)
[ingest.caselaw] profile=huurrecht since=2024-01-01 subject=civielRecht_verbintenissenrecht
[ingest.caselaw] listing ECLIs… 12847 found
[ingest.caselaw] fetching 12847 ECLIs (from cache: 0, to download: 12847, workers=5)
[ingest.caselaw] WARN: ECLI:NL:… content 404, skipped (1/12847)
[ingest.caselaw] fetched 12846
[ingest.caselaw] filtering… 183 survived fence
[ingest.caselaw] chunked 183 cases → 892 chunks
[ingest.caselaw] embedding 892 chunks (batch=32)…
[ingest.caselaw] wrote 892 rows (127 unique ECLIs) to data/lancedb/cases.lance
[ingest.caselaw] done in 28m41s
```

## 10. Configuration

`src/jurist/config.py` additions:

| Var | Default | Purpose |
|---|---|---|
| `JURIST_CASELAW_PROFILE` | `huurrecht` | Selects subject_uri + keyword_terms |
| `JURIST_CASELAW_SUBJECT_URI` | (from profile) | Override |
| `JURIST_CASELAW_SINCE` | `2024-01-01` | `modified` date floor (ISO 8601) |
| `JURIST_CASELAW_MAX_LIST` | (unset) | Debug cap on ECLIs listed |
| `JURIST_CASELAW_FETCH_WORKERS` | `5` | Parallel content fetches |
| `JURIST_CASELAW_CHUNK_WORDS` | `500` | Chunker target |
| `JURIST_CASELAW_CHUNK_OVERLAP` | `50` | Chunker overlap |
| `JURIST_EMBED_MODEL` | `BAAI/bge-m3` | Encoder identity |
| `JURIST_EMBED_BATCH` | `32` | Embedder batch size |

All have CLI flag equivalents on `python -m jurist.ingest.caselaw`.

## 11. Dependencies

`pyproject.toml` gains:

```toml
dependencies = [
  # ...existing...
  "sentence-transformers>=3.0,<4",
  "lancedb>=0.13,<1",
]
```

Transitive pulls: `torch`, `transformers`, `huggingface-hub`, `pyarrow`, `numpy`. Net fresh-install size climbs by ~3 GB (dominated by torch).

No new HTTP library — fetching uses stdlib `urllib.request` + `concurrent.futures.ThreadPoolExecutor`, matching the statutes ingester pattern.

README is updated with a first-run heads-up: expect a few minutes of `uv sync`, followed by a one-time ~2.3 GB HuggingFace download on the first ingest.

## 12. Parent spec amendment

A single commit precedes M3a code, updating `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`:

1. **§8.2 rewrite** — new filter strategy: `subject=civielRecht_verbintenissenrecht` + `modified` date floor + local keyword fence. Delete the `rechtsgebied = "Huurrecht"` claim.
2. **§7.4 `CaseChunk` → `CaseChunkRow`** — rename, drop `rechtsgebied`, add `zaaknummer` + `subject_uri` + `modified`.
3. **§11 M3 split** — M3a (ingestion + LanceDB) and M3b (real case retriever). M3b acceptance criteria stay largely as written; M3a gets this spec's §15.
4. **§15 decisions log** — three new entries:
   - rechtspraak.nl open-data taxonomy has no huurrecht URI; corpus filtered via `civielRecht_verbintenissenrecht` + keyword fence (with the verified volumes).
   - M3 split into M3a/M3b mirroring M1/M2 ingest-then-retrieve rhythm.
   - LanceDB row schema extended: `zaaknummer`, `subject_uri`, `modified`.

The amendment is a prerequisite, not part of M3a's implementation commits.

## 13. Out of scope / deferred

- **Real case retriever agent (M3b).** Separate spec + plan.
- **Huurcommissie as a data source.** Publishes on `huurcommissie.nl`, not `rechtspraak.nl` open-data. A separate ingester against that site would broaden huurprijs-specific coverage; v2 scope.
- **BM25 over `<dcterms:abstract>`** — abstracts are often empty (`-`), so BM25 gives little signal. Rejected.
- **Morphology-aware keyword filter.** Substring match is sufficient.
- **Modified-timestamp change detection.** A changed uitspraak under an existing ECLI stays cached. V2 concern.
- **Bundling bge-m3 weights in the repo.** Legal/size issues; stick with HF download.
- **Async ingestion (`aiohttp` etc.).** ThreadPoolExecutor is enough for ~20k sequential GETs.

## 14. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Keyword fence yields too few huurprijs-specific cases to power M3b retrieval | Medium | Stats logged per stage. If <50 unique ECLIs survive, widen fence (add `pacht`, `huisvest`) or drop date floor. Decision deferred to M3b. |
| bge-m3 HF download fails on demo laptop | Low | `HF_ENDPOINT` env override available; README documents mirror option. Model is cached once downloaded. |
| rechtspraak.nl returns inconsistent XML for some ECLIs | Medium | Parser is lenient per-field; missing fields → empty-string defaults with WARNING. Sparse-case fixture in unit tests. |
| LanceDB misbehaves on Windows (path casing / locking) | Low | Test on demo host; fallback to SQLite+FAISS is not pre-designed but is feasible. Not expected based on LanceDB's Windows support. |
| First-run `uv sync` times out on slow network (torch is ~2 GB) | Low | README advises `uv sync` before ingestion. Separate failure surface. |
| rechtspraak.nl rate-limits us at 5-way concurrency | Low | One-shot batch; 5 workers is modest. Polite User-Agent. If 429s appear, drop to 2 workers. |

## 15. Acceptance criteria

M3a is done when:

1. Parent spec amendment commit landed on `master` (§12).
2. `uv run python -m jurist.ingest.caselaw` runs end-to-end on a fresh clone. No `ANTHROPIC_API_KEY` required. No LLM calls in the ingestion path.
3. LanceDB at `data/lancedb/cases.lance` contains ≥100 unique ECLIs, each with ≥1 chunk row, every row carrying a 1024-d unit-norm embedding, non-empty `subject_uri`, and keyword fence satisfied.
4. Re-running without `--refresh` is idempotent (hits disk cache; 0 new rows; reports quickly).
5. `--refresh` wipes disk cache + LanceDB and rebuilds cleanly.
6. Unit tests green across: parser, filter, splitter, fetch-with-cache, mocked embedder, vectorstore round-trip.
7. `RUN_E2E=1 uv run pytest tests/integration/test_m3a_ingestion_e2e.py` passes: small live ingest (~10 ECLIs), bge-m3 determinism.
8. `uv run ruff check .` clean.
9. README updated: first-run model-download note, ingestion command, expected wall-clock, re-run behavior.

## 16. Decisions log (M3a-specific)

| # | Decision | Alternatives considered | Reason |
|---|---|---|---|
| 1 | Split parent-spec M3 into M3a (ingestion) + M3b (retriever) | Keep as one milestone per parent spec | Mirrors M1→M2 rhythm; ingestion and retrieval have distinct risk profiles; each gets a clean "done" gate. |
| 2 | Source filter: `civielRecht_verbintenissenrecht` + date + local keyword fence | Parent spec's `rechtsgebied=Huurrecht` | The huurrecht URI does not exist in rechtspraak.nl's open-data taxonomy (verified). Verbintenissenrecht is the legal parent; keyword fence restores precision. |
| 3 | No `--download-model` CLI step | Separate pre-download command; lazy-on-first-embed | Ingester runs once per developer; warming the model at stage-0 foregrounds the download without extra ceremony. |
| 4 | Sync + ThreadPoolExecutor for fetch | asyncio / aiohttp | Batch job; no need for a third execution model in the codebase. Matches statutes ingester. |
| 5 | Lenient substring keyword fence (no morphology) | Word-boundary regex; lemmatization | Substring catches inflections cheaply; civielRecht_verbintenissenrecht already narrows scope. False positives negligible. |
| 6 | LanceDB row schema adds `zaaknummer`, `subject_uri`, `modified` vs parent spec | Parent schema verbatim | `zaaknummer` needed for display; `subject_uri` preserves extensibility; `modified` supports freshness weighting later. |
| 7 | `CaselawProfile` registry for multi-rechtsgebied extensibility | Hardcode huurrecht terms | User goal: "extendable to other areas". Minimal cost now; drop-in add later. |
| 8 | No pre-built LanceDB committed to repo | Check in small fixture DB | Binary artifact fragility; mocked encoder covers unit tests; integration test builds lazily. |
| 9 | No `httpx` / `aiohttp` dep | Either as replacement for urllib | `urllib.request` + `ThreadPoolExecutor` is enough; match existing pattern. |
| 10 | Target corpus: 2024-cutoff, no hard size cap, lenient fence | 300 hard cap (parent spec); strict 2-tier fence | User direction: prefer broader corpus with noise for robustness evaluation + extensibility. |
| 11 | Rename `CaseChunk` → `CaseChunkRow` | Keep parent's name | Disambiguates from `CitedCase` (retrieval output); `Row` signals LanceDB storage. |
| 12 | `uitspraken.rechtspraak.nl/api/zoek` not used | UI-backing API gives full-text search | WAF/CSRF blocks scripted clients (verified 411/302 redirect). Undocumented; brittle. |

---

*End of spec.*
