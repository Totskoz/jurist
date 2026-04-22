# Run History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clock-icon drawer that lists prior runs and quick-switches the panel + graph to a past run's state, with archival persisted to disk (`data/history.json`) so history survives browser reload and cache clear.

**Architecture:** Two new FastAPI routes (`GET` / `PUT /api/history`) do atomic JSON writes. Frontend adds a `history` slice to the Zustand store, a small `useActiveRun` hook that routes reads to either the live slice or a rehydrated snapshot, and three new components (icon, drawer, pill) composed into `Panel.tsx`. Archival fires in the `apply()` reducer on `run_finished` / `run_failed`.

**Tech Stack:** FastAPI + Pydantic (backend); React 18 + Zustand 5 + framer-motion + TypeScript + Vitest (frontend). No new dependencies.

**Parent spec:** `docs/superpowers/specs/2026-04-22-history-tab-design.md`

---

## File Structure

**Backend — created:**
- `src/jurist/api/history.py` — Pydantic models, atomic writer, `APIRouter` with GET + PUT (~90 LOC)
- `tests/api/test_history.py` — pytest coverage for endpoints + writer (~160 LOC)

**Backend — modified:**
- `src/jurist/config.py` — add `history_path` property (1 line)
- `src/jurist/api/app.py` — mount the router (~4 LOC)

**Frontend — created:**
- `web/src/state/historyApi.ts` — `getHistory()` / `putHistory()` fetch wrappers (~30 LOC)
- `web/src/state/snapshot.ts` — `toSnapshot` / `fromSnapshot` / `ActiveRunView` type (~80 LOC)
- `web/src/state/snapshot.test.ts` — round-trip + filter tests (~80 LOC)
- `web/src/hooks/useActiveRun.ts` — derived hook + pure `selectActiveRun` helper (~50 LOC)
- `web/src/hooks/useActiveRun.test.ts` — selector tests (~50 LOC)
- `web/src/components/panel/HistoryIcon.tsx` — clock icon button + badge (~40 LOC)
- `web/src/components/panel/HistoryDrawer.tsx` — sliding drawer with list + delete + clear (~140 LOC)
- `web/src/components/panel/ViewingHistoryPill.tsx` — banner at top of panel (~45 LOC)
- `web/src/util/relativeTime.ts` — `formatRelativeNl(ms)` helper (~30 LOC)
- `web/src/util/relativeTime.test.ts` — boundary tests (~40 LOC)

**Frontend — modified:**
- `web/src/state/runStore.ts` — new fields, actions, lifecycle hooks (~130 LOC additions)
- `web/src/state/runStore.test.ts` — history-slice coverage (~120 LOC additions)
- `web/src/components/panel/Panel.tsx` — mount icon/drawer/pill + `hydrateHistory` on mount (~25 LOC additions)
- `web/src/components/graph/Graph.tsx` — swap direct reads to `useActiveRun()` (~5 LOC change)
- `web/src/components/panel/phases/RunningPhase.tsx` — swap to `useActiveRun()`
- `web/src/components/panel/phases/AnswerReadyPhase.tsx` — swap to `useActiveRun()`
- `web/src/components/panel/phases/InspectNodePhase.tsx` — swap to `useActiveRun()`

**Testing scope clarification:** Spec §8.2 listed `HistoryDrawer.test.tsx` and `ViewingHistoryPill.test.tsx`. This plan deliberately skips DOM-rendering tests for those components: the repo's vitest config uses `environment: 'node'` (see `web/vitest.config.ts`) and has no `@testing-library/react`. Rather than adding DOM-testing deps for two thin view components, this plan exercises the underlying logic (selector, store actions, snapshot helpers) with pure tests, and verifies the visual layer via the Task 17 manual smoke test. If DOM tests are desired later, add `@testing-library/react` + `jsdom` + per-file `// @vitest-environment jsdom` as a separate change.

---

## Task 1: Add `history_path` to config

**Files:**
- Modify: `src/jurist/config.py:82-93` (add alongside existing `@property` paths)

- [ ] **Step 1: Add the property**

Edit `src/jurist/config.py`. After the existing `cases_dir` property, add:

```python
    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.json"
```

- [ ] **Step 2: Verify nothing breaks**

Run: `uv run python -c "from jurist.config import settings; print(settings.history_path)"`
Expected: prints a path ending in `data\history.json` (Windows) or `data/history.json`.

- [ ] **Step 3: Commit**

```bash
git add src/jurist/config.py
git commit -m "config: add history_path (data/history.json)"
```

---

## Task 2: Backend — models, atomic writer, GET/PUT router

**Files:**
- Create: `src/jurist/api/history.py`
- Create: `tests/api/test_history.py`

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_history.py`:

```python
"""Tests for /api/history — atomic-write, size caps, version gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jurist.api.history import router
from jurist.config import Settings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Minimal app with only the history router mounted — no KG/Lance lifespan."""
    new_settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("jurist.api.history.settings", new_settings)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _entry(i: int) -> dict:
    return {
        "id": f"run_{i:04d}",
        "question": f"q{i}",
        "timestamp": 1_700_000_000_000 + i,
        "status": "finished",
        "snapshot": {
            "kgState": [], "edgeState": [], "traceLog": [],
            "thinkingByAgent": {}, "answerText": "", "finalAnswer": None,
            "cases": [], "resolutions": [], "citedSet": [],
        },
    }


def test_get_on_missing_file_returns_empty(client: TestClient):
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_put_then_get_roundtrips(client: TestClient):
    body = {"version": 1, "entries": [_entry(1), _entry(2)]}
    put = client.put("/api/history", json=body)
    assert put.status_code == 200
    assert put.json() == {"ok": True}

    got = client.get("/api/history")
    assert got.status_code == 200
    assert got.json() == body


def test_put_rejects_too_many_entries(client: TestClient):
    body = {"version": 1, "entries": [_entry(i) for i in range(16)]}
    resp = client.put("/api/history", json=body)
    assert resp.status_code == 400
    assert "15" in resp.text


def test_put_rejects_wrong_version(client: TestClient):
    resp = client.put("/api/history", json={"version": 2, "entries": []})
    # Pydantic's Literal[1] → 422 at validation layer; that's fine.
    assert resp.status_code in (400, 422)


