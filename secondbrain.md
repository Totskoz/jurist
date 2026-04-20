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

## Environment quirks worth capturing (not yet in CLAUDE.md)

- **Zombie python3.11 processes on port 8766.** Observed 5 stale processes from prior sessions holding the port and serving the old `FAKE_KG`, which made the frontend show 9 nodes after M1 shipped. `tasklist | grep python` + `taskkill /F /PID <pid>` to clean up. Consider adding to CLAUDE.md "Environment quirks" or moving the API to a fresh port.
