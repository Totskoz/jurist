# Trace Inline Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface already-captured agent reasoning (decomposition fields, per-pick rerank reasons, per-citation quote+explanation) as inline sub-lines in the panel's trace view, so the "redenering" disclosure no longer renders terse two-line blocks for three of the five agents. No new LLM calls.

**Architecture:** Backend adds one new event type (`decomposition_done`) and enriches two existing events (`reranked`, `citation_resolved`) with fields already parsed elsewhere. Frontend rewrites `TraceLines.tsx` to return `string | ReactNode | null`, rendering multi-line blocks when the enrichment fields are present and falling back to today's terse single line when they aren't. History persistence needs zero code change — snapshots already flow `TraceEvent.data` opaquely end-to-end.

**Tech Stack:** Python 3.11 / asyncio / Pydantic v2 (backend agents). TypeScript / React 18 / Zustand / vitest (frontend). Event transport is SSE via FastAPI `EventSourceResponse`.

**Spec:** `docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md`

---

## Files

**Backend — modified:**
- `src/jurist/agents/decomposer.py` (add one event emission before `agent_finished`)
- `src/jurist/agents/case_retriever.py:73-76` (replace existing `reranked` emission)
- `src/jurist/agents/synthesizer.py:380-397` (enrich both `citation_resolved` loops)

**Backend — tests modified:**
- `tests/agents/test_decomposer.py:42` (update event-sequence assertion; add a new test)
- `tests/agents/test_case_retriever.py:113-117` (extend `reranked` payload assertions)
- `tests/agents/test_synthesizer.py:118-131` (assert new `citation_resolved` fields)

**Frontend — modified:**
- `web/src/components/panel/TraceLines.tsx` (return type + new case handlers + fallbacks)

**Frontend — tests modified:**
- `web/src/state/snapshot.test.ts` (add round-trip coverage of enriched events)
- `web/src/state/runStore.test.ts` (add `decomposition_done` default-case coverage)

**No changes needed:**
- `src/jurist/schemas.py` — `TraceEvent.data: dict[str, Any]` is generic.
- `src/jurist/api/history.py` — `HistoryEntry.snapshot: dict` is opaque to the server.
- `web/src/state/snapshot.ts` / `web/src/state/runStore.ts` — `traceLog` append and `toSnapshot` filter are both type-generic.
- `web/src/types/events.ts` — `TraceEvent.data: Record<string, unknown>` is generic.

---

## Task 1: Decomposer emits `decomposition_done`

**Files:**
- Modify: `src/jurist/agents/decomposer.py:117-132`
- Modify: `tests/agents/test_decomposer.py:28-46`
- Modify: `tests/agents/test_decomposer.py` (add one new test)

### - [ ] Step 1: Update the existing happy-path test to expect the new event

Open `tests/agents/test_decomposer.py`. Replace the assertion block in `test_decomposer_happy_path` (currently lines 42-46):

```python
    assert [ev.type for ev in events] == ["agent_started", "agent_finished"]
    out = DecomposerOut.model_validate(events[-1].data)
    assert out.intent == "legality_check"
    assert len(out.sub_questions) == 2
    assert "huurverhoging" in out.concepts
```

with:

```python
    assert [ev.type for ev in events] == [
        "agent_started", "decomposition_done", "agent_finished",
    ]
    done = events[1]
    assert done.data["sub_questions"] == [
        "Is de woning gereguleerd?", "Wat is het maximum?",
    ]
    assert done.data["concepts"] == ["huurverhoging", "gereguleerd"]
    assert done.data["intent"] == "legality_check"
    assert done.data["huurtype_hypothese"] == "onbekend"

    out = DecomposerOut.model_validate(events[-1].data)
    assert out.intent == "legality_check"
    assert len(out.sub_questions) == 2
    assert "huurverhoging" in out.concepts
```

### - [ ] Step 2: Add a regression test that decomposition_done fires exactly once

Append this test to `tests/agents/test_decomposer.py` (after `test_decomposer_regens_on_bad_intent`):

