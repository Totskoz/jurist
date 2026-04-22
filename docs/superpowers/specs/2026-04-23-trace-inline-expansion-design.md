# Trace Inline Expansion — Design

**Date:** 2026-04-23
**Status:** Draft. Awaiting user review.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§7 UI / transport — event protocol)
**Related:**
- `docs/superpowers/specs/2026-04-22-frontend-redesign-design.md` (panel phase machine, `TraceLines` component)
- `docs/superpowers/specs/2026-04-22-history-tab-design.md` (snapshot persistence model — relied on here, not modified)

---

## 1. Context and goals

The panel's "redenering" (reasoning) disclosure — shown live under `RunningPhase`
and on demand under `AnswerReadyPhase → Toon redenering` — surfaces a rich
trace for the **statute retriever** (it streams pre-tool `agent_thinking`
deltas between loop turns) but near-nothing for the three forced-tool agents:

| Agent           | What renders today                                           |
|-----------------|--------------------------------------------------------------|
| decomposer      | `start` → `klaar` (2 lines)                                  |
| case retriever  | `case_found × 20` → `gekozen: ecli,ecli,ecli` → `klaar`      |
| synthesizer     | `bron X id` × N → `klaar` (no quote/explanation shown here)  |

The forced-tool silence is deliberate: the system prompts explicitly say
*"Geen vrije tekst"* so the model invokes the tool immediately and never
drifts. That design is **not** being revisited. The data each agent produces —
sub-questions, concepts, intent, huurtype, per-pick rerank reasons, per-citation
quotes and explanations — is already in the pipeline. It's just not rendered.

This spec replaces terse trace lines with **inline expansions**: multi-line,
indented sub-content rendered chronologically as part of the agent's trace
section. No new LLM calls, no extended thinking, no latency cost.

**Done when:**

1. Decomposer emits a `decomposition_done` event carrying sub-questions,
   concepts, intent, and huurtype; it renders as a multi-line block in the
   trace.
2. Case retriever's `reranked` event carries per-pick reasons; each pick
   renders as a `✓ ECLI — reason` sub-line under a "gekozen:" header.
3. Synthesizer's `citation_resolved` event carries quote + explanation;
   each citation renders as a three-line block: source id, quoted passage,
   arrow explanation.
4. All enrichments survive snapshot → localStorage-or-server → rehydrate
   round-trip; historic view of a past run renders identically to the live
   view at terminal time.
5. Snapshots written before this change (and events missing the new fields)
   fall back to today's terse rendering without throwing.
6. Manual run of the locked huur question shows the richer trace live and
   in the subsequent "Toon redenering" disclosure; clicking into history
   shows the same.

**Out of scope:**

- Extended thinking on any forced-tool call.
- Collapsibility / per-agent expand-collapse UI (flat rendering is fine at
  this density; add later if needed).
- New styling beyond indentation + a slightly dimmer sub-line color.
- Changes to the live `RunningPhase` Sonnet-thinking block for the statute
  retriever (stays exactly as-is).
- Changes to the final structured-answer view (`Relevante wetsartikelen` /
  `Vergelijkbare uitspraken` sections in `AnswerReadyPhase`). Those already
  show quotes and explanations; the trace view duplicates the data there
  for timeline context, not to replace the structured view.

## 2. Principles

- **Surface captured reasoning, don't generate new reasoning.** Every new
  rendered field must already exist somewhere in the agent's output (tool
  input, final typed payload) before this change. Zero LLM cost.
- **Event-driven, not structure-derived.** Each render reads from a
  TraceEvent payload, not from `finalAnswer` / `agent_finished.data`, so
  rendering stays chronological and the same logic serves the live view
  and the historic replay.
- **Additive-only event evolution.** New fields are added to existing
  events' `data` dicts; old consumers ignore them. The only new event type
  is `decomposition_done`, which `runStore.apply()` picks up via its
  existing `default:` fall-through. No schema migration.