def test_get_on_wrong_version_returns_empty_default(
    client: TestClient, tmp_path: Path
):
    (tmp_path / "history.json").write_text(
        json.dumps({"version": 99, "entries": []}), encoding="utf-8"
    )
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_get_on_corrupt_file_returns_empty_default(
    client: TestClient, tmp_path: Path
):
    (tmp_path / "history.json").write_text("{ not json", encoding="utf-8")
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_put_atomic_write_does_not_leave_partial(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Seed a valid file.
    body = {"version": 1, "entries": [_entry(1)]}
    client.put("/api/history", json=body)

    # Patch json.dump inside the history module to raise mid-write.
    import jurist.api.history as history_mod

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(history_mod.json, "dump", boom)

    # Attempt another write — should fail.
    resp = client.put("/api/history", json={"version": 1, "entries": [_entry(2)]})
    assert resp.status_code == 500

    # Original file must still be the seeded one.
    got = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert got == body
    # No stray .tmp file.
    assert not (tmp_path / "history.json.tmp").exists()


def test_put_rejects_payload_over_5mb(client: TestClient):
    # One giant question text → pushes entry well over limit; 5 entries is enough.
    big = "x" * (2 * 1024 * 1024)  # 2 MB string
    entries = []
    for i in range(3):
        e = _entry(i)
        e["question"] = big
        entries.append(e)
    resp = client.put("/api/history", json={"version": 1, "entries": entries})
    assert resp.status_code == 413
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/api/test_history.py -v`
Expected: ALL FAIL with `ModuleNotFoundError: No module named 'jurist.api.history'`.

- [ ] **Step 3: Implement `src/jurist/api/history.py`**

Create the file:

```python
"""GET + PUT /api/history — disk-persisted run archive."""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from jurist.config import settings

logger = logging.getLogger(__name__)

MAX_ENTRIES = 15
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


class HistoryEntry(BaseModel):
    id: str
    question: str
    timestamp: int
    status: Literal["finished", "failed"]
    # Opaque to the server — client is the source of truth for snapshot shape.
    snapshot: dict


class HistoryFile(BaseModel):
    version: Literal[1] = 1
    entries: list[HistoryEntry] = Field(default_factory=list)


router = APIRouter()


def _empty() -> dict:
    return {"version": 1, "entries": []}


def _read() -> dict:
    path = settings.history_path
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("history file unreadable, returning empty: %s", e)
        return _empty()
    if not isinstance(data, dict) or data.get("version") != 1:
        return _empty()
    return data


def _atomic_write(body: HistoryFile) -> None:
    """Write via tmp file + os.replace so a crash cannot leave partial JSON."""
    path = settings.history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(body.model_dump(), f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        # Clean up tmp on failure so next write starts fresh.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


@router.get("/history")
async def get_history() -> dict:
    return _read()


@router.put("/history")
async def put_history(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"payload exceeds {MAX_PAYLOAD_BYTES} bytes",
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {e}") from e

    body = HistoryFile.model_validate(parsed)

    if len(body.entries) > MAX_ENTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"entries count {len(body.entries)} exceeds cap of {MAX_ENTRIES}",
        )

    try:
        _atomic_write(body)
    except Exception as e:
        logger.exception("history write failed")
        raise HTTPException(status_code=500, detail=f"write failed: {e}") from e

    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/api/test_history.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/api/history.py tests/api/test_history.py
git commit -m "feat(api): history router — GET + PUT with atomic writes and caps"
```

---

## Task 3: Mount history router in `app.py`

**Files:**
- Modify: `src/jurist/api/app.py:17-18, 105-112`

- [ ] **Step 1: Add the import and mount**

Edit `src/jurist/api/app.py`. In the imports block (near existing `from jurist.api.orchestrator import run_question`), add:

```python
from jurist.api.history import router as history_router
```

After the existing `add_middleware` call (around line 112), add:

```python
app.include_router(history_router, prefix="/api")
```

- [ ] **Step 2: Smoke-test via a new integration test**

Append to `tests/api/test_history.py` after the existing tests:

```python
def test_history_mounted_on_full_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The full app (with KG + Lance lifespan) also exposes /api/history."""
    import numpy as np

    from jurist.schemas import CaseChunkRow
    from jurist.vectorstore import CaseStore

    # Isolate KG + lance + history under tmp_path.
    new_settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("jurist.config.settings", new_settings)
    monkeypatch.setattr("jurist.api.app.settings", new_settings)
    monkeypatch.setattr("jurist.api.history.settings", new_settings)

    # Seed KG.
    kg_path = tmp_path / "kg" / "huurrecht.json"
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    kg_path.write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "source_versions": {"BWB": "x"},
        "nodes": [], "edges": [],
    }), encoding="utf-8")

    # Seed a non-empty LanceDB.
    store = CaseStore(tmp_path / "lancedb" / "cases.lance")
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])

    from jurist.api import app as app_module

    class _NoOpEmbedder:
        def __init__(self, model_name): pass
        def encode(self, texts, *, batch_size=32):
            return np.zeros((len(texts), 1024), dtype=np.float32)

    monkeypatch.setattr(app_module, "Embedder", _NoOpEmbedder)

    with TestClient(app_module.app) as client:
        r = client.get("/api/history")
        assert r.status_code == 200
        assert r.json() == {"version": 1, "entries": []}
```

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/api/test_history.py::test_history_mounted_on_full_app -v`
Expected: 1 passed.

- [ ] **Step 4: Full suite check**

Run: `uv run pytest -v`
Expected: all existing tests still pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/jurist/api/app.py tests/api/test_history.py
git commit -m "feat(api): mount history router under /api"
```

---

## Task 4: Frontend — `snapshot.ts` (pure serializer)

**Files:**
- Create: `web/src/state/snapshot.ts`
- Create: `web/src/state/snapshot.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/state/snapshot.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { toSnapshot, fromSnapshot } from './snapshot';
import type { RunSnapshot } from './snapshot';
import type { TraceEvent } from '../types/events';

const ev = (type: string, data: Record<string, unknown> = {}, agent: string = ''): TraceEvent =>
  ({ type, data, agent, run_id: 'r', ts: '2026-04-22T00:00:00Z' } as TraceEvent);

describe('toSnapshot', () => {
  it('flattens Maps and Sets to arrays', () => {
    const kgState = new Map([['A', 'cited' as const], ['B', 'visited' as const]]);
    const edgeState = new Map([['A::B', 'traversed' as const]]);
    const citedSet = new Set(['A', 'B']);

    const snap = toSnapshot({
      kgState,
      edgeState,
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet,
    });

    expect(snap.kgState).toEqual([['A', 'cited'], ['B', 'visited']]);
    expect(snap.edgeState).toEqual([['A::B', 'traversed']]);
    expect(snap.citedSet).toEqual(['A', 'B']);
  });

  it('strips answer_delta events from traceLog', () => {
    const trace: TraceEvent[] = [
      ev('agent_started', {}, 'synthesizer'),
      ev('answer_delta', { text: 'x' }, 'synthesizer'),
      ev('answer_delta', { text: 'y' }, 'synthesizer'),
      ev('agent_finished', {}, 'synthesizer'),
    ];
    const snap = toSnapshot({
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: trace,
      thinkingByAgent: {},
      answerText: 'xy',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: new Set(),
    });
    expect(snap.traceLog.map((e) => e.type)).toEqual(['agent_started', 'agent_finished']);
  });
});

describe('fromSnapshot', () => {
  it('rehydrates arrays back to Maps and Sets', () => {
    const snap: RunSnapshot = {
      kgState: [['A', 'cited'], ['B', 'visited']],
      edgeState: [['A::B', 'traversed']],
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: ['A', 'B'],
    };
    const view = fromSnapshot(snap);
    expect(view.kgState instanceof Map).toBe(true);
    expect(view.kgState.get('A')).toBe('cited');
    expect(view.edgeState.get('A::B')).toBe('traversed');
    expect(view.citedSet instanceof Set).toBe(true);
    expect(view.citedSet.has('A')).toBe(true);
  });
});

describe('toSnapshot → fromSnapshot round-trip', () => {
  it('preserves all fields', () => {
    const kgState = new Map([['A', 'current' as const]]);
    const edgeState = new Map([['A::B', 'traversed' as const]]);
    const citedSet = new Set(['A']);

    const view1 = {
      kgState,
      edgeState,
      traceLog: [ev('agent_started', {}, 'decomposer')],
      thinkingByAgent: { decomposer: 'thinking...' },
      answerText: 'hello',
      finalAnswer: null,
      cases: [{ ecli: 'ECLI:X', similarity: 0.9 }],
      resolutions: [{ kind: 'artikel' as const, id: 'A', resolved_url: 'http://x' }],
      citedSet,
    };
    const view2 = fromSnapshot(toSnapshot(view1));

    expect([...view2.kgState.entries()]).toEqual([...kgState.entries()]);
    expect([...view2.edgeState.entries()]).toEqual([...edgeState.entries()]);
    expect([...view2.citedSet]).toEqual([...citedSet]);
    expect(view2.traceLog).toEqual(view1.traceLog);
    expect(view2.thinkingByAgent).toEqual(view1.thinkingByAgent);
    expect(view2.answerText).toEqual(view1.answerText);
    expect(view2.cases).toEqual(view1.cases);
    expect(view2.resolutions).toEqual(view1.resolutions);
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd web && npx vitest run src/state/snapshot.test.ts`
Expected: module-not-found errors.

- [ ] **Step 3: Implement `web/src/state/snapshot.ts`**

Create the file:

```typescript
import type { StructuredAnswer, TraceEvent } from '../types/events';
import type { CaseHit, CitationResolution, EdgeState, NodeState } from './runStore';

/**
 * Structural subset of RunState that components render. Both the live slice
 * and rehydrated historic snapshots conform to this shape so a single
 * `useActiveRun` hook can swap between them.
 */
export interface ActiveRunView {
  kgState: Map<string, NodeState>;
  edgeState: Map<string, EdgeState>;
  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];
  citedSet: Set<string>;
}

/**
 * Serialized form of ActiveRunView: Maps → entries arrays, Set → array,
 * and `answer_delta` events filtered out of the trace (they are redundant
 * with `answerText` + `finalAnswer` and dominate the size budget).
 */
export interface RunSnapshot {
  kgState: [string, NodeState][];
  edgeState: [string, EdgeState][];
  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];
  citedSet: string[];
}

export function toSnapshot(view: ActiveRunView): RunSnapshot {
  return {
    kgState: [...view.kgState.entries()],
    edgeState: [...view.edgeState.entries()],
    traceLog: view.traceLog.filter((ev) => ev.type !== 'answer_delta'),
    thinkingByAgent: { ...view.thinkingByAgent },
    answerText: view.answerText,
    finalAnswer: view.finalAnswer,
    cases: [...view.cases],
    resolutions: [...view.resolutions],
    citedSet: [...view.citedSet],
  };
}

export function fromSnapshot(snap: RunSnapshot): ActiveRunView {
  return {
    kgState: new Map(snap.kgState),
    edgeState: new Map(snap.edgeState),
    traceLog: snap.traceLog,
    thinkingByAgent: { ...snap.thinkingByAgent },
    answerText: snap.answerText,
    finalAnswer: snap.finalAnswer,
    cases: [...snap.cases],
    resolutions: [...snap.resolutions],
    citedSet: new Set(snap.citedSet),
  };
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd web && npx vitest run src/state/snapshot.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/state/snapshot.ts web/src/state/snapshot.test.ts
git commit -m "feat(web): snapshot — pure to/from helpers for historic runs"
```

---

## Task 5: Frontend — `historyApi.ts` fetch wrappers

**Files:**
- Create: `web/src/state/historyApi.ts`

No test for this task — it's a thin `fetch` wrapper. Store-level tests in Task 8 exercise it via stubbed `globalThis.fetch`.

- [ ] **Step 1: Implement**

Create `web/src/state/historyApi.ts`:

```typescript
import type { RunSnapshot } from './snapshot';

export interface HistoryEntry {
  id: string;
  question: string;
  timestamp: number;
  status: 'finished' | 'failed';
  snapshot: RunSnapshot;
}

interface HistoryFile {
  version: 1;
  entries: HistoryEntry[];
}

export async function getHistory(): Promise<HistoryEntry[]> {
  const resp = await fetch('/api/history');
  if (!resp.ok) throw new Error(`GET /api/history failed: ${resp.status}`);
  const body: HistoryFile = await resp.json();
  if (body.version !== 1) return [];
  return body.entries;
}

export async function putHistory(entries: HistoryEntry[]): Promise<void> {
  const resp = await fetch('/api/history', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, entries }),
  });
  if (!resp.ok) throw new Error(`PUT /api/history failed: ${resp.status}`);
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/state/historyApi.ts
git commit -m "feat(web): historyApi — thin getHistory/putHistory wrappers"
```

---

## Task 6: Frontend — `useActiveRun` hook + pure selector

**Files:**
- Create: `web/src/hooks/useActiveRun.ts`
- Create: `web/src/hooks/useActiveRun.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/hooks/useActiveRun.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { selectActiveRun } from './useActiveRun';
import type { RunSnapshot } from '../state/snapshot';
import type { HistoryEntry } from '../state/historyApi';

function makeSnapshot(overrides: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    kgState: [['SNAP_A', 'cited']],
    edgeState: [],
    traceLog: [],
    thinkingByAgent: {},
    answerText: 'snapshot-answer',
    finalAnswer: null,
    cases: [],
    resolutions: [],
    citedSet: ['SNAP_A'],
    ...overrides,
  };
}

function makeEntry(id: string, snap: RunSnapshot): HistoryEntry {
  return { id, question: 'q', timestamp: 0, status: 'finished', snapshot: snap };
}

describe('selectActiveRun', () => {
  const liveView = {
    kgState: new Map([['LIVE_A', 'current' as const]]),
    edgeState: new Map(),
    traceLog: [],
    thinkingByAgent: { decomposer: 'thinking live' },
    answerText: 'live-answer',
    finalAnswer: null,
    cases: [],
    resolutions: [],
    citedSet: new Set<string>(),
  };

  it('returns live view when viewingHistoryId is null', () => {
    const out = selectActiveRun(liveView, null, []);
    expect(out.answerText).toBe('live-answer');
    expect(out.kgState.get('LIVE_A')).toBe('current');
  });

  it('returns rehydrated snapshot when viewingHistoryId matches an entry', () => {
    const entry = makeEntry('run_1', makeSnapshot());
    const out = selectActiveRun(liveView, 'run_1', [entry]);
    expect(out.answerText).toBe('snapshot-answer');
    expect(out.kgState.get('SNAP_A')).toBe('cited');
    expect(out.kgState.has('LIVE_A')).toBe(false);
  });

  it('falls back to live view when viewingHistoryId does not match any entry', () => {
    const out = selectActiveRun(liveView, 'nonexistent', []);
    expect(out.answerText).toBe('live-answer');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/hooks/useActiveRun.test.ts`
Expected: module-not-found.

- [ ] **Step 3: Implement `web/src/hooks/useActiveRun.ts`**

Create the file:

```typescript
import { useMemo } from 'react';
import { useRunStore } from '../state/runStore';
import type { HistoryEntry } from '../state/historyApi';
import { fromSnapshot, type ActiveRunView } from '../state/snapshot';

/**
 * Pure selector — given the live slice view, the viewingHistoryId, and the
 * history array, returns whichever view the UI should render. Extracted as a
 * pure function for unit testing; the hook below is a thin React wrapper.
 */
export function selectActiveRun(
  liveView: ActiveRunView,
  viewingHistoryId: string | null,
  history: HistoryEntry[],
): ActiveRunView {
  if (viewingHistoryId === null) return liveView;
  const entry = history.find((e) => e.id === viewingHistoryId);
  if (!entry) return liveView;
  return fromSnapshot(entry.snapshot);
}

export function useActiveRun(): ActiveRunView {
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const answerText = useRunStore((s) => s.answerText);
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const cases = useRunStore((s) => s.cases);
  const resolutions = useRunStore((s) => s.resolutions);
  const citedSet = useRunStore((s) => s.citedSet);
  const viewingHistoryId = useRunStore((s) => s.viewingHistoryId);
  const history = useRunStore((s) => s.history);

  const liveView: ActiveRunView = {
    kgState, edgeState, traceLog, thinkingByAgent,
    answerText, finalAnswer, cases, resolutions, citedSet,
  };

  return useMemo(
    () => selectActiveRun(liveView, viewingHistoryId, history),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [viewingHistoryId, history, kgState, edgeState, traceLog, thinkingByAgent,
     answerText, finalAnswer, cases, resolutions, citedSet],
  );
}
```

- [ ] **Step 4: Typecheck + test**

Run: `cd web && npx tsc --noEmit && npx vitest run src/hooks/useActiveRun.test.ts`
Expected: no TS errors. Tests pass.

Note: tsc will fail until Task 7 adds `viewingHistoryId` / `history` to the store. Mark tsc as expected-to-fail here; verify at end of Task 7.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useActiveRun.ts web/src/hooks/useActiveRun.test.ts
git commit -m "feat(web): useActiveRun — selector switches live vs historic view"
```

---

## Task 7: Frontend — extend `runStore` with history fields + simple actions

**Files:**
- Modify: `web/src/state/runStore.ts`
- Modify: `web/src/state/runStore.test.ts`

Scope of this task: add new store fields, the trivial toggle/view/exit actions, and clear `viewingHistoryId` in `start()` and `reset()`. Defer `archiveCurrent` / `hydrateHistory` / `deleteHistory` / `clearHistory` to Task 8 so each task has a tight diff.

- [ ] **Step 1: Write failing tests**

Append to `web/src/state/runStore.test.ts`:

```typescript
import type { HistoryEntry } from './historyApi';

describe('runStore — history slice (Task 7)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('initializes history=[], viewingHistoryId=null, drawer closed', () => {
    const s = useRunStore.getState();
    expect(s.history).toEqual([]);
    expect(s.viewingHistoryId).toBeNull();
    expect(s.historyDrawerOpen).toBe(false);
  });

  it('toggleHistoryDrawer flips open state', () => {
    useRunStore.getState().toggleHistoryDrawer();
    expect(useRunStore.getState().historyDrawerOpen).toBe(true);
    useRunStore.getState().toggleHistoryDrawer();
    expect(useRunStore.getState().historyDrawerOpen).toBe(false);
  });

  it('viewHistory sets id and closes drawer', () => {
    useRunStore.getState().toggleHistoryDrawer();
    useRunStore.getState().viewHistory('run_1');
    const s = useRunStore.getState();
    expect(s.viewingHistoryId).toBe('run_1');
    expect(s.historyDrawerOpen).toBe(false);
  });

  it('exitHistory clears viewingHistoryId', () => {
    useRunStore.getState().viewHistory('run_1');
    useRunStore.getState().exitHistory();
    expect(useRunStore.getState().viewingHistoryId).toBeNull();
  });

  it('start() clears viewingHistoryId', () => {
    useRunStore.getState().viewHistory('run_1');
    useRunStore.getState().start('run_2', 'q2');
    expect(useRunStore.getState().viewingHistoryId).toBeNull();
  });

  it('reset() clears viewingHistoryId but preserves history array', () => {
    // Manually seed history (no public setter yet — direct setState).
    const entry: HistoryEntry = {
      id: 'run_1', question: 'q', timestamp: 0, status: 'finished',
      snapshot: {
        kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [],
      },
    };
    useRunStore.setState({ history: [entry], viewingHistoryId: 'run_1' });
    useRunStore.getState().reset();
    const s = useRunStore.getState();
    expect(s.viewingHistoryId).toBeNull();
    expect(s.history).toEqual([entry]);  // preserved
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/state/runStore.test.ts`
Expected: new tests fail with "history is not a function" / property missing.

- [ ] **Step 3: Modify `web/src/state/runStore.ts`**

At the top of the file, add the import:

```typescript
import type { HistoryEntry } from './historyApi';
```

Extend the `RunState` interface (around line 19-44) — add these fields between `citedSet` and the action signatures:

```typescript
  history: HistoryEntry[];
  viewingHistoryId: string | null;
  historyDrawerOpen: boolean;
```

And these action signatures after `toggleCollapse: () => void;`:

```typescript
  toggleHistoryDrawer: () => void;
  viewHistory: (id: string) => void;
  exitHistory: () => void;
```

In the `create` initial-state block, add:

```typescript
  history: [],
  viewingHistoryId: null,
  historyDrawerOpen: false,
```

In `start()`, add `viewingHistoryId: null,` to the `set({ ... })` object.

In `reset()`, add `viewingHistoryId: null,` to the `set({ ... })` object.

At the end of the actions block, add the three new implementations:

```typescript
  toggleHistoryDrawer: () => set((s) => ({ historyDrawerOpen: !s.historyDrawerOpen })),
  viewHistory: (id) => set({ viewingHistoryId: id, historyDrawerOpen: false }),
  exitHistory: () => set({ viewingHistoryId: null }),
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run src/state/runStore.test.ts && npx tsc --noEmit`
Expected: all store tests pass; tsc clean (Task 6's useActiveRun references now resolve).

- [ ] **Step 5: Commit**

```bash
git add web/src/state/runStore.ts web/src/state/runStore.test.ts
git commit -m "feat(web): runStore — history/viewingHistoryId/drawer fields + simple actions"
```

---

## Task 8: Frontend — archive / hydrate / delete / clear actions with PUT

**Files:**
- Modify: `web/src/state/runStore.ts`
- Modify: `web/src/state/runStore.test.ts`

- [ ] **Step 1: Write failing tests**

Append to `web/src/state/runStore.test.ts`:

```typescript
import { vi } from 'vitest';

function mockFetchOk(): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async () => new Response(
    JSON.stringify({ version: 1, entries: [] }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  ));
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

describe('runStore — archive/hydrate/delete/clear (Task 8)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('archiveCurrent prepends entry, caps at 15, strips answer_delta', async () => {
    const fetchMock = mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_new', 'question?');
    store.apply(ev('answer_delta', { text: 'hello' }, 'synthesizer'));
    store.apply(ev('answer_delta', { text: ' world' }, 'synthesizer'));
    store.apply(ev('node_visited', { article_id: 'A' }, 'statute_retriever'));

    store.archiveCurrent('finished');

    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_new');
    expect(s.history[0].question).toBe('question?');
    expect(s.history[0].status).toBe('finished');
    expect(s.history[0].snapshot.answerText).toBe('hello world');
    expect(s.history[0].snapshot.traceLog.map((e) => e.type))
      .toEqual(['node_visited']);  // answer_delta stripped

    // PUT fired (fire-and-forget; allow microtask).
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/history',
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('archiveCurrent FIFO-caps at 15', () => {
    mockFetchOk();
    const mkEntry = (id: string): HistoryEntry => ({
      id, question: id, timestamp: 0, status: 'finished',
      snapshot: {
        kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [],
      },
    });
    // Seed 15 existing entries.
    useRunStore.setState({ history: Array.from({ length: 15 }, (_, i) => mkEntry(`old_${i}`)) });

    const store = useRunStore.getState();
    store.start('run_new', 'q');
    store.archiveCurrent('finished');

    const s = useRunStore.getState();
    expect(s.history).toHaveLength(15);
    expect(s.history[0].id).toBe('run_new');  // newest first
    expect(s.history.some((e) => e.id === 'old_0')).toBe(false);  // oldest evicted
    expect(s.history.some((e) => e.id === 'old_14')).toBe(true);  // kept
  });

  it('archiveCurrent with status=failed sets status=failed', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_f', 'q');
    store.archiveCurrent('failed');
    expect(useRunStore.getState().history[0].status).toBe('failed');
  });

  it('deleteHistory removes entry and exits history when id is active', () => {
    mockFetchOk();
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished' as const,
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    const e2 = { ...e1, id: '2' };
    useRunStore.setState({ history: [e1, e2], viewingHistoryId: '1' });

    useRunStore.getState().deleteHistory('1');
    const s = useRunStore.getState();
    expect(s.history.map((e) => e.id)).toEqual(['2']);
    expect(s.viewingHistoryId).toBeNull();  // auto-exited
  });

  it('clearHistory empties history and exits view', () => {
    mockFetchOk();
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished' as const,
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    useRunStore.setState({ history: [e1], viewingHistoryId: '1' });

    useRunStore.getState().clearHistory();
    const s = useRunStore.getState();
    expect(s.history).toEqual([]);
    expect(s.viewingHistoryId).toBeNull();
  });

  it('hydrateHistory populates history from GET /api/history', async () => {
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished',
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    globalThis.fetch = vi.fn(async () => new Response(
      JSON.stringify({ version: 1, entries: [e1] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )) as unknown as typeof fetch;

    await useRunStore.getState().hydrateHistory();
    expect(useRunStore.getState().history.map((e) => e.id)).toEqual(['1']);
  });

  it('hydrateHistory sets history=[] when API fails', async () => {
    globalThis.fetch = vi.fn(async () => new Response('nope', { status: 500 })) as unknown as typeof fetch;
    useRunStore.setState({ history: [/* junk */] as HistoryEntry[] });
    await useRunStore.getState().hydrateHistory();
    expect(useRunStore.getState().history).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/state/runStore.test.ts`
Expected: new tests fail (actions undefined).

- [ ] **Step 3: Modify `web/src/state/runStore.ts`**

Add imports at the top:

```typescript
import { getHistory, putHistory, type HistoryEntry } from './historyApi';
import { toSnapshot } from './snapshot';
```

(Replace the earlier `import type { HistoryEntry }` line.)

Extend the `RunState` interface — add these action signatures:

```typescript
  archiveCurrent: (status: 'finished' | 'failed') => void;
  deleteHistory: (id: string) => void;
  clearHistory: () => void;
  hydrateHistory: () => Promise<void>;
```

Add a module-level constant near the top of the file (above `useRunStore`):

```typescript
const HISTORY_CAP = 15;
```

Implement the actions. Add inside the `create` body, near the other action implementations:

```typescript
  archiveCurrent: (status) => {
    const s = get();
    if (!s.runId) return;  // nothing to archive

    const snapshot = toSnapshot({
      kgState: s.kgState,
      edgeState: s.edgeState,
      traceLog: s.traceLog,
      thinkingByAgent: s.thinkingByAgent,
      answerText: s.answerText,
      finalAnswer: s.finalAnswer,
      cases: s.cases,
      resolutions: s.resolutions,
      citedSet: s.citedSet,
    });

    const entry: HistoryEntry = {
      id: s.runId,
      question: s.question,
      timestamp: Date.now(),
      status,
      snapshot,
    };

    const next = [entry, ...s.history].slice(0, HISTORY_CAP);
    set({ history: next });

    // Fire-and-forget PUT; errors are logged, local state is authoritative.
    void putHistory(next).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  deleteHistory: (id) => {
    const s = get();
    const next = s.history.filter((e) => e.id !== id);
    const patch: Partial<RunState> = { history: next };
    if (s.viewingHistoryId === id) patch.viewingHistoryId = null;
    set(patch);
    void putHistory(next).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  clearHistory: () => {
    set({ history: [], viewingHistoryId: null });
    void putHistory([]).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  hydrateHistory: async () => {
    try {
      const entries = await getHistory();
      set({ history: entries });
    } catch (err) {
      console.warn('history GET failed:', err);
      set({ history: [] });
    }
  },
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run src/state/runStore.test.ts && npx tsc --noEmit`
Expected: all tests pass. tsc clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/state/runStore.ts web/src/state/runStore.test.ts
git commit -m "feat(web): runStore — archiveCurrent/hydrateHistory/delete/clear with PUT"
```

---

## Task 9: Frontend — wire `archiveCurrent` into terminal `apply()` branches

**Files:**
- Modify: `web/src/state/runStore.ts:171-194`
- Modify: `web/src/state/runStore.test.ts`

- [ ] **Step 1: Write failing tests**

Append to `web/src/state/runStore.test.ts`:

```typescript
describe('runStore — apply() archives on terminal events (Task 9)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('run_finished triggers archiveCurrent with status=finished', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_x', 'question');
    store.apply(ev('run_finished', {
      final_answer: {
        kind: 'answer',
        korte_conclusie: '',
        relevante_wetsartikelen: [],
        vergelijkbare_uitspraken: [],
        aanbeveling: '',
      },
    }));
    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_x');
    expect(s.history[0].status).toBe('finished');
  });

  it('run_failed triggers archiveCurrent with status=failed', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_y', 'bad question');
    store.apply(ev('run_failed', { reason: 'rate_limit' }));
    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_y');
    expect(s.history[0].status).toBe('failed');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/state/runStore.test.ts`
Expected: new tests fail (history still empty after terminal event).

- [ ] **Step 3: Modify `apply()` branches**

In `web/src/state/runStore.ts`, find the `run_finished` case:

```typescript
      case 'run_finished': {
        const finalAnswer = (ev.data.final_answer as StructuredAnswer) ?? null;
        const citedSet = new Set<string>();
        if (finalAnswer && finalAnswer.kind === 'answer') {
          for (const art of finalAnswer.relevante_wetsartikelen ?? []) {
            if (art.article_id) citedSet.add(art.article_id);
          }
        }
        const next = new Map(s.kgState);
        for (const [k, v] of next) {
          if (v === 'current') next.set(k, 'visited');
        }
        for (const aid of citedSet) {
          next.set(aid, 'cited');
        }
        set({ traceLog, kgState: next, status: 'finished', finalAnswer, citedSet });
        return;
      }
```

Replace `return;` with:

```typescript
        set({ traceLog, kgState: next, status: 'finished', finalAnswer, citedSet });
        get().archiveCurrent('finished');
        return;
      }
```

Find the `run_failed` case:

```typescript
      case 'run_failed': {
        set({ traceLog, status: 'failed' });
        return;
      }
```

Replace with:

```typescript
      case 'run_failed': {
        set({ traceLog, status: 'failed' });
        get().archiveCurrent('failed');
        return;
      }
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run src/state/runStore.test.ts && npx tsc --noEmit`
Expected: all pass. tsc clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/state/runStore.ts web/src/state/runStore.test.ts
git commit -m "feat(web): auto-archive on run_finished and run_failed"
```

---

## Task 10: Frontend — `relativeTime.ts` util

**Files:**
- Create: `web/src/util/relativeTime.ts`
- Create: `web/src/util/relativeTime.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/util/relativeTime.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { formatRelativeNl } from './relativeTime';

describe('formatRelativeNl', () => {
  const NOW = 1_700_000_000_000;

  it('just now → "net nu"', () => {
    expect(formatRelativeNl(NOW - 10_000, NOW)).toBe('net nu');
  });

  it('seconds → "X seconden geleden"', () => {
    expect(formatRelativeNl(NOW - 45_000, NOW)).toBe('45 seconden geleden');
  });

  it('single minute → "1 minuut geleden"', () => {
    expect(formatRelativeNl(NOW - 60_000, NOW)).toBe('1 minuut geleden');
  });

  it('multiple minutes', () => {
    expect(formatRelativeNl(NOW - 10 * 60_000, NOW)).toBe('10 minuten geleden');
  });

  it('single hour', () => {
    expect(formatRelativeNl(NOW - 60 * 60_000, NOW)).toBe('1 uur geleden');
  });

  it('multiple hours', () => {
    expect(formatRelativeNl(NOW - 3 * 60 * 60_000, NOW)).toBe('3 uur geleden');
  });

  it('yesterday', () => {
    expect(formatRelativeNl(NOW - 25 * 60 * 60_000, NOW)).toBe('gisteren');
  });

  it('multiple days', () => {
    expect(formatRelativeNl(NOW - 4 * 24 * 60 * 60_000, NOW)).toBe('4 dagen geleden');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/util/relativeTime.test.ts`
Expected: module not found.

- [ ] **Step 3: Implement `web/src/util/relativeTime.ts`**

```typescript
export function formatRelativeNl(ts: number, now: number = Date.now()): string {
  const diffMs = Math.max(0, now - ts);
  const sec = Math.floor(diffMs / 1000);
  if (sec < 30) return 'net nu';
  if (sec < 60) return `${sec} seconden geleden`;
  const min = Math.floor(sec / 60);
  if (min < 60) return min === 1 ? '1 minuut geleden' : `${min} minuten geleden`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr === 1 ? '1 uur geleden' : `${hr} uur geleden`;
  const day = Math.floor(hr / 24);
  if (day === 1) return 'gisteren';
  return `${day} dagen geleden`;
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/util/relativeTime.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/util/relativeTime.ts web/src/util/relativeTime.test.ts
git commit -m "feat(web): formatRelativeNl — Dutch relative-time labels"
```

---

## Task 11: Frontend — `HistoryIcon.tsx`

**Files:**
- Create: `web/src/components/panel/HistoryIcon.tsx`

- [ ] **Step 1: Implement**

Create the component:

```typescript
import { useRunStore } from '../../state/runStore';

export default function HistoryIcon() {
  const count = useRunStore((s) => s.history.length);
  const toggle = useRunStore((s) => s.toggleHistoryDrawer);

  return (
    <button
      onClick={toggle}
      aria-label={`Historie (${count} eerdere vragen)`}
      title="Historie"
      style={{
        position: 'absolute',
        top: 12,
        left: 12,
        width: 32,
        height: 32,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        zIndex: 2,
      }}
    >
      {/* Clock SVG */}
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      {count > 0 && (
        <span
          style={{
            position: 'absolute',
            top: 4,
            right: 4,
            background: 'var(--accent)',
            color: '#0a0b0f',
            borderRadius: 8,
            fontSize: 10,
            fontWeight: 700,
            padding: '0 5px',
            minWidth: 14,
            height: 14,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/panel/HistoryIcon.tsx
git commit -m "feat(web): HistoryIcon — clock button with entry-count badge"
```

---

## Task 12: Frontend — `ViewingHistoryPill.tsx`

**Files:**
- Create: `web/src/components/panel/ViewingHistoryPill.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useRunStore } from '../../state/runStore';
import { formatRelativeNl } from '../../util/relativeTime';

export default function ViewingHistoryPill() {
  const viewingId = useRunStore((s) => s.viewingHistoryId);
  const history = useRunStore((s) => s.history);
  const exit = useRunStore((s) => s.exitHistory);

  if (viewingId === null) return null;
  const entry = history.find((e) => e.id === viewingId);
  if (!entry) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '10px 14px',
        marginBottom: 16,
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid var(--panel-border)',
        borderRadius: 8,
        fontSize: 13,
        color: 'var(--text-secondary)',
      }}
    >
      <span>
        Je bekijkt een eerdere vraag &middot; {formatRelativeNl(entry.timestamp)}
      </span>
      <button
        onClick={exit}
        style={{
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 6,
          padding: '6px 10px',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Terug naar live
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/panel/ViewingHistoryPill.tsx
git commit -m "feat(web): ViewingHistoryPill — banner with 'Terug naar live'"
```

---

## Task 13: Frontend — `HistoryDrawer.tsx`

**Files:**
- Create: `web/src/components/panel/HistoryDrawer.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRunStore } from '../../state/runStore';
import { formatRelativeNl } from '../../util/relativeTime';

export default function HistoryDrawer() {
  const open = useRunStore((s) => s.historyDrawerOpen);
  const toggle = useRunStore((s) => s.toggleHistoryDrawer);
  const history = useRunStore((s) => s.history);
  const viewHistory = useRunStore((s) => s.viewHistory);
  const deleteHistory = useRunStore((s) => s.deleteHistory);
  const clearHistory = useRunStore((s) => s.clearHistory);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') toggle();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, toggle]);

  const onClear = () => {
    if (history.length === 0) return;
    if (window.confirm('Alle geschiedenis wissen?')) clearHistory();
  };

  const onDelete = (id: string, question: string) => {
    const preview = question.length > 50 ? question.slice(0, 47) + '…' : question;
    if (window.confirm(`Verwijder "${preview}"?`)) deleteHistory(id);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ x: '-100%' }}
          animate={{ x: 0 }}
          exit={{ x: '-100%' }}
          transition={{ type: 'spring', stiffness: 220, damping: 26 }}
          style={{
            position: 'absolute',
            top: 56,  // below CollapseHandle/HistoryIcon row
            left: 0,
            right: 0,
            bottom: 0,
            background: 'var(--panel-surface)',
            backdropFilter: 'blur(20px)',
            borderRight: '1px solid var(--panel-border)',
            display: 'flex',
            flexDirection: 'column',
            zIndex: 3,
          }}
        >
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--panel-border)',
          }}>
            <h3 style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 700,
              color: 'var(--text-primary)',
              textTransform: 'uppercase',
              letterSpacing: 0.6,
            }}>
              Historie ({history.length})
            </h3>
            <div style={{ display: 'flex', gap: 8 }}>
              {history.length > 0 && (
                <button
                  onClick={onClear}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-tertiary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  Wis alles
                </button>
              )}
              <button
                onClick={toggle}
                aria-label="Sluit historie"
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-secondary)',
                  fontSize: 18,
                  cursor: 'pointer',
                  padding: 0,
                  lineHeight: 1,
                }}
              >
                ×
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
            {history.length === 0 ? (
              <p style={{
                color: 'var(--text-tertiary)',
                fontSize: 13,
                textAlign: 'center',
                padding: 40,
                margin: 0,
              }}>
                Nog geen eerdere vragen
              </p>
            ) : (
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {history.map((entry) => (
                  <li
                    key={entry.id}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '10px 12px',
                      marginBottom: 4,
                      borderRadius: 8,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                    onClick={() => viewHistory(entry.id)}
                  >
                    <span
                      aria-label={entry.status === 'finished' ? 'geslaagd' : 'mislukt'}
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        background: entry.status === 'finished' ? '#4ade80' : '#f87171',
                        flexShrink: 0,
                        marginTop: 7,
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 13,
                        lineHeight: 1.4,
                        color: 'var(--text-primary)',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {entry.question}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
                        {formatRelativeNl(entry.timestamp)}
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); onDelete(entry.id, entry.question); }}
                      aria-label="Verwijder"
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-tertiary)',
                        fontSize: 16,
                        cursor: 'pointer',
                        padding: '0 4px',
                        lineHeight: 1,
                      }}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/panel/HistoryDrawer.tsx
git commit -m "feat(web): HistoryDrawer — list with click-to-view, delete, clear-all"
```

---

## Task 14: Frontend — Panel integration

**Files:**
- Modify: `web/src/components/panel/Panel.tsx`

- [ ] **Step 1: Edit Panel.tsx**

Add imports at the top:

```typescript
import HistoryIcon from './HistoryIcon';
import HistoryDrawer from './HistoryDrawer';
import ViewingHistoryPill from './ViewingHistoryPill';
```

Inside the component, add the hydrate effect — place it next to the existing resize effect:

```typescript
  const hydrateHistory = useRunStore((s) => s.hydrateHistory);
  useEffect(() => {
    void hydrateHistory();
  }, [hydrateHistory]);
```

Replace the existing JSX return so the structure becomes:

```tsx
  return (
    <motion.aside
      animate={{ x: collapsed ? collapseOffset : 0 }}
      transition={{ type: 'spring', stiffness: 180, damping: 22 }}
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        bottom: 16,
        width: panelWidth,
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(20px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 14,
        color: 'var(--text-primary)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        zIndex: 5,
      }}
    >
      <HistoryIcon />
      <CollapseHandle />
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 28 }}>
        <ViewingHistoryPill />
        <AnimatePresence mode="wait">
          <motion.div
            key={phase}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ type: 'spring', stiffness: 220, damping: 24 }}
          >
            {phase === 'idle' && <IdlePhase />}
            {phase === 'running' && <RunningPhase />}
            {phase === 'answer-ready' && <AnswerReadyPhase />}
            {phase === 'inspecting-node' && <InspectNodePhase />}
          </motion.div>
        </AnimatePresence>
      </div>
      <HistoryDrawer />
    </motion.aside>
  );
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Visual check**

Start the backend: `uv run python -m jurist.api` (requires KG + Lance built).
Start the frontend: `cd web && npm run dev`.
Open `http://localhost:5173`.
- Verify the clock icon renders top-left of the panel.
- Click it — empty drawer slides in from the left with "Nog geen eerdere vragen".
- Press Escape — drawer closes.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/panel/Panel.tsx
git commit -m "feat(web): Panel — mount HistoryIcon, drawer, pill; hydrate on mount"
```

---

## Task 15: Frontend — swap Graph + phase components to `useActiveRun`

**Files:**
- Modify: `web/src/components/graph/Graph.tsx`
- Modify: `web/src/components/panel/phases/RunningPhase.tsx`
- Modify: `web/src/components/panel/phases/AnswerReadyPhase.tsx`
- Modify: `web/src/components/panel/phases/InspectNodePhase.tsx`

- [ ] **Step 1: Locate direct runStore reads in Graph.tsx**

Run: `rg -n "useRunStore" web/src/components/graph/Graph.tsx`

For each selector that reads run state (`kgState`, `edgeState`, `citedSet`, `inspectedNode` — note: `inspectedNode` stays as-is, it's a UI-local field), replace with `useActiveRun()` reads.

Add at top:

```typescript
import { useActiveRun } from '../../hooks/useActiveRun';
```

Replace the specific calls:

```typescript
const { kgState, edgeState, citedSet } = useActiveRun();
```

Keep `useRunStore((s) => s.inspectedNode)` and `inspectNode` as-is — those are UI-local actions/state that must always track the live store.

- [ ] **Step 2: Swap RunningPhase.tsx**

Run: `rg -n "useRunStore" web/src/components/panel/phases/RunningPhase.tsx`.

For each run-state read (`traceLog`, `thinkingByAgent`, `answerText`, `cases`, `resolutions`), replace with `useActiveRun()`.

Add at top:

```typescript
import { useActiveRun } from '../../../hooks/useActiveRun';
```

Replace with (example):

```typescript
const { traceLog, thinkingByAgent, answerText, cases, resolutions } = useActiveRun();
```

Keep `status`, `question`, any UI-local actions from `useRunStore`.

- [ ] **Step 3: Swap AnswerReadyPhase.tsx**

Same treatment: imports `useActiveRun`, pulls `traceLog`, `thinkingByAgent`, `finalAnswer` from it. Keep `status`, `question`, `reset` from `useRunStore`.

- [ ] **Step 4: Swap InspectNodePhase.tsx**

Same treatment for any run-state reads. Keep `inspectedNode`, `closeInspector` from `useRunStore`.

- [ ] **Step 5: Typecheck + existing tests**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no TS errors; all existing tests still pass.

- [ ] **Step 6: Visual check**

Start backend + frontend. Ask the locked huur question; wait for the run to finish. Verify the panel + graph render identically to before (useActiveRun falls through to the live slice while `viewingHistoryId === null`).

- [ ] **Step 7: Commit**

```bash
git add web/src/components/graph/Graph.tsx web/src/components/panel/phases/*.tsx
git commit -m "refactor(web): components read run state via useActiveRun"
```

---

## Task 16: Frontend — typecheck, full frontend test suite, existing-feature regression

**Files:** none (verification only)

- [ ] **Step 1: Full frontend check**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: clean.

- [ ] **Step 2: Full backend check**

Run: `uv run pytest -v`
Expected: all existing tests pass; history tests pass.

- [ ] **Step 3: No commit needed if all green.**

If anything red: diagnose, fix, and commit in that task's diff. Do not mark this task completed until both suites are clean.

---

## Task 17: Manual E2E smoke test and final commit

**Files:** none (manual verification)

The plan is done when every checkbox in this task passes. Any failure here sends work back to the responsible task above.

- [ ] **Step 1: Start backend**

```bash
uv run python -m jurist.api
```

Wait for the `Anthropic client ready` log line.

- [ ] **Step 2: Start frontend**

```bash
cd web && npm run dev
```

Open `http://localhost:5173`.

- [ ] **Step 3: Baseline — clock icon + empty drawer**

- Clock icon visible top-left of the panel. No badge.
- Click it → drawer slides in from the left; shows "Nog geen eerdere vragen".
- Press Escape → drawer closes.

- [ ] **Step 4: Archive a successful run**

- Click "Vraag stellen" on the locked huur question.
- Wait for the answer to complete.
- Open drawer: 1 entry, green dot, question text, "net nu" (or similar).
- On disk: `ls data/history.json` → file exists. Inspect the JSON and confirm `version: 1`, one entry, `status: "finished"`, and `snapshot.traceLog` does **not** contain any `answer_delta` events.

- [ ] **Step 5: Quick-switch to the archived run**

- Click the entry in the drawer → drawer closes; "Je bekijkt een eerdere vraag · net nu" pill appears at top of panel.
- Panel shows the structured answer exactly as when it completed.
- Graph nodes cited in the answer are highlighted.
- Click "Terug naar live" → pill disappears; panel still shows the finished answer (live slice unchanged).

- [ ] **Step 6: Archive a failed run**

- Temporarily unset `ANTHROPIC_API_KEY` in the running backend shell and restart backend (`Ctrl+C` then re-run), OR force a failure another way.
- Ask the question again.
- Wait for failure.
- Drawer now shows 2 entries: newest has a red dot.

- [ ] **Step 7: Delete and clear**

- Hover an entry → an `×` appears on the right → click it → confirm → entry gone.
- Drawer still has 1 entry. "Wis alles" → confirm → empty state.
- `data/history.json` on disk reflects empty entries list.

- [ ] **Step 8: Disk persistence across reload**

- Ask the locked question once more to seed one entry.
- Full browser refresh (Ctrl+Shift+R).
- Reopen drawer → entry still there (proof that `hydrateHistory` ran and read from disk).

- [ ] **Step 9: FIFO eviction at 15**

- Ask short, fast-to-answer questions (any throwaway) 16 times, or use the dev tools console to seed via `useRunStore.setState({history: [...15 mock entries...]})` and then archive a 16th via a real run.
- After the 16th: drawer shows exactly 15, oldest is gone, newest on top.

- [ ] **Step 10: New-question flow from a historic view**

- With an archived entry visible via pill, click "Nieuwe vraag" → panel returns to idle, pill gone, drawer state unchanged.
- Ask another question. Verify it streams normally and archives on completion.

- [ ] **Step 11: Final commit**

If any untracked artifacts remain (e.g., `data/history.json` appeared in `git status` despite `.gitignore`), investigate the `.gitignore` rule before committing. Then:

```bash
git log --oneline -20
```

Should show the full chain of commits for this feature. No final squash needed.

---

## Self-Review (performed inline during plan authoring)

1. **Spec coverage:**
   - §3 Storage/schema → Tasks 1, 2.
   - §4 Backend → Tasks 1, 2, 3.
   - §5.1 Store changes → Tasks 7, 8, 9.
   - §5.2 historyApi → Task 5.
   - §5.3 Snapshot helpers → Task 4.
   - §5.4 useActiveRun → Task 6.
   - §5.5 UI components → Tasks 11, 12, 13.
   - §5.6 Panel integration → Task 14.
   - §5.7 Graph integration → Task 15.
   - §5.8 Phase components → Task 15.
   - §6 Behavior → exercised in Tasks 8, 9, and verified in Task 17.
   - §7 Edge cases → Tasks 8, 9 (tests for delete-of-active, clear-of-active, FIFO cap, hydrate failure); Task 17 for manual failure-archival.
   - §8 Testing → Tasks 2, 4, 6, 7, 8, 9, 10, 16, 17. Note testing-scope clarification up top: DOM-rendering tests skipped for two view-only components.
   - §9 File footprint → matches this plan's File Structure section.

2. **Placeholder scan:** No "TBD", "TODO", "implement later". Every code block is complete.

3. **Type consistency:**
   - `HistoryEntry` fields match across backend (`src/jurist/api/history.py`), frontend API wrapper (`historyApi.ts`), and store.
   - `RunSnapshot` / `ActiveRunView` shapes match between `snapshot.ts`, tests, and the archive action.
   - `archiveCurrent('finished' | 'failed')` signature matches the apply() call sites.
   - `selectActiveRun` signature matches the hook wrapper's call.
   - `HISTORY_CAP = 15` matches backend's `MAX_ENTRIES = 15`.
   - Test helper `mockFetchOk` is defined once (Task 8) and reused in Task 9 tests — Task 9's test block relies on the helper being in scope. It is, because both live in the same test file. Verified.

4. **Scope check:** Single plan, ~17 tasks, cohesive feature, no independent subsystems that need splitting.

5. **Ambiguity check:** Mid-run switch behavior, delete-of-active behavior, and FIFO eviction are all spelled out in both spec and plan with matching semantics.

No issues found. Plan ready for execution.