```python
@pytest.mark.asyncio
async def test_decomposer_emits_decomposition_done_exactly_once_after_regen():
    """Even when attempt 1 fails and attempt 2 succeeds, decomposition_done
    fires exactly once — we only emit for the final accepted output, not per
    attempt."""
    import jurist.agents.decomposer as dec_mod

    class _TwoShotClient:
        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                self._outer._n += 1
                if self._outer._n == 1:
                    return SimpleNamespace(content=[
                        SimpleNamespace(type="text", text="oh no"),
                    ])
                return SimpleNamespace(content=[
                    SimpleNamespace(
                        type="tool_use", name="emit_decomposition",
                        input={
                            "sub_questions": ["q1"], "concepts": ["c1"],
                            "intent": "procedure",
                            "huurtype_hypothese": "onbekend",
                        },
                    ),
                ])

        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0
            self.messages = _TwoShotClient._Messages(self)

    mock = _TwoShotClient()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]
    events = [ev async for ev in dec_mod.run(DecomposerIn(question="q"), ctx=ctx)]
    types = [e.type for e in events]
    assert types.count("decomposition_done") == 1
    assert types == ["agent_started", "decomposition_done", "agent_finished"]
```

### - [ ] Step 3: Run the tests, confirm they fail

Run:

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run pytest tests/agents/test_decomposer.py -v
```

Expected: `test_decomposer_happy_path` FAILS (assertion on event list length — only 2 events today), and `test_decomposer_emits_decomposition_done_exactly_once_after_regen` FAILS (same reason). Other decomposer tests PASS (they don't assert on event sequence).

### - [ ] Step 4: Emit the new event in `decomposer.run`

Open `src/jurist/agents/decomposer.py`. Replace the body of `run` (lines 117-132) with:

```python
async def run(
    input: DecomposerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_decomposer_system()
    user = (
        f"Vraag: {input.question}\n\n"
        "Decomposeer deze vraag via `emit_decomposition`."
    )
    schema = _build_decomposer_tool_schema()

    out = await _decompose_with_retry(ctx.llm, system, user, schema)
    yield TraceEvent(type="decomposition_done", data={
        "sub_questions": list(out.sub_questions),
        "concepts": list(out.concepts),
        "intent": out.intent,
        "huurtype_hypothese": out.huurtype_hypothese,
    })
    yield TraceEvent(type="agent_finished", data=out.model_dump())
```

Note: `list(out.sub_questions)` / `list(out.concepts)` produces plain Python lists (not Pydantic list views), which serialize cleanly through `model_dump_json()`.

### - [ ] Step 5: Run the tests, confirm they pass

Run:

```bash
uv run pytest tests/agents/test_decomposer.py -v
```

Expected: all decomposer tests PASS, including the two updated/new ones.

### - [ ] Step 6: Commit

```bash
git add src/jurist/agents/decomposer.py tests/agents/test_decomposer.py
git commit -m "$(cat <<'EOF'
feat(decomposer): emit decomposition_done event before agent_finished

Surfaces sub_questions, concepts, intent, and huurtype_hypothese on the
trace timeline so the panel can render the decomposer's output as inline
sub-lines instead of a bare start→klaar pair.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Case retriever `reranked` carries per-pick reasons

**Files:**
- Modify: `src/jurist/agents/case_retriever.py:73-76`
- Modify: `tests/agents/test_case_retriever.py:113-117`

### - [ ] Step 1: Update the happy-path test to assert the enriched payload

Open `tests/agents/test_case_retriever.py`. Replace lines 113-117 (the current `reranked` assertion):

```python
    reranked = [e for e in events if e.type == "reranked"]
    assert len(reranked) == 1
    assert reranked[0].data["kept"] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
```

with:

```python
    reranked = [e for e in events if e.type == "reranked"]
    assert len(reranked) == 1
    # kept stays around for back-compat.
    assert reranked[0].data["kept"] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    picks = reranked[0].data["picks"]
    assert [p["ecli"] for p in picks] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    # Reasons flow from the Haiku mock's tool input (≥20 Dutch chars each).
    assert picks[0]["reason"] == "Feitelijk zeer vergelijkbaar met de vraag."
    assert picks[1]["reason"].startswith("Relevant voor juridische context")
    assert picks[2]["reason"].startswith("Toepassing van Boek 7")
```

### - [ ] Step 2: Run the test, confirm it fails

Run:

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run pytest tests/agents/test_case_retriever.py::test_happy_path_emits_expected_events -v
```

Expected: FAIL on `reranked[0].data["picks"]` — KeyError, field doesn't exist yet.

### - [ ] Step 3: Enrich the event in `case_retriever.run`

Open `src/jurist/agents/case_retriever.py`. Replace lines 73-76 (the existing `reranked` emission):

```python
    yield TraceEvent(
        type="reranked",
        data={"kept": [p.ecli for p in picks]},
    )
```

with:

```python
    yield TraceEvent(
        type="reranked",
        data={
            "picks": [{"ecli": p.ecli, "reason": p.reason} for p in picks],
            "kept": [p.ecli for p in picks],  # back-compat; old consumers read only the ECLI list
        },
    )
```

### - [ ] Step 4: Run the case retriever test suite, confirm all pass

Run:

```bash
uv run pytest tests/agents/test_case_retriever.py tests/agents/test_case_retriever_errors.py -v
```

Expected: all tests PASS. The enriched event is a superset of the previous shape, so error-path tests are unaffected.

### - [ ] Step 5: Commit

```bash
git add src/jurist/agents/case_retriever.py tests/agents/test_case_retriever.py
git commit -m "$(cat <<'EOF'
feat(case_retriever): include per-pick reasons in reranked event

The Haiku rerank already requires a ≥20-char Dutch reason per pick; that
reason now rides on the reranked event alongside the ECLI list, so the
panel can render each pick as "✓ ECLI — reason" instead of a bare ECLI
triplet. The `kept` field stays for back-compat.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Synthesizer `citation_resolved` carries quote, explanation, label

**Files:**
- Modify: `src/jurist/agents/synthesizer.py:380-397`
- Modify: `tests/agents/test_synthesizer.py:118-131`

### - [ ] Step 1: Update the happy-path test to assert the enriched payload

Open `tests/agents/test_synthesizer.py`. Replace the assertion block in `test_synthesizer_happy_path` (currently lines 118-131):

```python
    types = [ev.type for ev in events]
    # agent_started is first; agent_finished is last; thinking comes before
    # citation_resolved and answer_delta.
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert types.count("agent_thinking") == 3                       # one per text_delta
    # two citations total → two citation_resolved events
    assert types.count("citation_resolved") == 2
    assert types.count("answer_delta") >= 5                         # at least several tokens

    out = SynthesizerOut.model_validate(events[-1].data)
    assert "15%" in out.answer.korte_conclusie
    assert out.answer.relevante_wetsartikelen[0].article_id.endswith("/Artikel248")
```

with:

```python
    types = [ev.type for ev in events]
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert types.count("agent_thinking") == 3
    assert types.count("citation_resolved") == 2
    assert types.count("answer_delta") >= 5

    citations = [ev for ev in events if ev.type == "citation_resolved"]
    # Artikel event — kind=artikel, label populated, quote + explanation present.
    artikel_ev = next(c for c in citations if c.data["kind"] == "artikel")
    assert artikel_ev.data["id"] == "BWBR0005290"
    assert artikel_ev.data["label"] == "Boek 7, Artikel 248"
    assert "drie jaren" in artikel_ev.data["quote"]
    assert "bevoegdheid" in artikel_ev.data["explanation"].lower()
    # Uitspraak event — kind=uitspraak, no label field, quote + explanation present.
    uitspraak_ev = next(c for c in citations if c.data["kind"] == "uitspraak")
    assert uitspraak_ev.data["id"] == "ECLI:NL:RBAMS:2022:5678"
    assert "label" not in uitspraak_ev.data
    assert "15%" in uitspraak_ev.data["quote"]
    assert "buitensporig" in uitspraak_ev.data["explanation"]

    out = SynthesizerOut.model_validate(events[-1].data)
    assert "15%" in out.answer.korte_conclusie
    assert out.answer.relevante_wetsartikelen[0].article_id.endswith("/Artikel248")
```

### - [ ] Step 2: Run the test, confirm it fails

Run:

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run pytest tests/agents/test_synthesizer.py::test_synthesizer_happy_path -v
```

Expected: FAIL on `artikel_ev.data["label"]` — KeyError, field doesn't exist yet.

### - [ ] Step 3: Enrich the two emission loops in `synthesizer.run`

Open `src/jurist/agents/synthesizer.py`. Replace lines 380-397 (the two `citation_resolved` emission loops on the normal path):

```python
    for wa in answer.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": wa.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
            },
        )
    for uc in answer.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": uc.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
            },
        )