- **Graceful degradation on missing fields.** A snapshot written before
  this change (or any event with a missing field for any reason) falls
  back to today's single-line rendering. No hard assertions.

## 3. Architecture overview

```
┌────────────────┐      ┌──────────────────────┐      ┌────────────────┐
│  agent (py)    │ ───► │  TraceEvent (SSE)    │ ───► │ runStore (ts)  │
│  emits event   │      │  data:{...enriched}  │      │ traceLog += ev │
│  with extra    │      │                      │      │ (default case) │
│  data fields   │      └──────────────────────┘      └───────┬────────┘
└────────────────┘                                            │
                                                              ▼
                                                   ┌──────────────────────┐
                                                   │  TraceLines.tsx      │
                                                   │  switch on ev.type,  │
                                                   │  render multi-line   │
                                                   │  when fields present │
                                                   └──────────────────────┘

                                     persistence:
                                     runStore.archiveCurrent → toSnapshot
                                       → PUT /api/history (opaque snapshot)
                                       → disk, then reloaded on demand
```

All flow is generic: the event-type → render mapping is the only place that
needs per-agent knowledge. Persistence is type-opaque end-to-end, so new
fields ride along without touching `snapshot.ts`, `historyApi.ts`, or the
backend `/api/history` endpoint.

## 4. Backend changes

### 4.1 Decomposer — new `decomposition_done` event

`src/jurist/agents/decomposer.py::run` currently yields:

```python
yield TraceEvent(type="agent_started")
out = await _decompose_with_retry(...)
yield TraceEvent(type="agent_finished", data=out.model_dump())
```

Add one event between the retry and the finisher:

```python
out = await _decompose_with_retry(...)
yield TraceEvent(type="decomposition_done", data={
    "sub_questions": out.sub_questions,
    "concepts": out.concepts,
    "intent": out.intent,
    "huurtype_hypothese": out.huurtype_hypothese,
})
yield TraceEvent(type="agent_finished", data=out.model_dump())
```

No change to the Haiku call, the tool schema, or the regen path.

### 4.2 Case retriever — enrich `reranked` with per-pick reasons

`src/jurist/agents/case_retriever.py::run` currently yields:

```python
yield TraceEvent(type="reranked", data={"kept": [p.ecli for p in picks]})
```

Change to:

```python
yield TraceEvent(type="reranked", data={
    "picks": [{"ecli": p.ecli, "reason": p.reason} for p in picks],
    "kept": [p.ecli for p in picks],  # back-compat
})
```

Keeping `kept` preserves any consumer that reads the ECLI list only.
Reasons come from the existing `RerankPick.reason` — the same field that's
already validated to ≥20 Dutch chars by `_validate_picks`.

### 4.3 Synthesizer — enrich `citation_resolved` with label + quote + explanation

`src/jurist/agents/synthesizer.py::run` currently yields one event per
cited article/case with `{kind, id, resolved_url}`. Enrich:

```python
for wa in answer.relevante_wetsartikelen:
    yield TraceEvent(type="citation_resolved", data={
        "kind": "artikel",
        "id": wa.bwb_id,
        "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
        "label": wa.article_label,     # new — e.g. "Boek 7, art. 248"
        "quote": wa.quote,             # new — 40–500 chars verified passage
        "explanation": wa.explanation, # new — 1–2 Dutch sentences
    })

for uc in answer.vergelijkbare_uitspraken:
    yield TraceEvent(type="citation_resolved", data={
        "kind": "uitspraak",
        "id": uc.ecli,
        "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
        "quote": uc.quote,             # new
        "explanation": uc.explanation, # new
    })
```

All new fields are drawn from the already-parsed `StructuredAnswer` — the
exact same values the "Relevante wetsartikelen" panel already renders
elsewhere. No new parsing, no new validation.

The refusal path (`kind="insufficient_context"`) already emits no
`citation_resolved` events — unchanged.

## 5. Frontend changes

### 5.1 `TraceLines.tsx` — return `string | ReactNode`

