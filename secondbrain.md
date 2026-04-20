# secondbrain

Parking lot for design ideas we've agreed on but aren't building yet. Not a spec. Not a plan. Just "don't make me rediscover this."

---

## KGPanel: progressive reveal + cited-subgraph collapse

**Problem.** With M1 loaded we render 218 nodes / 283 edges in one dagre LR layout. It's a wide, unfocused wall. M1.5 (Besluit huurprijzen + wider huurrecht corpus) will push this to ~400+. The current view doesn't tell the story of *this answer* — it just shows the corpus.

**Target shape: three modes.**

1. **Idle** (page load, no run active) — open question. Options:
   - (a) full corpus — today's problem
   - (b) empty "ask a question" placeholder
   - (c) anchored view: Art 7:248 + 1-hop neighbors (locked demo entry point)
   - *lean: (c), but decide after M2 when we see what real runs look like*
2. **Running** (question submitted, agents working) — progressive reveal driven by trace events:
   - `decomposer` emits `concepts` → fade graph, highlight nodes whose title/keywords match
   - `statute_retriever` emits `node_visited` → animate pan+zoom to that node, expand neighborhood
   - `edge_traversed` → arrowhead flow animation on the edge
3. **Finished** (`run_finished`) — fade uncited nodes to ~10% opacity, `fitView({ nodes: cited + 1-hop })`, plus a "show full corpus" toggle so it's reversible.

**Mechanics (when we build it).** React Flow's `setCenter(x, y, {zoom, duration})` drives the camera. Store already tracks `currentNodeId` from `node_visited`, so KGPanel can subscribe and animate on change. Needs a queue with ~500ms min dwell to keep rapid visits from feeling jittery. Use a light ~1.5× zoom — full zoom-to-single-node loses the "where am I in the corpus" map feel.

**Phasing (decided).**

- **Now / before M2 (~half a day):** finished-state collapse only. On `run_finished`, fade uncited to low opacity and `fitView` to cited subgraph. Add "show full corpus" toggle. Works against current fakes, removes the 218-node eyesore today.
- **After M2 lands:** per-step camera follow (queue, dwell tuning, edge flow animation), idle-state anchor. Reason: tuning pacing against the fake's canned 5-node walk is wasted effort — the real Sonnet tool-use loop will visit a different count with different timing per question.
- **After M4:** anything depending on decomposer `concepts` (pre-filter fade on concept emit).

**Open questions.**

- Idle state: (a)/(b)/(c) — pick after observing real M2 runs.
- Dwell time calibration — depends on real retriever pacing.
- Does the "cited subgraph" include cases or stay statute-only? (cases live in a separate panel today; might or might not want cross-links in the graph).

## M1.5 — corpus widening (deferred from M1)

Scope we dropped from M1 to keep it shippable:

- **Besluit huurprijzen woonruimte** — the correct BWB ID needs live verification (BWBR0003402 was the hallucination we caught; real ID unknown to us yet). Fetch + parse once confirmed.
- **Rest of BW7 Titel 4** — M1 only ingests all of BW7 Titel 4 already. Check whether any other *titels* of Boek 7 are relevant to huurrecht edge cases before widening further.
- **Cross-corpus extrefs** — currently we drop dangling edges that point at article IDs outside the loaded corpus. Widening the corpus will resolve some of these. Worth logging which edges get dropped so we know what's missing.

## M2 fallback ladder: what to try if Jaccard recall disappoints

We picked agentic tool-use over the KG with lexical (Jaccard) `search_articles` for M2. If on real runs the user's phrasing ("huur 15% verhogen") doesn't surface the right statutory terms ("huurprijswijziging", "huurverhoging", "puntentelling"), here's the upgrade path in order of cost:

1. **Query expansion (HyDE-lite).** Cheapest. Have the decomposer (M4) — or a one-shot Sonnet call before the loop — rewrite the user phrase into 2–3 statutory-vocabulary paraphrases. OR each through the existing `search_articles` and dedupe. No new index, no new tool, reuses everything. This is the "Lightweight seeding" middle option already noted in `discussions.md`.
2. **Add a `vector_search_articles` tool.** Build a bge-m3 embedding index over the 218 articles (we'll already have bge-m3 standing up for M3 cases — reuse it). Expose as a second retrieval tool alongside Jaccard; let Sonnet pick. ~218 vectors is trivial to host, in-memory or LanceDB.
3. **Real HyDE.** Generate a hypothetical statute passage, embed it, dense-retrieve. Only worth it once (2) is in place and still missing recall. Most useful when corpus widens past the point where the article catalog still fits in the cached system prompt.

**Skip: full GraphRAG.** Community detection + per-community summarization solves "what's in this giant corpus?" not "find the right article." At 218 nodes / 283 edges the model can already see the whole catalog in cache; community summaries add a layer of indirection without adding signal. Revisit only if M1.5 + cross-corpus extrefs push us past ~2k nodes *and* the questions start being thematic/global rather than article-specific.

## M2 cost + behaviour observations (from real runs on 2026-04-20)

Two real end-to-end runs of the locked question against the live API, plus token-size measurements. Noting these down so we don't re-derive them next time the cost conversation comes up.

**Baseline per-run profile.**

- ~90K tokens input, ~1.7K tokens output, ~32s wall clock end-to-end; statute retriever is ~26s of that across 3 model turns.
- At naive Sonnet 4.6 pricing (~$3 / $15 per MTok) that's ~$0.30 per question — reasonable for a demo.
- *Effective* cost depends on prompt-cache hit rate. With per-turn `cache_read_input_tokens` now logged (see `jurist.llm.client`), we can verify the cache is actually earning its 10%-of-miss discount. Until we check a live log, treat the $0.30 as an upper bound.

**Catalog trimming is the cheapest lever we haven't pulled.**

System prompt is 64,585 chars (~18-20K tokens) — 60%+ of the per-turn input. The catalog renders each article as `[<id>] "<label>" — <title>: <snippet[200]>`. Dropping `JURIST_STATUTE_CATALOG_SNIPPET_CHARS` cuts it hard:

| `snippet_chars` | catalog chars | approx savings |
| --- | --- | --- |
| 200 (default)   | 64,585 | — |
| 100             | 45,737 | ~30% |
| 60              | 37,701 | ~40% |
| 0 (title only)  | 26,173 | ~60% |

Pull the trigger when: cache telemetry shows we're paying cache-write more than we recover via cache-reads, OR the corpus widens past the point where 200-char snippets still fit comfortably (M1.5+ territory). One-line default change in `jurist.config`. No code changes elsewhere — the renderer already honours the setting.

**The retriever isn't really traversing the KG.**

In both observed real runs the model went: read catalog → fire parallel `get_article(id)` → `done`. It never called `search_articles`, `list_neighbors`, or `follow_cross_ref`. Rational behaviour: the catalog in the system prompt *is* the lookup index, so the neighbour/search/follow tools are redundant for questions where the relevant article_ids are already visible in the cached preamble.

Consequences:
- For the **demo narrative** ("Sonnet traverses the legal graph") this is weak — the KG is being used as a lookup table, not walked. The UI's `node_visited` animation still fires, so visually it looks like traversal.
- When the **corpus widens** past the cached-preamble budget (M1.5+), the catalog won't fit verbatim and the traversal tools will start to earn their keep. Revisit tool usefulness at that point rather than now.
- Not worth pruning the tools today — they're cheap to keep defined, and a sharper question (one where the right article isn't in the catalog's snippet) might still use them.

Related: `secondbrain.md#M2 fallback ladder` already covers the retrieval-quality upgrade path (HyDE-lite → vector tool → real HyDE). This observation is orthogonal: it's about whether the *existing* non-Jaccard tools are being exercised, not about whether we need more tools.

## Statute retrieval at full-corpus scale (beyond M1.5)

The catalog-in-system-prompt approach scales to maybe 10-20K articles before tokens get silly. Full Dutch statutory corpus is 1-2 orders of magnitude larger (BWB ≈ 40-60K regelingen, millions of articles). Sketching the architecture we'd pivot to when we outgrow the cached preamble — not building it now, but locking in the direction so we don't redo the thinking when M1.5+ work starts.

**Core insight.** Legal questions have strong domain locality: a rent dispute never needs to see tax law or criminal procedure. Don't make retrieval smart over "all Dutch law" — classify into a rechtsgebied first, then retrieve within it. Mirrors how human lawyers actually work ("dit is huurrecht → Boek 7 BW, navigeer daar").

**Layered architecture, cheapest lever first.**

1. **Rechtsgebied router (Haiku).** Classify the question into 1-3 of ~50 fixed rechtsgebieden (huurrecht, arbeidsrecht, consumentenrecht, …). Tiny prompt, near-free, ~1s. Fails soft: if uncertain, return top-3 and let downstream retrievers dedupe.
2. **Scoped catalog in system prompt** — current M2 pattern, narrowed to the router-selected rechtsgebied(en). One rechtsgebied is a few thousand articles max; stays cached.
3. **Vector search fallback** (bge-m3 + optional HyDE query expansion) when the question straddles areas, when router confidence is low, or when the right article isn't surfacing in the scoped catalog. Already item 2 in `§M2 fallback ladder`.
4. **Graph traversal** (M2's existing `get_article` / `follow_cross_ref`) works unchanged once seeded.

**Why not GraphRAG.** Community detection + per-community LLM summaries solve *"what's in this corpus?"* thematic questions, not *"find this exact article"* grounding. Legal answers cite article numbers; an indirection layer of summaries adds no signal and is expensive to build (thousands of communities to LLM-summarize). Already parked as "Skip" in `§M2 fallback ladder`; noting it again here because the full-corpus scaling conversation is where it keeps getting re-proposed.

**Why not pure HyDE.** HyDE is a *query-quality* trick, not a *scale* trick. It bridges user-phrasing / statute-phrasing gaps ("huur verhogen" ↔ "huurprijswijziging"); it does not solve "corpus won't fit in context" — vector search itself does. Keep HyDE as an optional rewrite step the retriever can fire when Jaccard/vector look like they missed, not as the retrieval backbone.

**Trigger points — what to build when.**

- **Now / M2:** nothing. 218 articles fits cached.
- **M1.5 (low thousands, still one rechtsgebied):** still fits. Watch catalog token budget; may trim `JURIST_STATUTE_CATALOG_SNIPPET_CHARS` (see `§M2 cost + behaviour observations`).
- **Multi-rechtsgebied:** build the router + scoped catalog (steps 1-2). This is the real architectural shift.
- **Full corpus:** add vector fallback (step 3). Also the point where the UI probably needs to surface *"this is huurrecht"* explicitly, because "did the router pick the right rechtsgebied?" becomes a user-visible failure mode.

**Open question.** Router taxonomy source — BWB's own classification, a textbook tableau, or DAS's internal rechtsgebied taxonomy? Lean: DAS's, since they already have one for their insurance products and the whole demo is pointed at DAS. Also avoids bikeshedding.

## Environment quirks worth capturing (not yet in CLAUDE.md)

- **Zombie python3.11 processes on port 8766.** Observed 5 stale processes from prior sessions holding the port and serving the old `FAKE_KG`, which made the frontend show 9 nodes after M1 shipped. `tasklist | grep python` + `taskkill /F /PID <pid>` to clean up. Consider adding to CLAUDE.md "Environment quirks" or moving the API to a fresh port.