```

with:

```python
    for wa in answer.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": wa.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
                "label": wa.article_label,
                "quote": wa.quote,
                "explanation": wa.explanation,
            },
        )
    for uc in answer.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": uc.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
                "quote": uc.quote,
                "explanation": uc.explanation,
            },
        )
```

Note: only the artikel event gains `label` (from `WetArtikelCitation.article_label`). `UitspraakCitation` has no equivalent field, so the uitspraak event omits it — the frontend handles this asymmetry in Task 6.

### - [ ] Step 4: Run the synthesizer test suite, confirm all pass

Run:

```bash
uv run pytest tests/agents/test_synthesizer.py tests/agents/test_synthesizer_grounding.py tests/agents/test_synthesizer_refusal.py tests/agents/test_synthesizer_m5_rules.py tests/agents/test_synthesizer_tools.py -v
```

Expected: all tests PASS. Refusal tests don't emit `citation_resolved` (empty citation lists), so they're unaffected.

### - [ ] Step 5: Run the full backend test suite as a regression gate

Run:

```bash
uv run pytest -v
```

Expected: all tests PASS (no orchestrator tests assert on citation_resolved payloads strictly).

### - [ ] Step 6: Commit

```bash
git add src/jurist/agents/synthesizer.py tests/agents/test_synthesizer.py
git commit -m "$(cat <<'EOF'
feat(synthesizer): enrich citation_resolved with quote, explanation, label