Today each event resolves to `string | null`. Change the return type of
`eventLine` to `string | ReactNode | null`. Renderer maps strings to a
single `<li>` (current behavior) and ReactNodes to a multi-line container.

New / changed cases:

| `ev.type`             | Output                                                                                     |
|-----------------------|--------------------------------------------------------------------------------------------|
| `decomposition_done`  | "decomposeert:" header + bulleted `sub_questions` + `concepten: ...` + `intentie: ...` + `huurtype: ...` |
| `reranked` (w/ picks) | "gekozen:" header + `✓ ECLI — reason` line per pick                                        |
| `reranked` (no picks) | Fallback to today's `gekozen: eclis` single line                                           |
| `citation_resolved` (artikel, w/ quote) | 3 lines: `bron artikel bwb_id (article_label)` + `"quote"` (indented, italic) + `→ explanation` (indented) |
| `citation_resolved` (uitspraak, w/ quote) | 3 lines: `bron uitspraak ECLI` + `"quote"` (indented, italic) + `→ explanation` (indented) — no `(label)` since uitspraken have no article_label field |
| `citation_resolved` (no quote/explanation) | Fallback to today's `bron X id` single line                            |

Sub-lines use:

```css
padding-left: 14px;
color: var(--text-tertiary);
font-size: 12px;  /* vs 13px for top-level trace lines */
```

The monospace font family is kept for visual continuity with the existing
trace. Quoted passages render in italics (`font-style: italic`) to
visually separate them from agent narrative.

### 5.2 `runStore.ts` — no logic change needed

`apply()` on line 282 has a `default:` case that appends any event to
`traceLog` without side effects. `decomposition_done` falls through there;
the enriched `reranked` / `citation_resolved` already have cases that
don't touch the new fields. Nothing to change.

### 5.3 `types/events.ts` — no change needed

`TraceEvent.data` is already typed `Record<string, unknown>` (events.ts:44),
so new fields flow through without a schema edit. The renderer in
`TraceLines.tsx` casts the relevant fields as it reads them.

## 6. History persistence — existing pipeline carries it

No code change. Verifying the chain:

1. **SSE** — `src/jurist/api/app.py` yields `{"data": ev.model_dump_json()}`.
   Pydantic serializes `TraceEvent.data: dict[str, Any]` verbatim; new fields
   ride along.
2. **`runStore.apply`** (`web/src/state/runStore.ts:189`) —
   `const traceLog = [...s.traceLog, ev];` appends the full event;
   side-effect switch cases don't mutate `ev.data`.
3. **`toSnapshot`** (`web/src/state/snapshot.ts:39`) — filters only
   `answer_delta`; preserves every other event whole.
4. **`archiveCurrent`** (`runStore.ts:127`) — called on `run_finished` and
   `run_failed`; serializes the snapshot and PUTs.
5. **`PUT /api/history`** (`src/jurist/api/history.py:79`) —
   `HistoryEntry.snapshot: dict` is opaque to the server.
6. **Disk** — atomic JSON write via `_atomic_write`.
7. **Reload** — `GET /api/history` → `fromSnapshot` → `TraceLines` renders
   with the enriched events.

**Size envelope.** Per-run increments on the locked huur question:

- `decomposition_done`: ~400 B (concepts list + sub-questions).
- `reranked` (enriched): +~300 B for 3 × ≥20-char Dutch reasons.
- `citation_resolved` × ~8 (5 articles + 3 cases typical): +~8 × 600 B ≈ 5 KB.

Net: ~6 KB per run. Over the 15-entry cap: ~90 KB extra. The
`MAX_PAYLOAD_BYTES = 5 MB` cap (`history.py:17`) has ample headroom.

## 7. Back-compat: old snapshots with missing fields

Snapshots written before this change contain `reranked` events with `kept`
but no `picks`, and `citation_resolved` events without `quote` /
`explanation`. Renderer must accept both shapes:

