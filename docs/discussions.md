# Discussions — design + implementation notes

Running log of non-obvious decisions, rationale, and findings across milestones.
Complements the authoritative design spec (`docs/superpowers/specs/...`) and
implementation plans (`docs/superpowers/plans/...`) with context that would
otherwise be lost to git history.

---

## M3a — Caselaw ingestion (landed 2026-04-22)

### Final corpus stats

From the first full ingest run against live rechtspraak.nl. Total wall clock
20.7 hours, with stage 8 (embedding) absorbing ~95% of that on a 16 GB
Ryzen 7 5800H — see "Observations for M3b" below for throughput analysis.

| Stage | Count | Notes |
|---|---|---|
| Listed (from `/uitspraken/zoeken`) | 19,841 | `subject=civielRecht_verbintenissenrecht`, `modified>=2024-01-01` |
| Skipped at resume gate | 11 | Already indexed from earlier 20-ECLI smoke test |
| Fetched XML | 19,830 | 5-way parallel via `ThreadPoolExecutor`; 19,829 cache hits on the final run (cache built up across earlier retry cycles) |
| Parse failures | 4 | 0.02% — malformed XML at line 2 col 39 (likely BOM/encoding); ECLIs `RBAMS:2023:295`, `RBGEL:2025:3408`, `RBDHA:2026:1804`, `RBLIM:2026:1366`; skipped |
| Parsed successfully | 19,826 | |
| Passed huur fence | 6,088 | 31% hit rate on verbintenissenrecht — confirms huur is a material subset |
| Chunks generated | 47,202 | ~7.8 chunks/case, 500-word target + 50-word overlap |
| **Unique ECLIs in LanceDB (final)** | **6,099** | 6,088 new + 11 resumed from smoke test |
| **Rows written** | **47,202** | One row per chunk; 1024-d bge-m3 embedding per row |

Total wall clock: **74,437 s (20.7 h)**. Store: `data/lancedb/cases.lance`
(pyarrow schema; 1024-d bge-m3 embeddings, L2-normalized).

### Why this shape?

**Why `civielRecht_verbintenissenrecht` and not `huurrecht`?**
Live probing of `https://data.rechtspraak.nl/Waardelijst/Rechtsgebieden`
(2026-04-21) proved no `#huurrecht` subject URI exists in rechtspraak.nl's
open-data taxonomy. `civielRecht_verbintenissenrecht` is huurrecht's
taxonomic parent (verbintenissen = obligations, of which tenancy is one
category). The 31% fence hit rate is the legal-corpus answer: roughly a
third of Dutch civil-obligations judgments touch huur terms.

**Why `modified >= 2024-01-01`?**
Scales the corpus to a tractable ~20k judgments while staying recent.
Rechtspraak.nl has ~53k total verbintenissenrecht entries; anything older
than 2024 is less likely to cite current BW articles. A production system
would expand this floor.

