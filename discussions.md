# discussions

Design decisions worth defending in the DAS presentation. Each entry: the alternative that was on the table, what I picked, and why — so I can walk an interviewer through the reasoning instead of just the result.

---

## M2 statute retrieval: tool-use loop over KG vs. HyDE-style "guess the statute"

**The alternative considered.** Instead of a Sonnet tool-use loop that walks the statute KG, have an agent generate what the relevant statute *probably says* (a "hypothetical document"), embed that, and retrieve against the real statute corpus via vector similarity. This is the HyDE pattern (Gao et al., 2022). Fewer LLM calls, simpler pipeline, no tool-use harness.

**What I picked.** Sonnet 4.6 tool-use loop over the huurrecht KG, with `search_articles`, `get_article`, `follow_cross_ref`, `done`. Full article catalog (~218 rows: id + label + title + summary) lives in a cached system prompt so the model can pick seeds directly without an always-on initial search.

**Why — the four reasons I'd give in the interview.**

1. **The traversal *is* the explainability story.** M2 emits `node_visited` / `edge_traversed` events that animate the KG panel — you literally watch the agent follow 7:248 → 7:252a, hop into the Uhw, and return with a grounded citation path. That's the differentiator for a legal-insurance use case where a claims handler has to *trust* why a specific article was cited. HyDE collapses that into one opaque batch retrieval; the KG panel becomes decorative.
2. **Statute wording is precise, and hallucinated article IDs are a known failure mode.** Dutch civil-code article numbers are dense (7:248 lid 2 vs. 7:248a vs. 7:252a). A hypothetical-statute generator will invent confident-sounding but wrong IDs and phrasing — a failure I've already seen in this project (fabricated BWB IDs during spec drafting, which is why "verify external IDs" sits in my working memory). The tool-use path never guesses: it picks from a real catalog and reads real article text before citing.
3. **The motivation for HyDE doesn't apply at this corpus size.** HyDE exists to avoid loading a large corpus into context. ~218 articles × a short summary each fits comfortably in a cached system prompt. The model gets the corpus map for free; "guessing to avoid reading" solves a problem we don't have.
4. **The asymmetry between statutes and cases is deliberate, not accidental.** On the case side (M3) I *do* use semantic retrieval — bge-m3 + Haiku rerank — because case law is unstructured, large, and doesn't have a citation graph. Collapsing both retrievers onto HyDE would erase a design choice that actually matches the shape of each data source: graph-walk for structured and citation-linked, vector search for unstructured judgment text.

**The middle options I'd flag as future work.**

- *Lightweight seeding.* Keep the tool-use loop, but let the decomposer emit 2–3 paraphrased "what statute would answer this" queries that seed the first `search_articles` call. Cheap, still animates the KG, gives Sonnet warmer opening hooks than a cold catalog scan. Worth measuring after M2/M4 land.
- *Decomposer fan-out with per-concept HyDE retrievers.* More ambitious variant: the decomposer splits the question into its distinct legal concepts (e.g. "maximum rent increase percentage", "social vs. liberalised sector", "indexation clause"), and for each concept a dedicated retriever agent generates a hypothetical statute passage and vector-searches against the real corpus. Results get merged and deduped before the synthesizer. Likely better recall on multi-concept questions than a single tool-use loop, and fans out naturally in parallel. Tradeoff: it collides with two deliberate v1 decisions — sequential agents and a single-threaded trace — so the KG panel would need to show N concurrent retrievers, which is a UX redesign, not just a retrieval change. Revisit when we have questions that genuinely span multiple rechtsgebieden or when the corpus is wide enough that a single loop can't cover it in ≤15 iterations.

**Where HyDE would genuinely win (and where I'd switch).** A v2 scope that widens the corpus substantially — Besluit huurprijzen + wider huurrecht + jurisprudence commentary, thousands of fragments — at which point the catalog no longer fits in cache and the article set is too large for the model to pick seeds directly. Not this version.

## Why agentic-RAG-on-KG over the broader retrieval landscape (GraphRAG, plain agentic RAG, HyDE)

**The alternatives considered.** Beyond the HyDE comparison above, two other paradigms come up in interviews:

- **GraphRAG (Microsoft-style).** Run community detection on the graph, pre-summarize each community with an LLM, retrieve summaries first then drill into nodes. Designed for large unstructured corpora (a Discord dump, a wiki) that have *been turned into* a graph by an extraction pipeline.
- **Plain agentic RAG (no graph).** Sonnet with a single `search` tool over a flat embedding index, looping until it has enough context. The standard 2024 pattern.

**What I picked.** Agentic RAG *over* the KG with lexical search and structural traversal tools (`search_articles`, edge-following, `done`). The graph is authored from statute structure (titel → afdeling → artikel + cross-refs), not extracted by an LLM. The catalog of 218 articles sits in the cached system prompt so the model has the full corpus map for free.

**Why — paradigm by paradigm.**

1. **vs. GraphRAG.** GraphRAG's community summaries solve the "what does this body of text contain?" problem on corpora too large to read. At 218 nodes the model can already see every article title + summary in one cached prompt — there's nothing to summarize *about*. Worse, community summaries are themselves LLM outputs, which means citation grounding now traces through a fabricated layer. For a legal-insurance use case where every cited article must be the actual statute, that's the wrong direction. GraphRAG earns its keep when the graph itself was derived (entities + relations extracted from prose); ours is authoritatively constructed from BWB structure, so the indirection is pure overhead.
2. **vs. plain agentic RAG.** Drop the graph and you keep the agentic loop but lose the *traversal* — no `node_visited` / `edge_traversed` events, no animated path through the corpus, no "the agent followed 7:248 → 7:252a → Uhw" story. The KG panel becomes a static decoration. For a portfolio demo whose differentiator is *visible reasoning over structured law*, deleting the graph deletes the demo. (Also: at 218 articles, the cached catalog already gives Sonnet a structural map — flattening that to a vector index throws away signal we already have for free.)
3. **vs. HyDE.** Covered in detail above. Short version: HyDE invents plausible-sounding statute IDs and phrasing, which is the exact failure mode we can't afford on Dutch civil-code article numbers (7:248 vs 7:248a vs 7:252a).

**The asymmetry, restated.** Statutes get agentic-on-KG with lexical search because they're structured, citation-linked, and small. Cases (M3) get embeddings + rerank because they're unstructured, large, and have no citation graph. Same agentic loop philosophy, different retrieval primitives matched to data shape.

**Fallback ladder if M2 recall disappoints.** Documented in `secondbrain.md` — query expansion (HyDE-lite seeding) is the cheap first step, vector tool over articles is step two, real HyDE is step three, GraphRAG stays off the list at this scope.
