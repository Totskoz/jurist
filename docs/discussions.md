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

---

## M4 post-eval — external-review pass (2026-04-22)

After M4 landed and produced substantively-correct Dutch answers on the locked
question (see `docs/evaluations/2026-04-22-m4-e2e-run.md`), the user fed one
rendered answer into both Claude and Gemini for independent review and shared
their verdicts. This section triages that feedback against what the pipeline
actually does, and catalogues the answer-quality limitations the review exposed
that the mechanical eval did not. M5 is scoped to address a subset; the rest
are deferred with reasons.

**Important framing.** The reviewers do **not** see our corpus, our grounding
mechanism, or our system dates. Their critique reads the rendered answer like a
legal reviewer reads a junior's memo: substantively skeptical. Several of their
claims turn out to be **reviewer training-data artefacts** rather than real
defects — cases where their training lags our corpus snapshot. Others are
real. Both get written down honestly.

### Verified findings — real system defects (drive M5)

| # | Finding | Root cause | Addressed by |
|---|---|---|---|
| AQ1 | Synthesizer stacks beding-route (art. 7:248 lid 4 → Huurcommissie binnen 4 mnd na ingang) and voorstel-route (art. 7:253 bezwaar vóór ingang) as sequential steps in the `aanbeveling`. These apply to mutually exclusive huurtypes. | Synthesizer system prompt has no procedure-routing rule; decomposer doesn't emit a huurtype hypothesis for the synth to branch on. | M5 — `DecomposerOut.huurtype_hypothese ∈ {sociale, middeldure, vrije, onbekend}`; synth prompt branches ("Als … is: X. Als … is: Y.") on `onbekend` and single-path on known. |
| AQ2 | Synthesizer echoes only the statutory "nietig voor het meerdere" even when retrieved Rotterdam/Amsterdam rulings apply Richtlijn 93/13/EEG to conclude **algehele vernietiging**. Material consumer-law angle lost between retrieval and prose. | Case chunks carry the EU-directive reasoning but the synth prompt has no escalation rule; the statutory frame dominates. | M5 — prompt rule: if any cited `chunk_text` contains "Richtlijn 93/13" / "oneerlijk beding" / "algehele vernietiging", `korte_conclusie` + `aanbeveling` must surface the fully-void consequence. |
| AQ3 | Reviewer named ECLI:NL:HR:2024:1780 as a key 29-nov-2024 HR arrest on oneerlijke huurverhogingsbedingen. Not present in `cases.lance` (0 chunks). We do have 33 distinct HR ECLIs including sibling late-2024 arrests (1663, 1709, 1761, 1763) but not 1780. | Combination of the `modified≥2024-01-01` floor + the huur-fence `{huur, verhuur, woonruimte, huurcommissie}` missed this arrest; unknown whether the ECLI itself even exists (reviewer recollection unverified). | M5 — fence expansion `{huurverhoging, huurprijs, indexering, "oneerlijk beding", "onredelijk beding"}`; curated priority-ECLI sidecar top-up; one live audit task against rechtspraak.nl to verify (or disprove) ECLI:NL:HR:2024:1780 and identify other late-2024 HR huur arrests not yet indexed. |
| AQ8 | System is corpus-scoped to huurrecht but the behaviour is not — on a non-huur question, the pipeline still dumps a forced `emit_answer` over weak grounding. Today nothing emits a structured refusal. | `StructuredAnswer` has no refusal kind; forced-tool synthesizer cannot decline; retrievers don't expose a low-confidence signal. | M5 — `StructuredAnswer.kind ∈ {answer, insufficient_context}`; `StatuteOut.low_confidence` + `CaseRetrieverOut.low_confidence` (cosine-threshold-based); synth prompt rule to emit refusal when both signals trip or when judged ungrounded. |

### Deferred findings — real but out of M5 scope