```tsx
case 'reranked': {
  const picks = ev.data.picks as {ecli: string; reason: string}[] | undefined;
  if (picks && picks.length) return <EnrichedRerank picks={picks} />;
  return `gekozen: ${(ev.data.kept as string[]).join(', ')}`;
}

case 'citation_resolved': {
  const quote = ev.data.quote as string | undefined;
  const expl = ev.data.explanation as string | undefined;
  const label = ev.data.label as string | undefined;  // artikel-only; uitspraak omits
  if (quote && expl) return <EnrichedCitation
    kind={ev.data.kind} id={ev.data.id} label={label}
    quote={quote} explanation={expl}
  />;
  return `bron ${ev.data.kind} ${ev.data.id}`;
}
```

This also covers the refusal path (where citation_resolved doesn't fire —
the synthesizer emits the refusal body straight into `answer_delta`), and
it covers any future event where the synth elected to emit bare citations
without verification metadata.

## 8. Testing

### 8.1 Backend

- `tests/agents/test_decomposer.py` — add a test that asserts the
  agent emits exactly the expected sequence: `agent_started`,
  `decomposition_done`, `agent_finished`, with matching payloads.
- `tests/agents/test_case_retriever.py` — the existing happy-path test
  asserts on `reranked.data`; update to expect `picks: [{ecli, reason}]`
  and keep the `kept` back-compat assertion.
- `tests/agents/test_synthesizer.py` — the existing citation-resolved
  assertion gains `quote` / `explanation` / `label` (article path only).
- `tests/api/test_orchestrator.py` — if any test does strict event-
  sequence equality for the decomposer path, adjust to include the new
  event.

### 8.2 Frontend

- `web/src/state/snapshot.test.ts` — extend the round-trip test with a
  traceLog containing (a) a `decomposition_done` event, (b) a `reranked`
  with `picks`, (c) two `citation_resolved` events with `quote` +
  `explanation`. Assert `toSnapshot(fromSnapshot(...))` is field-stable.
- `web/src/state/runStore.test.ts` — assert that dispatching a
  `decomposition_done` event appends it to `traceLog` and produces no
  state side-effect (falls through to `default:`).
- New `web/src/components/panel/TraceLines.test.tsx` (or extend existing)
  — unit test the render for each new case, plus the fallback paths when
  enrichment fields are missing.

### 8.3 Manual integration

Run the locked huur question end-to-end with live LLMs:

1. Live trace shows decomposer block with sub-questions, concepts,
   intent, huurtype.
2. Case retriever block shows 20 `gevonden` lines followed by 3
   `✓ ECLI — reason` lines under "gekozen:".
3. Synthesizer block shows ~5–8 citations, each with the label, quote,
   and explanation.
4. After `run_finished`, open "Toon redenering" → identical content.
5. Reload the page, open history drawer, click the run → identical
   content.

## 9. Risks and mitigations

| Risk                                                       | Mitigation                                                                                                    |
|------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| Enriched events break existing tests with strict-equality assertions on `data` | Tests updated in the same commit; CI catches regressions. |
| Quote contains characters that break JSX rendering (e.g., `<`, `{`) | React escapes strings in text children by default. Validated during manual integration. |
| History file grows faster than expected                    | Size envelope in §6 is conservative; 5 MB cap has ~50× headroom. Monitor if answers get longer. |
| Visual density overwhelms in the "Toon redenering" view    | Rendering is still flat (no JS animation, no collapsibility). If feedback signals noise, add a toggle as a follow-up. |

## 10. Implementation sequence

One session. Suggested order:

1. Backend: add `decomposition_done` event + one test.
2. Backend: enrich `reranked` event + update case-retriever tests.
3. Backend: enrich `citation_resolved` event + update synthesizer tests.
4. Frontend: refactor `TraceLines.tsx` return type + new case handlers
   with fallback paths.
5. Frontend: snapshot round-trip test + runStore default-case test.
6. Manual integration on the locked question (live + post-run + history
   replay).
7. Commit with a message that references this spec.

No TDD rule bends here — each step has a test-first increment.