The structured answer already carries these fields per WetArtikelCitation
/ UitspraakCitation; they now ride on citation_resolved events so the
panel can render each source inline with its quoted passage and the
synthesizer's Dutch explanation instead of a bare "bron X id" line.
Artikel events add `label` (from article_label); uitspraak events omit
it since UitspraakCitation has no equivalent field.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Snapshot round-trip preserves enriched events

**Files:**
- Modify: `web/src/state/snapshot.test.ts`

### - [ ] Step 1: Add a round-trip test for the three enriched/new event payloads

Open `web/src/state/snapshot.test.ts`. Append this test inside the existing `describe('toSnapshot → fromSnapshot round-trip', () => {...})` block (after line 110):

```typescript
  it('preserves decomposition_done, reranked picks, and citation_resolved enrichment fields', () => {
    const view1 = {
      question: 'Mag de huur met 15% omhoog?',
      kgState: new Map<string, 'default' | 'current' | 'visited' | 'cited'>(),
      edgeState: new Map<string, 'default' | 'traversed'>(),
      traceLog: [
        ev('decomposition_done', {
          sub_questions: ['Is 15% toegestaan?', 'Wat is het maximum?'],
          concepts: ['huurverhoging', 'sociale huur'],
          intent: 'legality_check',
          huurtype_hypothese: 'onbekend',
        }, 'decomposer'),
        ev('reranked', {
          picks: [
            { ecli: 'ECLI:NL:A:1', reason: 'Feitelijk vergelijkbaar met de vraag.' },
            { ecli: 'ECLI:NL:B:2', reason: 'Relevante juridische context.' },
            { ecli: 'ECLI:NL:C:3', reason: 'Toepassing van art. 7:248 BW.' },
          ],
          kept: ['ECLI:NL:A:1', 'ECLI:NL:B:2', 'ECLI:NL:C:3'],
        }, 'case_retriever'),
        ev('citation_resolved', {
          kind: 'artikel',
          id: 'BWBR0005290',
          resolved_url: 'https://wetten.overheid.nl/BWBR0005290',
          label: 'Boek 7, Artikel 248',
          quote: 'De verhuurder kan tot aan het tijdstip waarop drie jaren zijn verstreken',
          explanation: 'Regelt de bevoegdheid tot huurverhoging.',
        }, 'synthesizer'),
        ev('citation_resolved', {
          kind: 'uitspraak',
          id: 'ECLI:NL:RBAMS:2022:5678',
          resolved_url: 'https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678',
          quote: 'Huurverhoging van 15% acht de rechtbank in dit geval buitensporig.',
          explanation: 'Rechtbank wijst 15% af.',
        }, 'synthesizer'),
      ],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: new Set<string>(),
    };

    const view2 = fromSnapshot(toSnapshot(view1), view1.question);

    expect(view2.traceLog).toEqual(view1.traceLog);
    // Spot-check the enrichment fields survive as-is.
    const done = view2.traceLog[0];
    expect(done.data.sub_questions).toEqual(['Is 15% toegestaan?', 'Wat is het maximum?']);
    expect(done.data.huurtype_hypothese).toBe('onbekend');
    const reranked = view2.traceLog[1];
    expect((reranked.data.picks as Array<{ reason: string }>)[0].reason)
      .toBe('Feitelijk vergelijkbaar met de vraag.');
    const artikel = view2.traceLog[2];
    expect(artikel.data.label).toBe('Boek 7, Artikel 248');
    expect(artikel.data.quote).toContain('drie jaren');
    const uitspraak = view2.traceLog[3];
    expect(uitspraak.data.label).toBeUndefined();
    expect(uitspraak.data.explanation).toBe('Rechtbank wijst 15% af.');
  });
```

