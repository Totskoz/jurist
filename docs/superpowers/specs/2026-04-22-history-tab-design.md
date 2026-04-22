# Run History — Design

**Date:** 2026-04-22
**Status:** Draft. Awaiting user review.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§7 UI / transport — event protocol unchanged)
**Related:** `docs/superpowers/specs/2026-04-22-frontend-redesign-design.md` (panel phase machine, `runStore` shape)

---

## 1. Context and goals

Today every run that the user wants to compare has to be re-issued against the
live LLM pipeline. That is expensive (Sonnet + Haiku tokens) and slow (~30–60 s
end-to-end for the locked huur question). There is no way to revisit a prior
answer or see what the knowledge graph looked like when that answer was
produced.

This spec adds a **run history** feature: completed runs (success *and*
failure) are archived on terminal events and can be recalled later via a
clock-icon button in the panel header. Selecting a past entry snaps the whole
view — the knowledge graph *and* the panel — back to that run's state.
Clicking "Terug naar live" returns to the live run. Storage is server-side so
history survives browser cache clear, cross-browser, and across devices that
share the same API host.

**Done when:**

1. Every terminal event (`run_finished` or `run_failed`) automatically writes
   a `HistoryEntry` to `data/history.json` via `PUT /api/history`.
2. A clock icon in the panel header opens a drawer listing past runs, newest
   first, with status dot + relative timestamp.
3. Clicking an entry switches the panel + graph to the snapshot; a "Viewing
   past run" pill with "Terug naar live" appears at the top of the panel.
4. "Nieuwe vraag" / starting a new query / `reset()` auto-exits the historic
   view.
5. FIFO eviction at 15 entries, enforced client-side and validated
   server-side.
6. History survives a full dev-server + browser restart. Manual test on the
   locked huur question passes end-to-end.

**Out of scope (v1):**

- Per-run naming or tagging.
- Search or filter across history.
- Export / import.
- Side-by-side diff of two runs (quick-switch handles comparison today; diff
  view would be phase 2 if the need arises).
- Multi-user / authenticated history.
- Pagination (15-entry cap makes it moot).
- Live-run cancellation. Live streaming continues in the background while a
  historic view is active.

## 2. Principles

- **Quick-switch, non-destructive.** Entering a historic view does not abort
  the live run or mutate the live slice. Components read either the live
  slice or the snapshot via a derived hook; live streaming keeps mutating
  the live slice in the background.
- **Snapshot what the user actually sees.** Archive the store state the user
  was looking at when the run terminated — graph state, trace, thinking,
  answer, citations — not a re-derivation from server logs.
- **Persistent, file-based, single-user.** Disk persistence (`data/history.json`)
  satisfies "keep across browser reload" without needing a database. One file,
  atomic writes, last-writer-wins.
- **Two endpoints beat four.** `GET` + `PUT`-whole-list is simpler than
  per-entry CRUD and atomic-by-construction for a single-user demo.
- **YAGNI on storage.** `localStorage` fallback, offline queue, conflict
  resolution, and retry loops are not needed. The API is always running in
  demo contexts.

## 3. Storage and schema

### 3.1 File

`data/history.json` at the project root (gitignored — contains LLM outputs
that should not land in version control). Same data directory as
`data/kg/huurrecht.json` and `data/lancedb/cases.lance`. The existing `data/`
entry in `.gitignore` already covers this path; no `.gitignore` change is
required but the spec calls out verifying this during implementation.

### 3.2 File shape

```json
{
  "version": 1,
  "entries": [ HistoryEntry, ... ]
}
```

`version` is an integer. Future schema changes bump this; the server refuses
writes with a non-matching version, and `GET` on a non-matching version
returns an empty `{version:1, entries:[]}` response to the client (forcing a
clean re-init rather than a crash on load).

### 3.3 `HistoryEntry` (Pydantic + TypeScript mirror)

```ts
type HistoryEntry = {
  id: string;                // = backend runId (question_id from POST /api/ask)
  question: string;          // original question text
  timestamp: number;         // Date.now() at archival (ms since epoch)
  status: 'finished' | 'failed';
  snapshot: RunSnapshot;
};
```

### 3.4 `RunSnapshot`

Mirrors the mutable fields of `RunState` in `web/src/state/runStore.ts`, with
Maps/Sets flattened to arrays and `answer_delta` events stripped from the
trace:

```ts
type RunSnapshot = {
  kgState: [string, NodeState][];           // Map<string, NodeState> → array
  edgeState: [string, EdgeState][];         // Map<string, EdgeState> → array
  traceLog: TraceEvent[];                   // answer_delta events filtered out
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];
  citedSet: string[];                       // Set<string> → array
};
```