| # | Finding | Why now is wrong time |
|---|---|---|
| AQ4 | Corpus statute snapshot has no temporal awareness. The rendered 7:248 / Uhw 10 text is correct for today (2026-04-22) but the Wet betaalbare huur revision per 1 juli 2026 will stale it. | Needs a re-ingest discipline + version markers on KG nodes. Tracked separately; not a one-PR fix. |
| AQ5 | No ministeriële regeling corpus. Actual annual % caps (sociale 4,1 / middel 6,1 / vrij 4,4 per 2026) live outside wetteksten + rechtspraak. | Requires a third ingest source with different structure. Real milestone in its own right. |
| AQ6 | Grounding verifies "quote is in chunk_text" — not "chunk_text is from the named case's holding". A chunk could be boilerplate quoted from an earlier ruling; we'd still attribute it to the outer case. | Provenance per quote needs parser-level XML structure (section tags, footnotes). M3a's current chunker is section-blind. Non-trivial ingest rework. |
| AQ7 | Two back-to-back runs on the same question produce different citation sets. AQ1's procedure fix will tighten the recommendation; the citation-picking variability itself is not the locked-question showstopper. | Partly absorbed by AQ1. Pure variability reduction (temperature / preferred sources) costs more than the demo return justifies. |

### Rejected findings — reviewer training-data artefacts

Two specific reviewer claims were **verified against our corpus and rejected** as
reviewer-side errors. Documented here so future review passes don't re-ingest
the same mis-critique:

- **Claude claimed art. 7:248 BW citation is a "samengesteld, niet-bestaand
  citaat"** — specifically that our quote containing *"artikel 10 lid 2 of
  artikel 10a"* is fabricated. **False.** That exact string is in
  `data/kg/huurrecht.json` (line 512), sourced from BWB BWBR0005290 at the
  2026-01-01 snapshot. The phrasing reflects the post-Wet-betaalbare-huur
  (2024) renumbering. Claude's training pre-dates this amendment; its expected
  wetstekst is the pre-2024 version. **Our corpus and the rendered answer are
  correct.**

- **Claude claimed art. 7:265 BW should contain "ten nadele van de huurder"** —
  i.e. that the article establishes semi-dwingend recht. **Not in this article.**
  Our corpus has *"Van de bepalingen van deze onderafdeling kan niet worden
  afgeweken, tenzij uit die bepalingen anders voortvloeit"* (line 745). The
  "ten nadele" formulation exists elsewhere in Boek 7 (notably 7:209 for
  opstalrecht-in-huur and 7:242 for gebreken), not in 7:265. Reviewer appears
  to have confused articles. Our corpus matches BWB.

- **Claude claimed Uhw art. 10 formula (CPI + 1 procentpunt) is "achterhaald"
  for 2026.** On date (2026-04-22) this is still the operative formula. The
  Wet betaalbare huur does change it per 1 juli 2026 (ca. 10 weeks hence), at
  which point our corpus goes stale unless re-ingested. This is AQ4, not a
  current defect.

### What this pass actually tells us about the system

Three generalisable signals beyond the specific findings:

1. **Grounding works; the reviewer couldn't find a hallucinated citation.**
   Every quote in the rendered answer appeared verbatim in our corpus body
   because `verify_citations` forces it. The two reviewer complaints about
   "fabricated" statute text were reviewer-side confabulation, not synth
   hallucination. The three-layer defence (schema enum → pydantic →
   substring) holds.

2. **Retrieval-to-reasoning propagation is the soft seam.** AQ2 is the
   clearest case: the Rotterdam oneerlijk-beding chunk *is* in the user
   message Sonnet sees, but Sonnet's synth-prompt doesn't instruct it to
   escalate when that signal appears. Closed-set grounding stops the model
   from inventing material; it doesn't make the model *use* all the material
   in front of it. That's a prompt-engineering problem, not a grounding one.

3. **Scope containment is behavioural, not just textual.** The system is
   structurally a huur-only engine, but without AQ8 it won't tell a user
   that. A car-insurance question today would produce a confidently-wrong
   answer with real-looking huurrecht citations stitched to it. The fix is
   not to make the system broader — it's to make it *honest about being
   narrow*. AQ8 delivers that without corpus growth.

### Informs

- M5 spec: `docs/superpowers/specs/2026-04-22-m5-answer-quality-design.md`
- M5 plan: `docs/superpowers/plans/2026-04-22-m5-answer-quality.md`