**Why a lenient substring fence over a Dutch NLP classifier?**
YAGNI for a demo. The terms `{huur, verhuur, woonruimte, huurcommissie}`
catch the obvious inflections (huurder, huurders, huurprijs, verhuurder)
without a morphology list. False positives (a case that mentions "huur" in
passing but isn't about tenancy) are acceptable — the retriever's rerank
stage in M3b will weight by actual semantic relevance.

**Why 500-word chunks + 50-word overlap?**
bge-m3 has an 8192-token context but embedding quality degrades for very
long inputs. 500 words ≈ 700-1000 tokens — well within the sweet spot.
Overlap preserves context across chunk boundaries (a cited article mentioned
at chunk boundary doesn't get truncated).

### Key decisions (chronological)

| # | Decision | Rationale |
|---|---|---|
| 1 | Split M3 into **M3a (ingest) + M3b (retriever)** | Mirrors M1→M2 ingest-then-retrieve rhythm; each half gets its own acceptance gate. |
| 2 | `CaseChunk` → `CaseChunkRow`; added `zaaknummer`, `subject_uri`, `modified` | Row-shape disambiguated from retrieval output (`CitedCase`). Extensibility fields support multi-rechtsgebied (Phase 2) + freshness weighting (Phase 3). |
| 3 | Use `civielRecht_verbintenissenrecht` + local keyword fence | Parent spec §8.2's `rechtsgebied=Huurrecht` was invalid (no such URI). Verified taxonomy + fence restores precision. |
| 4 | `CaselawProfile` registry (`src/jurist/ingest/caselaw_profiles.py`) | Adding `arbeidsrecht`, `familierecht`, etc. is a dict-entry diff — no pipeline refactor. |
| 5 | bge-m3 via `sentence-transformers` | Multilingual 1024-d, strong Dutch retrieval, local inference (no embedding API cost). Shared with M3b retriever. |
| 6 | LanceDB as embedded vector store | Zero-infrastructure, file-backed (`data/lancedb/cases.lance/`), pyarrow-native. Concrete class — no abstract interface (spec §15 decision #12). |
| 7 | Stdlib `urllib` + 5-way `ThreadPoolExecutor` for fetch | No new HTTP library; politely bounded concurrency. 5 workers turned out to trigger rate-limiting after ~10 min (see Bugs below). |
| 8 | One-task-one-commit TDD | Kept the 17-task plan auditable; each commit lands green tests + ruff clean. |

### Prod bugs caught during implementation

1. **URL fragment truncation in `list_eclis`.** `urllib.parse.urlencode(params, safe=':#/')` left `#` unencoded. When the subject URI contained a `#` (taxonomy fragment delimiter), `urlopen` treated it as a URL fragment and silently truncated the query — the `subject=` param was dropped server-side. Fixed by removing `#` from the `safe` set (commit `a0f8aef`). Caught only during real-endpoint testing for Task 10 fixtures; unit tests used URIs without `#`. Regression test added.

2. **LanceDB `list_tables()` return-type drift.** `lancedb>=0.30` returns a `ListTablesResponse` object; the `in` operator on it doesn't detect table presence. Original Task 13 code worked in unit tests because each test used a fresh instance (table never exists at `open_or_create`), but the idempotency test in Task 14 exposed the bug. Fixed with a `hasattr(table_list, "tables")` guard for forward compatibility (commit `9290da9`).

3. **Narrow exception catch in `fetch_content`.** The initial implementation caught only `urllib.error.URLError`. `http.client.RemoteDisconnected` (server-side TCP drop after ~10 min of sustained parallelism) is a sibling of URLError under `OSError` — it escaped the retry path and aborted the entire 19k-ECLI ingest. Fix broadened to `(OSError, HTTPException)` (commit `645e26e`) + added exponential backoff (2/4/8/16s, up to 5 attempts) for politer recovery (commit `adfb8fe`).

### Observations for M3b

- **bge-m3 on CPU is ~0.64 chunks/sec on this hardware** (16 GB Ryzen 7 5800H). Measured via `py-spy dump --locals` on the live process over a 38-minute window mid-run; matches the 14h-average back-computation. Full stage 8 took ~20 h wall clock — dominated by memory pressure (committed 27 GB against 16 GB physical), not FLOPs. On a machine with ≥32 GB RAM or a GPU, expect 20-80× faster. Retriever-time query embedding is 1 chunk → milliseconds regardless.
- **No progress logging was a mistake.** The first indication that stage 8 was making forward progress came from live `py-spy dump --locals` reads of `sentences_sorted` / `start_index` — not from the process itself. M3b (and any re-ingest) should thread a `show_progress_bar=True` or equivalent logging hook through `Embedder.encode` so the operator can see chunks/sec without attaching a debugger.
- **No checkpointing was also a mistake.** Stage 8 embeds all chunks in-memory, then stage 9 writes in one pass. A 20h process with zero persisted progress is a single point of failure — if it crashes at hour 19, everything is lost. A batched write loop (embed N chunks → write to LanceDB → repeat) would make the pipeline resumable at ≤N-chunk granularity.
- **31% huur-fence hit rate** means the retriever sees ~6k embedded ECLIs to search over — plenty of signal, not so much noise that rerank can't dedupe.
- **Average chunks/case (7.8)** means top-k=20 chunk retrieval translates to ~2-3 distinct cases after ECLI-dedup. Rerank stage will likely widen k to 30-50.
- **rechtspraak.nl is sensitive to sustained parallelism**; 5 workers is OK with retries but politer would be 2-3 for a re-ingest.