### - [ ] Step 2: Run the test, confirm it passes (this is the regression gate, not a failing test)

Run:

```bash
cd web && npm test -- snapshot.test
```

Expected: PASS. This test verifies the existing code's correctness (traceLog is already serialized verbatim); no production code change is required for it to pass. It exists to **prevent** a future refactor from silently dropping enrichment fields.

If it FAILS: investigate — either the test has a typo (check event construction) or the snapshot layer has drifted and needs restoration.

### - [ ] Step 3: Commit

```bash
git add web/src/state/snapshot.test.ts
git commit -m "$(cat <<'EOF'
test(snapshot): round-trip preserves decomposition_done, rerank picks, citation enrichment

Regression gate for the inline-expansion feature: snapshots written after
the backend enrichment must carry sub_questions/concepts/intent on
decomposition_done, per-pick reasons on reranked, and quote/explanation/
label on citation_resolved events, so historic replay renders identically
to live.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `runStore.apply` passes `decomposition_done` through the default case

**Files:**
- Modify: `web/src/state/runStore.test.ts`

### - [ ] Step 1: Add a test for the new event type

Open `web/src/state/runStore.test.ts`. Append this `describe` block at the end of the file:

```typescript
describe('runStore — decomposition_done + enriched reranked/citation_resolved (inline expansion)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.setState({ history: [] });
  });

  it('appends decomposition_done to traceLog via default case with no side-effect', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');
    const before = useRunStore.getState();
    const beforeKg = before.kgState.size;
    const beforeThinking = Object.keys(before.thinkingByAgent).length;
    const beforeCases = before.cases.length;
    const beforeResolutions = before.resolutions.length;

    store.apply(ev('decomposition_done', {
      sub_questions: ['sq1'],
      concepts: ['c1'],
      intent: 'legality_check',
      huurtype_hypothese: 'onbekend',
    }, 'decomposer'));

    const s = useRunStore.getState();
    // Event lands on traceLog verbatim.
    expect(s.traceLog).toHaveLength(1);
    expect(s.traceLog[0].type).toBe('decomposition_done');
    expect(s.traceLog[0].data.sub_questions).toEqual(['sq1']);
    expect(s.traceLog[0].data.huurtype_hypothese).toBe('onbekend');
    // No side-effects on other slices.
    expect(s.kgState.size).toBe(beforeKg);
    expect(Object.keys(s.thinkingByAgent)).toHaveLength(beforeThinking);
    expect(s.cases).toHaveLength(beforeCases);
    expect(s.resolutions).toHaveLength(beforeResolutions);
  });

  it('appends enriched reranked with picks verbatim to traceLog', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');
    store.apply(ev('reranked', {
      picks: [
        { ecli: 'ECLI:NL:A:1', reason: 'Feitelijk vergelijkbaar.' },
      ],
      kept: ['ECLI:NL:A:1'],
    }, 'case_retriever'));

    const s = useRunStore.getState();
    expect(s.traceLog).toHaveLength(1);
    const picks = s.traceLog[0].data.picks as Array<{ ecli: string; reason: string }>;
    expect(picks[0].ecli).toBe('ECLI:NL:A:1');
    expect(picks[0].reason).toBe('Feitelijk vergelijkbaar.');
  });

  it('citation_resolved side-effect ignores enrichment fields but keeps them on traceLog', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');
    store.apply(ev('citation_resolved', {
      kind: 'artikel',
      id: 'BWBR0005290',
      resolved_url: 'https://wetten.overheid.nl/BWBR0005290',
      label: 'Boek 7, Artikel 248',
      quote: 'letterlijke passage uit de wettekst',
      explanation: 'Regelt huurverhoging.',
    }, 'synthesizer'));

    const s = useRunStore.getState();
    // resolutions slice stays shape-compatible — only kind/id/resolved_url.
    expect(s.resolutions).toEqual([{
      kind: 'artikel',
      id: 'BWBR0005290',
      resolved_url: 'https://wetten.overheid.nl/BWBR0005290',
    }]);
    // traceLog keeps every field.
    expect(s.traceLog[0].data.label).toBe('Boek 7, Artikel 248');
    expect(s.traceLog[0].data.quote).toBe('letterlijke passage uit de wettekst');
    expect(s.traceLog[0].data.explanation).toBe('Regelt huurverhoging.');
  });
});
```

### - [ ] Step 2: Run the test, confirm it passes

Run:

```bash
cd web && npm test -- runStore.test
```

Expected: PASS. Like Task 4, this test verifies existing behavior — no production code change needed (runStore's `default:` case already appends unknown events, and `citation_resolved`'s side-effect reads only three fields from `ev.data` regardless of what else is there).

### - [ ] Step 3: Commit

```bash
git add web/src/state/runStore.test.ts
git commit -m "$(cat <<'EOF'
test(runStore): decomposition_done and enriched events flow through intact