Fields **not** snapshotted: `runId` (duplicated by `HistoryEntry.id`),
`question` (duplicated by `HistoryEntry.question`), `status` (duplicated by
`HistoryEntry.status`), `inspectedNode` and `panelCollapsed` (UI-local, not
part of the run).

### 3.5 Size budget

`answer_delta` events dominate the live trace (~90% of the ~700 events for a
full run). They are redundant with `answerText` and `finalAnswer`, so stripping
them from the archived `traceLog` is safe. Post-strip, `RunSnapshot`
is ~30–50 KB. 15 entries × 50 KB ≈ 750 KB — comfortably under any sensible
cap. The server rejects PUTs larger than **5 MB** as a belt-and-suspenders
check.

### 3.6 Eviction

Client-side FIFO at **15 entries**. When the client archives a 16th, it drops
the oldest before PUTting. The server validates `len(entries) ≤ 15` and
returns 400 if violated — the client bug, not the server, should never be
able to grow the file unboundedly.

## 4. Backend

### 4.1 New module `src/jurist/api/history.py`

Pure FastAPI router plus a thin file-IO layer. ~80 LOC.

```python
class HistoryEntry(BaseModel):
    id: str
    question: str
    timestamp: int
    status: Literal["finished", "failed"]
    snapshot: dict  # opaque; validation happens client-side

class HistoryFile(BaseModel):
    version: Literal[1]
    entries: list[HistoryEntry]
```

Endpoints:

- `GET /api/history` → `HistoryFile`
  - If the file is missing or empty, return `{"version": 1, "entries": []}`.
  - If the file exists but `version != 1`, return the same empty default
    (soft-reset semantics on schema mismatch).
- `PUT /api/history` (body: `HistoryFile`) → `{"ok": true}`
  - Validates `version == 1`.
  - Validates `len(entries) ≤ 15` → 400 if not.
  - Validates serialized body size ≤ 5 MB → 413 if not.
  - Atomic write: serialize to `data/history.json.tmp`, `os.replace()` to
    `data/history.json`. No partial files on crash.

### 4.2 `src/jurist/api/app.py`

Mount the router. ~10 LOC:

```python
from jurist.api.history import router as history_router
app.include_router(history_router, prefix="/api")
```

### 4.3 `src/jurist/config.py`

One line: `history_path: Path = data_dir / "history.json"`.

### 4.4 No coupling to `_runs`

The history router operates only on the disk file. It does not read or touch
the in-process `_runs` / `_tasks` dicts. Live runs continue to live in memory
until their terminal event; history is a post-hoc archive of what the client
observed.

## 5. Frontend

### 5.1 Store changes — `web/src/state/runStore.ts`

New fields on `RunState`:

```ts
history: HistoryEntry[];
viewingHistoryId: string | null;
historyDrawerOpen: boolean;
```

New actions:

```ts
hydrateHistory(): Promise<void>;
archiveCurrent(status: 'finished' | 'failed'): void;
viewHistory(id: string): void;
exitHistory(): void;
deleteHistory(id: string): void;
clearHistory(): void;
toggleHistoryDrawer(): void;
```

Hooks into existing flow:

- `apply(ev)` — after the existing terminal-event branches:
  - `run_finished` → `archiveCurrent('finished')`
  - `run_failed` → `archiveCurrent('failed')`
  `archiveCurrent` builds the snapshot (stripping `answer_delta` from the
  `traceLog`), prepends a new `HistoryEntry`, FIFO-caps at 15, optimistically
  updates local `history`, then fires `PUT /api/history` with the new list.
- `start(runId, question)` — also set `viewingHistoryId = null`. Starting a
  new query auto-exits the historic view.
- `reset()` — also set `viewingHistoryId = null`. History array untouched.

Mutation actions that touch the active view:

- `deleteHistory(id)` — if `id === viewingHistoryId`, auto-call `exitHistory()`
  before the delete so the UI does not point at a now-deleted entry.
- `clearHistory()` — unconditionally call `exitHistory()` first.

### 5.2 New API module — `web/src/state/historyApi.ts`

Thin fetch wrappers. ~30 LOC.

```ts
export async function getHistory(): Promise<HistoryEntry[]>;
export async function putHistory(entries: HistoryEntry[]): Promise<void>;
```

Both use `fetch('/api/history', ...)`. On any non-2xx, throw; caller logs
and shows a toast. No retries, no queue.

### 5.3 Snapshot helpers

`web/src/state/snapshot.ts` (new, ~60 LOC):