Locks in that apply() appends decomposition_done via the default case
without side-effects, preserves picks[] on reranked, and keeps enrichment
fields on citation_resolved despite the resolutions slice's narrower
shape. Regression gate for the inline-expansion feature.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Rewrite `TraceLines.tsx` with inline expansion rendering

**Files:**
- Modify: `web/src/components/panel/TraceLines.tsx` (full file rewrite)

### - [ ] Step 1: Rewrite `TraceLines.tsx` with multi-line rendering + fallbacks

Replace the entire contents of `web/src/components/panel/TraceLines.tsx` with:

```tsx
import type { ReactNode } from 'react';
import type { TraceEvent } from '../../types/events';

type Rendered = string | ReactNode;

const subLineStyle: React.CSSProperties = {
  paddingLeft: 14,
  color: 'var(--text-tertiary)',
  fontSize: 12,
  opacity: 0.85,
  lineHeight: 1.55,
};

const subLineItalicStyle: React.CSSProperties = {
  ...subLineStyle,
  fontStyle: 'italic',
};

function renderDecomposition(data: Record<string, unknown>): ReactNode {
  const subs = (data.sub_questions as string[] | undefined) ?? [];
  const concepts = (data.concepts as string[] | undefined) ?? [];
  const intent = (data.intent as string | undefined) ?? '';
  const huurtype = (data.huurtype_hypothese as string | undefined) ?? '';
  return (
    <div>
      <div>decomposeert:</div>
      {subs.map((q, i) => (
        <div key={`sq-${i}`} style={subLineStyle}>• {q}</div>
      ))}
      {concepts.length > 0 && (
        <div style={subLineStyle}>concepten: {concepts.join(', ')}</div>
      )}
      {intent && <div style={subLineStyle}>intentie: {intent}</div>}
      {huurtype && <div style={subLineStyle}>huurtype: {huurtype}</div>}
    </div>
  );
}

function renderRerankWithPicks(
  picks: Array<{ ecli: string; reason: string }>,
): ReactNode {
  return (
    <div>
      <div>gekozen:</div>
      {picks.map((p, i) => (
        <div key={p.ecli + i} style={subLineStyle}>
          ✓ {p.ecli} — {p.reason}
        </div>
      ))}
    </div>
  );
}

function renderCitationEnriched(
  kind: string,
  id: string,
  label: string | undefined,
  quote: string,
  explanation: string,
): ReactNode {
  const headline =
    kind === 'artikel' && label
      ? `bron ${kind} ${id} (${label})`
      : `bron ${kind} ${id}`;
  return (
    <div>
      <div>{headline}</div>
      <div style={subLineItalicStyle}>"{quote}"</div>
      <div style={subLineStyle}>→ {explanation}</div>
    </div>
  );
}

function eventLine(ev: TraceEvent): Rendered | null {
  switch (ev.type) {
    case 'agent_started':
      return 'start';
    case 'agent_finished':
      return 'klaar';
    case 'decomposition_done':
      return renderDecomposition(ev.data);
    case 'tool_call_started':
      return `→ ${ev.data.tool}`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary ?? ''}`;
    case 'node_visited':
      return `bezocht ${ev.data.article_id}`;
    case 'edge_traversed':
      return null;
    case 'search_started':
      return 'zoekt jurisprudentie';
    case 'case_found':
      return `gevonden ${ev.data.ecli} (sim=${Number(ev.data.similarity).toFixed(2)})`;
    case 'reranked': {
      const picks = ev.data.picks as Array<{ ecli: string; reason: string }> | undefined;
      if (picks && picks.length > 0) {
        return renderRerankWithPicks(picks);
      }
      // Back-compat: old snapshots have only `kept`.
      const kept = (ev.data.kept as string[] | undefined) ?? [];
      return `gekozen: ${kept.join(', ')}`;
    }
    case 'citation_resolved': {
      const kind = ev.data.kind as string;
      const id = ev.data.id as string;
      const quote = ev.data.quote as string | undefined;
      const explanation = ev.data.explanation as string | undefined;
      const label = ev.data.label as string | undefined;
      if (quote && explanation) {
        return renderCitationEnriched(kind, id, label, quote, explanation);
      }
      // Back-compat: snapshots predating enrichment.
      return `bron ${kind} ${id}`;
    }
    case 'answer_delta':
      return null;
    case 'agent_thinking':
      return null;
    default:
      return ev.type;
  }
}

export default function TraceLines({ events }: { events: TraceEvent[] }) {
  const rendered = events
    .map(eventLine)
    .filter((l): l is Rendered => l !== null);
  if (rendered.length === 0) return null;
  return (
    <ul
      style={{
        listStyle: 'none',
        padding: 0,
        margin: '10px 0 0',
        fontFamily: 'ui-monospace, monospace',
        fontSize: 13,
        color: 'var(--text-tertiary)',
        lineHeight: 1.65,
      }}
    >
      {rendered.map((l, i) => (
        <li key={i}>{l}</li>
      ))}
    </ul>
  );
}
```

### - [ ] Step 2: Run typecheck to confirm no TS errors

Run:

```bash
cd web && npx tsc --noEmit
```

Expected: PASS with no errors.

### - [ ] Step 3: Run the full frontend test suite to confirm no regressions

Run:

```bash
cd web && npm test
```

Expected: all tests PASS (snapshot round-trip from Task 4, runStore from Task 5, plus existing tests untouched).

### - [ ] Step 4: Commit

```bash
git add web/src/components/panel/TraceLines.tsx
git commit -m "$(cat <<'EOF'
feat(web): TraceLines inline expansion for decomposer/case/synth reasoning

Renders the enrichment fields added to decomposition_done, reranked, and
citation_resolved events as indented sub-lines beneath their primary
timeline entry. Graceful fallback to the previous terse rendering when
enrichment fields are absent, so snapshots written before this change
still replay correctly.