- `toSnapshot(live: RunState): RunSnapshot` — serializes Maps/Sets to arrays,
  filters `answer_delta` out of `traceLog`.
- `fromSnapshot(snap: RunSnapshot): ActiveRunView` — rehydrates arrays to
  Maps/Sets. `ActiveRunView` is the structural subset of `RunState` that
  components need to render a run (kgState, edgeState, traceLog,
  thinkingByAgent, answerText, finalAnswer, cases, resolutions, citedSet).

Pure functions. Unit tests round-trip a sample state.

### 5.4 Derived-read hook — `web/src/hooks/useActiveRun.ts`

```ts
export function useActiveRun(): ActiveRunView {
  const viewingId = useRunStore((s) => s.viewingHistoryId);
  // ... if viewingId set: find entry, rehydrate snapshot via useMemo.
  // ... else: return the live slice fields.
}
```

Components that render run state — `Graph.tsx`, `RunningPhase.tsx`,
`AnswerReadyPhase.tsx`, `InspectNodePhase.tsx` — read through this hook.
`IdlePhase.tsx` does not (it has no run state to render).

Rehydration is memoized on `viewingHistoryId` so switching entries repeatedly
is cheap.

### 5.5 UI components

#### 5.5.1 Clock icon — `web/src/components/panel/HistoryIcon.tsx` (~25 LOC)

Small clock (or similar) SVG button in the panel header, positioned left of
the existing `CollapseHandle`. Shows a numeric badge when
`history.length > 0`. Click → `toggleHistoryDrawer()`.

#### 5.5.2 Drawer — `web/src/components/panel/HistoryDrawer.tsx` (~120 LOC)

A framer-motion `motion.div` absolutely positioned inside the panel's scroll
area. Full panel height, full panel width. Slides in from the left edge of
the panel (`x: -panelWidth → 0`) when `historyDrawerOpen === true`, slides
back out otherwise.

Structure:

- **Header row:** "Historie (N)" title, "Wis alles" text button (confirms via
  `window.confirm('Alle geschiedenis wissen?')`), close X that calls
  `toggleHistoryDrawer()`.
- **Empty state:** "Nog geen eerdere vragen" centered, muted.
- **Entry list:** newest first. Per row:
  - Status dot (green for `finished`, red for `failed`).
  - Question text, truncated to 2 lines.
  - Relative timestamp ("2 minuten geleden", "gisteren" — small local
    helper `formatRelativeNl(ts)`).
  - Delete-X visible on hover, confirms via `window.confirm` before calling
    `deleteHistory(entry.id)`.
  - Row body click → `viewHistory(entry.id)` then `toggleHistoryDrawer()`
    (drawer closes as part of the transition).

Keyboard: Escape closes the drawer.

#### 5.5.3 Pill — `web/src/components/panel/ViewingHistoryPill.tsx` (~40 LOC)

Visible at the top of the panel (above phase content, below CollapseHandle)
when `viewingHistoryId !== null`. Neutral-tone banner:

> "Je bekijkt een eerdere vraag · [formatted timestamp]  **Terug naar live**"

"Terug naar live" calls `exitHistory()`.

### 5.6 Panel integration — `web/src/components/panel/Panel.tsx`

Today `Panel.tsx` renders:

```
<motion.aside>                         (panel frame)
  <CollapseHandle />
  <div style={{ flex: 1, overflowY: 'auto', padding: 28 }}>   (scroll area)
    <AnimatePresence mode="wait">...phases...</AnimatePresence>
  </div>
</motion.aside>
```

Additions:

- Mount `HistoryIcon` next to `CollapseHandle`, inside `motion.aside` but
  outside the scroll area.
- Mount `HistoryDrawer` as a sibling of the scroll area `<div>` inside
  `motion.aside`, `position: absolute` covering the area below
  `CollapseHandle` to the bottom of the panel. Z-indexed above the scroll
  area, below `CollapseHandle`.