Spec: docs/superpowers/specs/2026-04-23-trace-inline-expansion-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Manual integration — locked huur question end-to-end

**Files:** (none — manual verification only)

### - [ ] Step 1: Start the backend

In one terminal:

```bash
export PATH="/c/Users/totti/.local/bin:$PATH"
uv run python -m jurist.api
```

Expected: logs show LanceDB + KG loaded, server listening on `http://127.0.0.1:8766`.

### - [ ] Step 2: Start the frontend dev server

In a second terminal:

```bash
cd web && npm run dev
```

Expected: Vite on `http://localhost:5173`.

### - [ ] Step 3: Run the locked question and verify live trace

1. Open `http://localhost:5173` in a browser.
2. Submit the locked question: *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*
3. While the run streams, open the side panel if collapsed.

Verify live trace shows:

- **decomposer** — after `start`, a "decomposeert:" line followed by bulleted sub-questions, a `concepten: ...` line, `intentie: legality_check`, `huurtype: onbekend` (or another valid value), then `klaar`.
- **statute_retriever** — unchanged from before (live Sonnet "gedachten" block + tool-call lines + `klaar`).
- **case_retriever** — `zoekt jurisprudentie`, ~20 `gevonden ECLI:... (sim=0.XX)` lines, then a "gekozen:" header followed by 3 `✓ ECLI — reason` sub-lines, then `klaar`.
- **synthesizer** — for each cited source a 3-line block: `bron artikel BWBR... (Boek 7, Artikel 248)` or `bron uitspraak ECLI:...`, a quoted passage indented and italicized, and an indented `→ explanation` line.

### - [ ] Step 4: Verify the post-run "Toon redenering" disclosure

1. After `agent_finished` for the synthesizer and `run_finished` fire, the panel transitions to `AnswerReadyPhase`.
2. Scroll to the bottom, click **"▸ Toon redenering"**.
3. Confirm the expanded block shows the same inline expansion for every agent as in Step 3.

### - [ ] Step 5: Verify historic replay

1. Start a new query (`Nieuwe vraag`) — use the same locked question or any second question to produce two history entries.
2. Open the history drawer via the clock icon.
3. Click the first (locked-question) entry.
4. Confirm the historic view's "Toon redenering" disclosure shows identical inline expansion to the live run.

### - [ ] Step 6: Verify back-compat on an old snapshot (optional but recommended)

If `data/history.json` holds any entries from before this change:

1. Open the history drawer, click an old entry.
2. Open "Toon redenering".
3. Confirm old entries render with the *terse* forms (single-line `bron X id`, single-line `gekozen: eclis`, and no `decomposition_done` sub-lines) — **no crash, no blank section**.

If there are no pre-existing history entries, note the back-compat assertion is still locked in by the fallback branches in `TraceLines.tsx` and the Task 4 round-trip test.

### - [ ] Step 7: Commit the manual-integration note

Add a one-line note to the PR description (not a code commit), or if you want a durable marker, append a row to any project log you maintain. No file change required here — the tests and the code are the durable artifacts.

---

## Execution notes

- **Commit cadence:** one commit per task (six code commits + one doc commit if you want to mark the integration pass). All commits reference the spec.
- **TDD discipline:** Tasks 1-3 have a genuinely failing test before the code change. Tasks 4-5 are regression gates for already-correct code; their tests pass immediately.
- **No orchestrator changes.** The new `decomposition_done` event and enriched existing events flow through `_pump` in `src/jurist/api/orchestrator.py` without modification — `_pump` stamps any event with agent/run_id/ts.
- **Rollback safety:** each backend change is a superset — removing the new fields (or the new event) would restore pre-change behavior. The frontend's fallback branches mean any single backend revert still renders without crashing.