- Mount `ViewingHistoryPill` *inside* the scroll area, *above* the
  `AnimatePresence` phase container (so it scrolls with the phase content
  and does not fight the drawer's z-index).
- Call `hydrateHistory()` once on mount via a `useEffect(..., [])` in
  `Panel.tsx`.

### 5.7 Graph integration — `web/src/components/graph/Graph.tsx`

Replace direct `useRunStore((s) => s.kgState)` / `s.edgeState` reads with
`useActiveRun()`. No other changes. The existing node/edge render functions
consume the same Map shapes whether live or rehydrated.

### 5.8 Phase components

`RunningPhase.tsx`, `AnswerReadyPhase.tsx`, `InspectNodePhase.tsx`: swap
direct run-state reads (`finalAnswer`, `traceLog`, `thinkingByAgent`,
`answerText`, `cases`, `resolutions`, `citedSet`) for `useActiveRun()`.

Crucially: `AnswerReadyPhase` renders identically for live-finished and
historic runs, because the snapshot carries the same `StructuredAnswer` and
trace that the live slice held at termination. No new phase is added;
`usePhase()` is unchanged.

`IdlePhase` unchanged.

## 6. Behavior specification

### 6.1 Live run + historic view coexistence

- Live streaming keeps mutating the live slice via `apply(ev)` whether a
  historic view is active or not. `useActiveRun()` decides what the UI
  reads.
- When live run terminates while the user is viewing history:
  - `archiveCurrent()` prepends the new entry; history list updates in the
    drawer (if open) and the badge count reflects it.
  - `viewingHistoryId` is not touched.
  - Clicking "Terug naar live" then shows the now-finished live run (with
    its final answer and final graph state).

### 6.2 Starting a new query from a historic view

- User hits "Nieuwe vraag" or enters a new question in idle → `reset()` or
  `start()` clears `viewingHistoryId`.
- Drawer state (`historyDrawerOpen`) is independent; `reset()` does not
  force-close it, but starting a stream covers the drawer with the new
  live panel view anyway (drawer is absolutely positioned — if the user
  wants it closed after starting, they click the icon).

### 6.3 Archival timing

- `archiveCurrent` runs in the same `apply()` tick as the terminal event,
  after the live-slice state is finalized for that event.
- Optimistic update: local `history` array is mutated first; PUT fires
  asynchronously. If PUT fails, the local state still reflects the new
  entry — disk and memory diverge until the user reloads. Acceptable for a
  single-user demo; a console.warn + toast communicates the drift.

### 6.4 Hydration timing

- `hydrateHistory()` fires once on app mount.
- If the API is unreachable at mount, `history = []` and the drawer shows
  empty state. Subsequent PUTs also fail; user can reload after the API
  recovers.

### 6.5 `answer_delta`-free trace on historic views

The historic `traceLog` lacks `answer_delta` events. This is invisible to the
user because:

- `answerText` is populated from the archived field (already concatenated
  from deltas at live time), so the streaming answer box reads fine.
- `finalAnswer` is populated, so the structured answer renders fine.
- `TraceLines` already filters `answer_delta` events to `null` in its
  `eventLine()` switch (see `web/src/components/panel/TraceLines.tsx:24`).
  `AgentThinking` reads `thinkingByAgent`, not the trace. No consumer of
  `traceLog` needs `answer_delta` entries to render correctly.

Pre-stripping at snapshot time is therefore a pure ~10× size win with no
behavior change.

## 7. Edge cases

- **Mid-run switch to history.** Allowed. Live apply-loop keeps mutating the
  live slice; reads route to the snapshot. "Terug naar live" shows whatever
  the live slice holds at that moment.
- **Stale snapshot schema on load.** Server returns empty `HistoryFile` when
  the on-disk file has `version != 1`. Client sees no entries and continues.
- **Clearing history while viewing a historic run.** `clearHistory()` calls
  `exitHistory()` first; UI returns to live (or idle if no live run).
- **Deleting the currently-viewed entry.** `deleteHistory(id)` calls
  `exitHistory()` when `id === viewingHistoryId`.
- **FIFO overflow at the client.** Client drops oldest, PUTs 15. If the
  client bugs out and sends 16, server 400s and the client's optimistic
  update remains locally — reload re-syncs from disk.
- **Two tabs open.** Last-writer-wins. Each tab's hydration is a point-in-time
  read; subsequent PUTs from the other tab are invisible until reload.
  Acceptable for demo use.
- **Rate-limit failure.** `run_failed{reason:"rate_limit"}` archives with
  `status: "failed"`; the red dot appears alongside other failures.
- **Graph render with an empty snapshot.** A `failed` run before any
  `node_visited` event has empty `kgState`/`edgeState`. Graph renders the
  base KG with all-default node state — visually identical to idle but with
  the failed answer panel. Acceptable.

## 8. Testing

### 8.1 Backend (pytest)

`tests/api/test_history.py`:

- `GET /api/history` on empty → `{version:1, entries:[]}`.
- `PUT` valid payload → persisted to tmp path → `GET` round-trips.
- `PUT` with `len(entries) > 15` → 400.
- `PUT` with `version != 1` → 400.
- `PUT` with payload > 5 MB → 413.
- Atomic write: patch `json.dump` to raise mid-write → original file
  unchanged.
- File path: tests use a tmp `history_path` via `settings` override.
- `GET` with on-disk `version == 99` → empty default response (soft-reset
  semantics).

### 8.2 Frontend (vitest)

`web/src/state/runStore.test.ts` additions:

- `archiveCurrent('finished')` strips `answer_delta` from the snapshot's
  `traceLog` and prepends a new entry.
- `archiveCurrent('failed')` sets `status: 'failed'`.
- FIFO cap: archiving a 16th entry drops the oldest.
- `viewHistory(id)` sets `viewingHistoryId`, closes the drawer.
- `exitHistory()` clears `viewingHistoryId`.
- `deleteHistory(id)` on the active id calls `exitHistory()` automatically.
- `clearHistory()` on an active view calls `exitHistory()` automatically.
- `start()` and `reset()` clear `viewingHistoryId`.

`web/src/state/snapshot.test.ts` (new):

- `toSnapshot` / `fromSnapshot` round-trip Maps/Sets correctly.
- `toSnapshot` filters `answer_delta` events out of `traceLog`.
- `fromSnapshot` on a snapshot with missing/null fields defaults sensibly.

`web/src/components/panel/HistoryDrawer.test.tsx` (new):

- Empty state renders when `history.length === 0`.
- Entry rows render newest-first.
- Clicking an entry body calls `viewHistory` and `toggleHistoryDrawer`.
- Delete-X confirms and calls `deleteHistory`.
- "Wis alles" confirms and calls `clearHistory`.

`web/src/components/panel/ViewingHistoryPill.test.tsx` (new):

- Not rendered when `viewingHistoryId === null`.
- Rendered when set; "Terug naar live" click calls `exitHistory`.

### 8.3 Manual test plan

1. Fresh `uv run python -m jurist.api` + `cd web && npm run dev`.
2. Ask the locked huur question → wait for answer → verify `data/history.json`
   exists on disk with one entry.
3. Open browser devtools Network tab; click clock icon; verify no new PUT
   fires for drawer toggle alone.
4. Click the archived entry → panel + graph snap to snapshot; pill appears.
5. Click "Terug naar live" → pill disappears; panel shows live finished
   state unchanged.
6. Ask a second question → wait for answer → drawer list shows 2 entries;
   newest on top.
7. Trigger a failure (e.g. unset `ANTHROPIC_API_KEY` mid-run) → verify the
   failed run archives with a red dot.
8. Delete one entry via hover-X → confirm dialog → entry removed from list
   and from `data/history.json` on disk.
9. "Wis alles" → confirm → list empty; file contains `{version:1, entries:[]}`.
10. Fill 16 entries — verify oldest evicts, list stays at 15.
11. Restart dev server + hard-refresh browser → history persists.

## 9. File footprint

**Backend (added):**

- `src/jurist/api/history.py` (~80 LOC)
- `src/jurist/api/app.py` (+~10 LOC: mount router)
- `src/jurist/config.py` (+1 line: `history_path`)

**Frontend (added):**

- `web/src/state/historyApi.ts` (~30 LOC)
- `web/src/state/snapshot.ts` (~60 LOC)
- `web/src/hooks/useActiveRun.ts` (~40 LOC)
- `web/src/components/panel/HistoryIcon.tsx` (~25 LOC)
- `web/src/components/panel/HistoryDrawer.tsx` (~120 LOC)
- `web/src/components/panel/ViewingHistoryPill.tsx` (~40 LOC)

**Frontend (modified):**

- `web/src/state/runStore.ts` (~100 LOC additions)
- `web/src/components/panel/Panel.tsx` (~15 LOC additions)
- `web/src/components/graph/Graph.tsx` (~5 LOC swap to `useActiveRun`)
- `web/src/components/panel/phases/RunningPhase.tsx` (swap to `useActiveRun`)
- `web/src/components/panel/phases/AnswerReadyPhase.tsx` (swap to `useActiveRun`)
- `web/src/components/panel/phases/InspectNodePhase.tsx` (swap to `useActiveRun`)

**Tests (added):**

- `tests/api/test_history.py`
- `web/src/state/snapshot.test.ts`
- `web/src/components/panel/HistoryDrawer.test.tsx`
- `web/src/components/panel/ViewingHistoryPill.test.tsx`
- `web/src/state/runStore.test.ts` (additions)

Total: ~450 LOC new + modified across ~12 source files plus 4 new test
files.

## 10. Open questions

None at time of writing. Decisions locked during brainstorming:

- Quick-switch (not side-by-side, not answer-only).
- Full-fidelity snapshot (with `traceLog`, stripped of `answer_delta`).
- Clock icon + slide-out drawer (not tab row, not floating card).
- Archive both successes and failures; disk persistence; cap 15.
