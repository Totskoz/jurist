# Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-panel frontend with a full-viewport dark force-directed KG canvas plus a single right-docked, collapsible, phase-driven panel — without touching the backend, event protocol, or `runStore`'s existing state shape.

**Architecture:** `react-force-graph-2d` as the full-viewport canvas (cluster-colored nodes derived from the `title` field, degree-based sizing, top-15% labels). One right-docked panel driven by a derived phase (`idle | running | answer-ready | inspecting-node`) wrapped in `framer-motion`'s `AnimatePresence`. Pure logic (clustering, phase derivation, runStore reducers, math helpers) is TDD'd with Vitest; canvas drawing and transitions are verified manually at the end.

**Tech Stack:** React 18 + TypeScript, Zustand, Tailwind v3, `react-force-graph-2d` (new), `framer-motion` (new), Vitest (new, dev-only). Removing `@xyflow/react` + `dagre` at the end.

**Spec:** `docs/superpowers/specs/2026-04-22-frontend-redesign-design.md`

---

## Task 1: Add Vitest + swap dependencies

**Why first:** The TDD tasks below need a test runner. We also want the new graph/motion libs available before we build the graph, but we keep `@xyflow/react` + `dagre` until the final integration task so the existing app still builds during development.

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`
- Create: `web/src/test-setup.ts`

- [ ] **Step 1: Install runtime deps (keep old ones for now)**

Run:
```bash
cd web && npm install react-force-graph-2d@^1.26.1 framer-motion@^11.11.17
```

Expected: both packages install without peer-dep warnings against React 18.

- [ ] **Step 2: Install Vitest as a dev dep**

Run:
```bash
cd web && npm install -D vitest@^2.1.8
```

Expected: clean install.

- [ ] **Step 3: Create `web/vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
```

- [ ] **Step 4: Add a test script to `web/package.json`**

Edit the `"scripts"` block to include `"test": "vitest run"`. Final shape:

```json
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview",
  "test": "vitest run"
}
```

- [ ] **Step 5: Create `web/src/test-setup.ts` as an empty placeholder**

```ts
// Intentionally empty — reserved for future globals.
```

(Having the file in place means later tasks that add matchers or mocks have a home.)

- [ ] **Step 6: Sanity-check everything builds**

Run:
```bash
cd web && npx tsc --noEmit
cd web && npm run test
```

Expected: `tsc` prints no errors. `vitest` reports "No test files found" (which is fine — we haven't written tests yet).

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/src/test-setup.ts
git commit -m "chore(web): add vitest + react-force-graph-2d + framer-motion"
```

---

## Task 2: Add dark palette (CSS vars + `theme.ts` mirror)

**Files:**
- Modify: `web/src/index.css`
- Create: `web/src/theme.ts`

- [ ] **Step 1: Replace `web/src/index.css` with the dark theme root**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* Background */
  --bg-gradient-top: #0a0b0f;
  --bg-gradient-bot: #14161c;

  /* Panel */
  --panel-surface: rgba(20, 22, 28, 0.72);
  --panel-border: rgba(255, 255, 255, 0.08);

  /* Text */
  --text-primary: #e7eaf0;
  --text-secondary: #9098a8;
  --text-tertiary: #5d6370;

  /* Accent + error */
  --accent: #f5c24a;
  --error: #f07178;

  /* Edge */
  --edge-default: rgba(255, 255, 255, 0.08);

  /* Cluster palette */
  --cluster-verplichtingen: #7fa3e0;
  --cluster-algemeen: #7bcdc4;
  --cluster-bedrijfsruimte: #dece7b;
  --cluster-huurcommissie: #b397db;
  --cluster-eindigen: #e48fa8;
  --cluster-huurprijzen: #86cf9a;
  --cluster-overig: #6b7280;
}

html, body, #root {
  height: 100%;
}

body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  background: linear-gradient(to bottom, var(--bg-gradient-top), var(--bg-gradient-bot));
  color: var(--text-primary);
}
```

- [ ] **Step 2: Create `web/src/theme.ts` mirroring the CSS vars for canvas drawing**

```ts
export const CLUSTER_KEYS = [
  'verplichtingen',
  'algemeen',
  'bedrijfsruimte',
  'huurcommissie',
  'eindigen',
  'huurprijzen',
  'overig',
] as const;

export type ClusterKey = (typeof CLUSTER_KEYS)[number];

export const clusterColor: Record<ClusterKey, string> = {
  verplichtingen: '#7fa3e0',
  algemeen: '#7bcdc4',
  bedrijfsruimte: '#dece7b',
  huurcommissie: '#b397db',
  eindigen: '#e48fa8',
  huurprijzen: '#86cf9a',
  overig: '#6b7280',
};

export const clusterLabel: Record<ClusterKey, string> = {
  verplichtingen: 'Verplichtingen onder huur',
  algemeen: 'Algemeen',
  bedrijfsruimte: 'Huur van bedrijfsruimte',
  huurcommissie: 'Huurcommissie & procedure',
  eindigen: 'Eindigen van de huur',
  huurprijzen: 'Huurprijzen',
  overig: 'Overig',
};

export const color = {
  textPrimary: '#e7eaf0',
  textSecondary: '#9098a8',
  textTertiary: '#5d6370',
  accent: '#f5c24a',
  error: '#f07178',
  edgeDefault: 'rgba(255, 255, 255, 0.08)',
} as const;
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/index.css web/src/theme.ts
git commit -m "feat(web): dark palette + cluster color module"
```

---

## Task 3: `clusters.ts` — `clusterOf` + `shortLabelFor` (TDD)

**Files:**
- Create: `web/src/components/graph/clusters.ts`
- Create: `web/src/components/graph/clusters.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/graph/clusters.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { clusterOf, shortLabelFor } from './clusters';

type Node = { article_id: string; bwb_id: string; label: string; title: string };

const n = (article_id: string, bwb_id: string, label: string, title: string): Node =>
  ({ article_id, bwb_id, label, title });

describe('clusterOf', () => {
  it('maps De verplichtingen van de huurder → verplichtingen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling3/Artikel212', 'BWBR0005290', 'Boek 7, Artikel 212', 'De verplichtingen van de huurder'))).toBe('verplichtingen');
  });

  it('maps Verplichtingen van de verhuurder → verplichtingen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling2/Artikel203', 'BWBR0005290', 'Boek 7, Artikel 203', 'Verplichtingen van de verhuurder'))).toBe('verplichtingen');
  });

  it('maps Algemeen → algemeen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel232', 'BWBR0005290', 'Boek 7, Artikel 232', 'Algemeen'))).toBe('algemeen');
  });

  it('maps Algemene bepalingen → algemeen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling1/Artikel201', 'BWBR0005290', 'Boek 7, Artikel 201', 'Algemene bepalingen'))).toBe('algemeen');
  });

  it('maps Huur van bedrijfsruimte → bedrijfsruimte', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling6/Artikel290', 'BWBR0005290', 'Boek 7, Artikel 290', 'Huur van bedrijfsruimte'))).toBe('bedrijfsruimte');
  });

  it('maps Instelling... huurcommissie → huurcommissie', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf1/Artikel2', 'BWBR0014315', 'Uhw, Artikel 2', 'Instelling, inrichting en samenstelling van de huurcommissie'))).toBe('huurcommissie');
  });

  it('maps De uitspraak en verdere bepalingen → huurcommissie', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf3/Artikel20', 'BWBR0014315', 'Uhw, Artikel 20', 'De uitspraak en verdere bepalingen'))).toBe('huurcommissie');
  });

  it('maps any unmatched Uhw title → huurcommissie (bwb_id fallback)', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf5/Artikel36', 'BWBR0014315', 'Uhw, Artikel 36', 'Taken van de huurcommissie'))).toBe('huurcommissie');
  });

  it('maps Het eindigen van de huur → eindigen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling4/Artikel271', 'BWBR0005290', 'Boek 7, Artikel 271', 'Het eindigen van de huur'))).toBe('eindigen');
  });

  it('maps Huurprijzen → huurprijzen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel247', 'BWBR0005290', 'Boek 7, Artikel 247', 'Huurprijzen'))).toBe('huurprijzen');
  });

  it('maps Overgangs- en slotbepalingen → overig', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel270a', 'BWBR0005290', 'Boek 7, Artikel 270a', 'Overgangs- en slotbepalingen'))).toBe('overig');
  });

  it('defaults unknown BW titles to overig', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel999', 'BWBR0005290', 'Boek 7, Artikel 999', 'Some Unknown Title'))).toBe('overig');
  });
});

describe('shortLabelFor', () => {
  it('formats BW article as Boek:Artikel', () => {
    expect(shortLabelFor({ article_id: 'BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel247', bwb_id: 'BWBR0005290', label: 'Boek 7, Artikel 247', title: '' })).toBe('7:247');
  });

  it('formats BW sub-article variant (Artikel270a)', () => {
    expect(shortLabelFor({ article_id: 'BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel270a', bwb_id: 'BWBR0005290', label: 'Boek 7, Artikel 270a', title: '' })).toBe('7:270a');
  });

  it('formats Uhw article as "Uhw N"', () => {
    expect(shortLabelFor({ article_id: 'BWBR0014315/Artikel10', bwb_id: 'BWBR0014315', label: 'Uhw, Artikel 10', title: '' })).toBe('Uhw 10');
  });

  it('formats Uhw sub-article variant as "Uhw 4a"', () => {
    expect(shortLabelFor({ article_id: 'BWBR0014315/Paragraaf1/Artikel4a', bwb_id: 'BWBR0014315', label: 'Uhw, Artikel 4a', title: '' })).toBe('Uhw 4a');
  });

  it('falls back to node.label for unrecognised patterns', () => {
    expect(shortLabelFor({ article_id: 'BWBR0099999/Weird/Path', bwb_id: 'BWBR0099999', label: 'Fallback Label', title: '' })).toBe('Fallback Label');
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd web && npm run test -- clusters`
Expected: all fail with "clusterOf is not a function" or equivalent.

- [ ] **Step 3: Implement `web/src/components/graph/clusters.ts`**

```ts
import type { ClusterKey } from '../../theme';

export interface KgNodeLike {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
}

const TITLE_TO_CLUSTER: Record<string, ClusterKey> = {
  'De verplichtingen van de huurder': 'verplichtingen',
  'Verplichtingen van de verhuurder': 'verplichtingen',
  'Algemeen': 'algemeen',
  'Algemene bepalingen': 'algemeen',
  'Huur van bedrijfsruimte': 'bedrijfsruimte',
  'Instelling, inrichting en samenstelling van de huurcommissie': 'huurcommissie',
  'De uitspraak en verdere bepalingen': 'huurcommissie',
  'Het eindigen van de huur': 'eindigen',
  'Huurprijzen': 'huurprijzen',
};

const UHW_BWB = 'BWBR0014315';

export function clusterOf(node: KgNodeLike): ClusterKey {
  const direct = TITLE_TO_CLUSTER[node.title];
  if (direct) return direct;
  if (node.bwb_id === UHW_BWB) return 'huurcommissie';
  return 'overig';
}

const BW_ARTICLE_RE = /\/Boek(\d+)\/.*Artikel([\w]+)$/;
const UHW_ARTICLE_RE = /Artikel([\w]+)$/;

export function shortLabelFor(node: KgNodeLike): string {
  if (node.bwb_id === 'BWBR0005290') {
    const m = BW_ARTICLE_RE.exec(node.article_id);
    if (m) return `${m[1]}:${m[2]}`;
  }
  if (node.bwb_id === UHW_BWB) {
    const m = UHW_ARTICLE_RE.exec(node.article_id);
    if (m) return `Uhw ${m[1]}`;
  }
  return node.label;
}
```

- [ ] **Step 4: Run tests — they should all pass**

Run: `cd web && npm run test -- clusters`
Expected: all tests pass.

- [ ] **Step 5: Property test — every real KG node maps to a cluster**

Append to `web/src/components/graph/clusters.test.ts`:

```ts
import kgData from '../../../../data/kg/huurrecht.json';

describe('clusterOf — real data coverage', () => {
  it('every KG node maps to exactly one cluster', () => {
    const kg = kgData as { nodes: KgNodeLike[] };
    const seen = new Set<string>();
    for (const node of kg.nodes) {
      const key = clusterOf(node);
      expect(['verplichtingen', 'algemeen', 'bedrijfsruimte', 'huurcommissie', 'eindigen', 'huurprijzen', 'overig']).toContain(key);
      seen.add(key);
    }
    // Sanity: at least 5 of the 7 buckets are non-empty on real data.
    expect(seen.size).toBeGreaterThanOrEqual(5);
  });
});
```

Also add `"resolveJsonModule": true` is already in `tsconfig.json` (verified) — JSON import works.

Need to allow TS to import JSON from outside `src`. Update `web/tsconfig.json` `include` to add the KG file:

```json
"include": ["src", "../data/kg/huurrecht.json"]
```

- [ ] **Step 6: Run the new property test**

Run: `cd web && npm run test -- clusters`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/graph/clusters.ts web/src/components/graph/clusters.test.ts web/tsconfig.json
git commit -m "feat(web): cluster lookup + short-label helper (TDD)"
```

---

## Task 4: State layer — `runStore` additions + `usePhase` hook (TDD)

**Files:**
- Modify: `web/src/state/runStore.ts`
- Create: `web/src/state/runStore.test.ts`
- Create: `web/src/hooks/usePhase.ts`
- Create: `web/src/hooks/usePhase.test.ts`

- [ ] **Step 1: Write failing tests for `runStore`**

Create `web/src/state/runStore.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest';
import { useRunStore } from './runStore';
import type { TraceEvent } from '../types/events';

const ev = (type: string, data: Record<string, unknown> = {}, agent = 'synthesizer'): TraceEvent =>
  ({ type, data, agent, run_id: 'r1', ts: '2026-04-22T00:00:00Z' } as TraceEvent);

describe('runStore — new UI fields', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('initializes inspectedNode=null, panelCollapsed=false, citedSet empty', () => {
    const s = useRunStore.getState();
    expect(s.inspectedNode).toBeNull();
    expect(s.panelCollapsed).toBe(false);
    expect(s.citedSet.size).toBe(0);
  });

  it('inspectNode sets inspectedNode', () => {
    useRunStore.getState().inspectNode('BWBR0005290/.../Artikel247');
    expect(useRunStore.getState().inspectedNode).toBe('BWBR0005290/.../Artikel247');
  });

  it('closeInspector clears inspectedNode', () => {
    useRunStore.getState().inspectNode('some-id');
    useRunStore.getState().closeInspector();
    expect(useRunStore.getState().inspectedNode).toBeNull();
  });

  it('toggleCollapse flips panelCollapsed', () => {
    expect(useRunStore.getState().panelCollapsed).toBe(false);
    useRunStore.getState().toggleCollapse();
    expect(useRunStore.getState().panelCollapsed).toBe(true);
    useRunStore.getState().toggleCollapse();
    expect(useRunStore.getState().panelCollapsed).toBe(false);
  });
});

describe('runStore — run_finished populates citedSet', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('populates citedSet from final_answer.relevante_wetsartikelen', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');

    // Pretend the retriever visited 4 nodes.
    for (const aid of ['A', 'B', 'C', 'D']) {
      store.apply(ev('node_visited', { article_id: aid }));
    }

    const finishEv = ev('run_finished', {
      final_answer: {
        kind: 'answer',
        korte_conclusie: '',
        relevante_wetsartikelen: [
          { bwb_id: 'A', article_label: '', quote: '', explanation: '' },
          { bwb_id: 'C', article_label: '', quote: '', explanation: '' },
        ],
        vergelijkbare_uitspraken: [],
        aanbeveling: '',
      },
    });
    store.apply(finishEv);

    const s = useRunStore.getState();
    expect(s.citedSet.has('A')).toBe(true);
    expect(s.citedSet.has('C')).toBe(true);
    expect(s.citedSet.has('B')).toBe(false);
    expect(s.citedSet.has('D')).toBe(false);

    // Only cited nodes flip to `cited`; others stay visited.
    expect(s.kgState.get('A')).toBe('cited');
    expect(s.kgState.get('C')).toBe('cited');
    expect(s.kgState.get('B')).toBe('visited');
    expect(s.kgState.get('D')).toBe('visited');
  });

  it('handles insufficient_context answers with empty citations', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');
    store.apply(ev('node_visited', { article_id: 'X' }));
    store.apply(ev('run_finished', {
      final_answer: {
        kind: 'insufficient_context',
        reason: 'out-of-scope',
      },
    }));
    expect(useRunStore.getState().citedSet.size).toBe(0);
    // Visited stays visited, not promoted to cited.
    expect(useRunStore.getState().kgState.get('X')).toBe('visited');
  });
});
```

- [ ] **Step 2: Run tests to see failure**

Run: `cd web && npm run test -- runStore`
Expected: all new tests fail — fields don't exist, actions don't exist.

- [ ] **Step 3: Modify `web/src/state/runStore.ts`**

Add to the `RunState` interface (keep everything that exists):

```ts
// in RunState interface, add:
inspectedNode: string | null;
panelCollapsed: boolean;
citedSet: Set<string>;

inspectNode: (articleId: string) => void;
closeInspector: () => void;
toggleCollapse: () => void;
```

In the `create<RunState>((set, get) => ({ ... }))` initial object, add:

```ts
inspectedNode: null,
panelCollapsed: false,
citedSet: new Set(),

inspectNode: (articleId) => set({ inspectedNode: articleId }),
closeInspector: () => set({ inspectedNode: null }),
toggleCollapse: () => set((s) => ({ panelCollapsed: !s.panelCollapsed })),
```

In `start`, add the three new fields resetting (so new runs don't carry over inspect/citedSet; keep panelCollapsed as-is across runs — user preference is sticky):

```ts
start: (runId, question) =>
  set({
    runId,
    question,
    status: 'running',
    kgState: new Map(),
    edgeState: new Map(),
    traceLog: [],
    thinkingByAgent: {},
    answerText: '',
    finalAnswer: null,
    cases: [],
    resolutions: [],
    inspectedNode: null,
    citedSet: new Set(),
    // panelCollapsed intentionally NOT reset — user's collapse preference persists.
  }),
```

Same fields in `reset` except reset `panelCollapsed: false` too.

Replace the `run_finished` case in the `apply` reducer with:

```ts
case 'run_finished': {
  const finalAnswer = (ev.data.final_answer as StructuredAnswer) ?? null;
  const citedSet = new Set<string>();
  if (finalAnswer && finalAnswer.kind === 'answer') {
    for (const art of finalAnswer.relevante_wetsartikelen ?? []) {
      if (art.bwb_id) citedSet.add(art.bwb_id);
    }
  }
  const next = new Map(s.kgState);
  // Demote any still-current to visited first.
  for (const [k, v] of next) {
    if (v === 'current') next.set(k, 'visited');
  }
  // Only promote cited articles to `cited`.
  for (const aid of citedSet) {
    next.set(aid, 'cited');
  }
  set({ traceLog, kgState: next, status: 'finished', finalAnswer, citedSet });
  return;
}
```

- [ ] **Step 4: Run tests — runStore tests should pass**

Run: `cd web && npm run test -- runStore`
Expected: all pass.

- [ ] **Step 5: Write failing tests for `usePhase`**

Create `web/src/hooks/usePhase.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { derivePhase } from './usePhase';
import type { RunStatus } from '../state/runStore';

describe('derivePhase', () => {
  const table: Array<[RunStatus, string | null, string]> = [
    ['idle', null, 'idle'],
    ['running', null, 'running'],
    ['finished', null, 'answer-ready'],
    ['failed', null, 'answer-ready'],
    ['idle', 'some-id', 'inspecting-node'],
    ['running', 'some-id', 'inspecting-node'],
    ['finished', 'some-id', 'inspecting-node'],
    ['failed', 'some-id', 'inspecting-node'],
  ];

  for (const [status, inspected, expected] of table) {
    it(`${status} + inspected=${inspected ?? 'null'} → ${expected}`, () => {
      expect(derivePhase(status, inspected)).toBe(expected);
    });
  }
});
```

- [ ] **Step 6: Run tests to see failure**

Run: `cd web && npm run test -- usePhase`
Expected: fails — module doesn't exist.

- [ ] **Step 7: Implement `web/src/hooks/usePhase.ts`**

```ts
import { useRunStore, type RunStatus } from '../state/runStore';

export type PhaseKey = 'idle' | 'running' | 'answer-ready' | 'inspecting-node';

export function derivePhase(status: RunStatus, inspectedNode: string | null): PhaseKey {
  if (inspectedNode) return 'inspecting-node';
  if (status === 'running') return 'running';
  if (status === 'finished' || status === 'failed') return 'answer-ready';
  return 'idle';
}

export function usePhase(): PhaseKey {
  const status = useRunStore((s) => s.status);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  return derivePhase(status, inspectedNode);
}
```

- [ ] **Step 8: Run all tests**

Run: `cd web && npm run test`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add web/src/state/runStore.ts web/src/state/runStore.test.ts web/src/hooks/usePhase.ts web/src/hooks/usePhase.test.ts
git commit -m "feat(web): runStore UI state + usePhase derivation (TDD)"
```

---

## Task 5: Node-render math helpers (TDD)

**Files:**
- Create: `web/src/components/graph/nodeRender.ts` (initial — math only, drawing added in Task 8)
- Create: `web/src/components/graph/nodeRender.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/components/graph/nodeRender.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { radiusFromDegree, shouldShowLabel } from './nodeRender';

describe('radiusFromDegree', () => {
  it('degree 0 → 4 px', () => {
    expect(radiusFromDegree(0)).toBe(4);
  });

  it('degree 1 → 5.8 px', () => {
    expect(radiusFromDegree(1)).toBeCloseTo(5.8, 2);
  });

  it('degree 16 → ~11.2 px', () => {
    expect(radiusFromDegree(16)).toBeCloseTo(11.2, 2);
  });

  it('is monotonic in degree', () => {
    for (let d = 0; d < 20; d++) {
      expect(radiusFromDegree(d + 1)).toBeGreaterThan(radiusFromDegree(d));
    }
  });
});

describe('shouldShowLabel', () => {
  it('shows labels for top ~15% (default threshold 0.15)', () => {
    // 218 nodes; top 15% = top 32.7 → rank 0..32 should be true, 33+ false.
    const total = 218;
    expect(shouldShowLabel(0, total)).toBe(true);
    expect(shouldShowLabel(30, total)).toBe(true);
    expect(shouldShowLabel(32, total)).toBe(true);
    expect(shouldShowLabel(33, total)).toBe(false);
    expect(shouldShowLabel(100, total)).toBe(false);
  });

  it('handles edge cases: 0 total, 1 total', () => {
    expect(shouldShowLabel(0, 0)).toBe(false);
    expect(shouldShowLabel(0, 1)).toBe(true);
  });
});
```

- [ ] **Step 2: Run to see failure**

Run: `cd web && npm run test -- nodeRender`
Expected: fails — module missing.

- [ ] **Step 3: Implement math helpers**

Create `web/src/components/graph/nodeRender.ts`:

```ts
export function radiusFromDegree(degree: number): number {
  return 4 + 1.8 * Math.sqrt(Math.max(0, degree));
}

const DEFAULT_LABEL_FRACTION = 0.15;

export function shouldShowLabel(
  rankByDegree: number,
  totalNodes: number,
  fraction = DEFAULT_LABEL_FRACTION
): boolean {
  if (totalNodes <= 0) return false;
  const cutoff = Math.floor(totalNodes * fraction);
  return rankByDegree <= cutoff;
}
```

- [ ] **Step 4: Run — all green**

Run: `cd web && npm run test -- nodeRender`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/graph/nodeRender.ts web/src/components/graph/nodeRender.test.ts
git commit -m "feat(web): node-render math helpers (TDD)"
```

---

## Task 6: `useKgData` hook + dangling-ref validation

**Files:**
- Create: `web/src/hooks/useKgData.ts`
- Create: `web/src/hooks/useKgData.test.ts`

- [ ] **Step 1: Write failing tests for the pure validator**

Create `web/src/hooks/useKgData.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { validateKgData } from './useKgData';

describe('validateKgData', () => {
  it('filters out edges whose source or target is not a known node', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' },
        { from_id: 'A', to_id: 'GHOST', kind: 'explicit' },
        { from_id: 'GHOST', to_id: 'B', kind: 'explicit' },
      ],
    };
    const result = validateKgData(raw);
    expect(result.edges).toHaveLength(1);
    expect(result.edges[0]).toMatchObject({ from_id: 'A', to_id: 'B' });
  });

  it('computes degree per node', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'C', bwb_id: 'BWBR1', label: 'C', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' },
        { from_id: 'A', to_id: 'C', kind: 'explicit' },
      ],
    };
    const result = validateKgData(raw);
    expect(result.degree.get('A')).toBe(2);
    expect(result.degree.get('B')).toBe(1);
    expect(result.degree.get('C')).toBe(1);
  });

  it('ranks nodes by degree descending (ties broken by article_id)', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'C', bwb_id: 'BWBR1', label: 'C', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' },
        { from_id: 'A', to_id: 'C', kind: 'explicit' },
      ],
    };
    const result = validateKgData(raw);
    expect(result.rankByDegree.get('A')).toBe(0); // highest
    // B and C tie; deterministic by article_id.
    expect(result.rankByDegree.get('B')).toBe(1);
    expect(result.rankByDegree.get('C')).toBe(2);
  });
});
```

- [ ] **Step 2: Run to see failure**

Run: `cd web && npm run test -- useKgData`
Expected: fails.

- [ ] **Step 3: Implement the hook**

Create `web/src/hooks/useKgData.ts`:

```ts
import { useEffect, useState } from 'react';

export interface KgNode {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
  body_text: string;
  outgoing_refs: string[];
}

export interface KgEdge {
  from_id: string;
  to_id: string;
  kind: 'explicit' | 'regex';
}

export interface ValidatedKg {
  nodes: KgNode[];
  edges: KgEdge[];
  degree: Map<string, number>;
  rankByDegree: Map<string, number>;
}

export function validateKgData(raw: { nodes: KgNode[]; edges: KgEdge[] }): ValidatedKg {
  const ids = new Set(raw.nodes.map((n) => n.article_id));
  const edges = raw.edges.filter((e) => ids.has(e.from_id) && ids.has(e.to_id));

  const degree = new Map<string, number>();
  for (const n of raw.nodes) degree.set(n.article_id, 0);
  for (const e of edges) {
    degree.set(e.from_id, (degree.get(e.from_id) ?? 0) + 1);
    degree.set(e.to_id, (degree.get(e.to_id) ?? 0) + 1);
  }

  const sorted = [...raw.nodes].sort((a, b) => {
    const dDiff = (degree.get(b.article_id) ?? 0) - (degree.get(a.article_id) ?? 0);
    if (dDiff !== 0) return dDiff;
    return a.article_id.localeCompare(b.article_id);
  });
  const rankByDegree = new Map<string, number>();
  sorted.forEach((n, i) => rankByDegree.set(n.article_id, i));

  return { nodes: raw.nodes, edges, degree, rankByDegree };
}

export type KgDataStatus = 'loading' | 'ready' | 'error';

export function useKgData(): { status: KgDataStatus; data: ValidatedKg | null; retry: () => void } {
  const [status, setStatus] = useState<KgDataStatus>('loading');
  const [data, setData] = useState<ValidatedKg | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    fetch('/api/kg')
      .then((r) => {
        if (!r.ok) throw new Error(`KG fetch failed: ${r.status}`);
        return r.json();
      })
      .then((raw: { nodes: KgNode[]; edges: KgEdge[] }) => {
        if (cancelled) return;
        setData(validateKgData(raw));
        setStatus('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return { status, data, retry: () => setAttempt((a) => a + 1) };
}
```

- [ ] **Step 4: Run tests — green**

Run: `cd web && npm run test -- useKgData`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useKgData.ts web/src/hooks/useKgData.test.ts
git commit -m "feat(web): useKgData hook with dangling-ref filter + degree ranking (TDD)"
```

---

## Task 7: `forceConfig.ts` — force-simulation tuning

**Files:**
- Create: `web/src/components/graph/forceConfig.ts`

- [ ] **Step 1: Create the module**

This is a configuration-only module — no test needed; it's a set of constants consumed by the Graph component.

```ts
/**
 * Force simulation tuning for react-force-graph-2d.
 * Picked to produce a layout resembling the reference image for ~218 nodes.
 */
export const FORCE_CONFIG = {
  // How many ticks of simulation run before we freeze the layout.
  cooldownTicks: 150,
  // How warm the simulation starts (0..1). 0.3 = moderate shake-out.
  warmupTicks: 0,
  // Link distance (between linked nodes).
  linkDistance: 60,
  // Charge strength — negative = repulsion. Stronger repulsion spreads clusters.
  chargeStrength: -90,
  // Collision radius multiplier over rendered node radius.
  collisionFactor: 1.2,
} as const;
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/graph/forceConfig.ts
git commit -m "feat(web): force-simulation tuning constants"
```

---

## Task 8: Canvas drawing functions — `nodeRender` + `edgeRender`

**Files:**
- Modify: `web/src/components/graph/nodeRender.ts`
- Create: `web/src/components/graph/edgeRender.ts`

- [ ] **Step 1: Extend `nodeRender.ts` with canvas drawing functions**

Append to `web/src/components/graph/nodeRender.ts`:

```ts
import { clusterColor, color, type ClusterKey } from '../../theme';
import type { NodeState } from '../../state/runStore';

export interface RenderableNode {
  article_id: string;
  cluster: ClusterKey;
  degree: number;
  rank: number;
  label: string;
  state: NodeState;
  x?: number;
  y?: number;
  isInspected: boolean;
  totalNodes: number;
}

export function drawNode(
  node: RenderableNode,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  pulseT: number
): void {
  if (node.x === undefined || node.y === undefined) return;
  const r = radiusFromDegree(node.degree);
  const fill = clusterColor[node.cluster];

  // Halo (current pulse OR cited persistent glow).
  if (node.state === 'current') {
    const haloR = r * 2 + pulseT * 4;
    const haloAlpha = 0.4 * (1 - pulseT);
    ctx.beginPath();
    ctx.fillStyle = hexToRgba(color.accent, haloAlpha);
    ctx.arc(node.x, node.y, haloR, 0, Math.PI * 2);
    ctx.fill();
  } else if (node.state === 'cited') {
    ctx.beginPath();
    ctx.fillStyle = hexToRgba(fill, 0.35);
    ctx.arc(node.x, node.y, r * 1.8, 0, Math.PI * 2);
    ctx.fill();
  }

  // Core fill.
  ctx.beginPath();
  const coreAlpha = node.state === 'default' ? 0.55 : 1.0;
  ctx.fillStyle = hexToRgba(fill, coreAlpha);
  ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
  ctx.fill();

  // Stroke.
  let strokeColor: string | null = null;
  let strokeWidth = 0;
  if (node.isInspected) {
    strokeColor = 'rgba(255,255,255,0.7)';
    strokeWidth = 1.5;
  } else if (node.state === 'current') {
    strokeColor = color.accent;
    strokeWidth = 2;
  } else if (node.state === 'visited') {
    strokeColor = fill;
    strokeWidth = 1;
  }
  if (strokeColor) {
    ctx.beginPath();
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = strokeWidth / globalScale;
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Label for top ~15%.
  if (shouldShowLabel(node.rank, node.totalNodes)) {
    const fontSize = 10 / globalScale;
    ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.lineWidth = 3 / globalScale;
    ctx.strokeStyle = 'rgba(10, 11, 15, 0.9)';
    ctx.strokeText(node.label, node.x, node.y + r + 2);
    ctx.fillStyle = color.textPrimary;
    ctx.fillText(node.label, node.x, node.y + r + 2);
  }
}

function hexToRgba(hex: string, alpha: number): string {
  // Accepts #rrggbb OR rgba(...) passthrough.
  if (hex.startsWith('rgba')) return hex;
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
```

- [ ] **Step 2: Create `edgeRender.ts`**

```ts
import { clusterColor, color, type ClusterKey } from '../../theme';
import type { EdgeState } from '../../state/runStore';

export interface RenderableEdge {
  source: { x?: number; y?: number };
  target: { x?: number; y?: number };
  targetCluster: ClusterKey;
  state: EdgeState;
  sweepProgress: number; // 0 = not sweeping, 1 = full sweep complete; animation only
}

export function drawEdge(edge: RenderableEdge, ctx: CanvasRenderingContext2D, globalScale: number): void {
  const sx = edge.source.x, sy = edge.source.y, tx = edge.target.x, ty = edge.target.y;
  if (sx === undefined || sy === undefined || tx === undefined || ty === undefined) return;

  const isTraversed = edge.state === 'traversed';
  const stroke = isTraversed ? hexToRgba(clusterColor[edge.targetCluster], 0.4) : color.edgeDefault;
  const width = (isTraversed ? 1.5 : 1) / globalScale;

  ctx.beginPath();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  ctx.moveTo(sx, sy);
  ctx.lineTo(tx, ty);
  ctx.stroke();

  // Sweep overlay (drawn on top during animation).
  if (edge.sweepProgress > 0 && edge.sweepProgress < 1) {
    const t = edge.sweepProgress;
    const hx = sx + (tx - sx) * t;
    const hy = sy + (ty - sy) * t;
    ctx.beginPath();
    ctx.strokeStyle = color.accent;
    ctx.lineWidth = 2.5 / globalScale;
    ctx.moveTo(sx, sy);
    ctx.lineTo(hx, hy);
    ctx.stroke();
  }
}

function hexToRgba(hex: string, alpha: number): string {
  if (hex.startsWith('rgba')) return hex;
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. Note: existing tests for `nodeRender` still pass (we only appended — didn't change math helpers).

Run: `cd web && npm run test`
Expected: all previous tests still pass.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/graph/nodeRender.ts web/src/components/graph/edgeRender.ts
git commit -m "feat(web): canvas drawing functions for nodes and edges"
```

---

## Task 9: `Graph.tsx` — full-viewport force graph

**Files:**
- Create: `web/src/components/graph/Graph.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import ForceGraph2D from 'react-force-graph-2d';
import { useRunStore } from '../../state/runStore';
import { useKgData } from '../../hooks/useKgData';
import { clusterOf, shortLabelFor } from './clusters';
import { FORCE_CONFIG } from './forceConfig';
import { drawNode, type RenderableNode } from './nodeRender';
import { drawEdge, type RenderableEdge } from './edgeRender';
import type { ClusterKey } from '../../theme';
import type { EdgeState, NodeState } from '../../state/runStore';

interface GraphNode {
  id: string;
  cluster: ClusterKey;
  degree: number;
  rank: number;
  label: string;
  title: string;
}

interface GraphLink {
  source: string;
  target: string;
  targetCluster: ClusterKey;
}

// Edge sweeps in-flight: key = "from::to", value = start-timestamp (ms).
const SWEEP_DURATION_MS = 200;
const SWEEP_THROTTLE_MS = 80;

export default function Graph() {
  const { status, data, retry } = useKgData();
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Subscribe narrowly.
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const inspectNode = useRunStore((s) => s.inspectNode);

  // Active sweeps: key = "from::to", value = start-timestamp (ms).
  const sweeps = useRef<Map<string, number>>(new Map());
  // Queue of edge keys waiting to start sweeping (throttled by SWEEP_THROTTLE_MS).
  const sweepQueue = useRef<string[]>([]);
  const lastSweepStart = useRef<number>(0);
  const prevEdgeState = useRef<typeof edgeState>(new Map());

  // Enqueue a sweep whenever an edge transitions to "traversed".
  useEffect(() => {
    for (const [k, v] of edgeState) {
      if (v === 'traversed' && prevEdgeState.current.get(k) !== 'traversed') {
        if (!sweeps.current.has(k) && !sweepQueue.current.includes(k)) {
          sweepQueue.current.push(k);
        }
      }
    }
    prevEdgeState.current = edgeState;
  }, [edgeState]);

  // Animate pulse + sweep queue via rAF.
  const pulseRef = useRef(0);
  useEffect(() => {
    let frameId = 0;
    const tick = () => {
      const now = performance.now();
      pulseRef.current = (now / 666) % 1; // 1.5 Hz

      // Pop queue at most one per SWEEP_THROTTLE_MS.
      while (sweepQueue.current.length > 0 && now - lastSweepStart.current >= SWEEP_THROTTLE_MS) {
        const key = sweepQueue.current.shift()!;
        sweeps.current.set(key, now);
        lastSweepStart.current = now;
      }

      // Clean up expired sweeps.
      for (const [k, start] of sweeps.current) {
        if (now - start >= SWEEP_DURATION_MS) sweeps.current.delete(k);
      }

      fgRef.current?.refresh();
      frameId = requestAnimationFrame(tick);
    };
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, []);

  // Resize observer for full-viewport sizing.
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setSize({ w: rect.width, h: rect.height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodeMap = new Map<string, ClusterKey>();
    const nodes: GraphNode[] = data.nodes.map((n) => {
      const cl = clusterOf(n);
      nodeMap.set(n.article_id, cl);
      return {
        id: n.article_id,
        cluster: cl,
        degree: data.degree.get(n.article_id) ?? 0,
        rank: data.rankByDegree.get(n.article_id) ?? 999,
        label: shortLabelFor(n),
        title: n.title,
      };
    });
    const links: GraphLink[] = data.edges.map((e) => ({
      source: e.from_id,
      target: e.to_id,
      targetCluster: nodeMap.get(e.to_id) ?? 'overig',
    }));
    return { nodes, links };
  }, [data]);

  if (status === 'loading') {
    return <div style={{ color: 'var(--text-secondary)', padding: 24 }}>Kennisgraaf laden…</div>;
  }
  if (status === 'error' || !data) {
    return (
      <div style={{ color: 'var(--text-primary)', padding: 24, textAlign: 'center' }}>
        <p style={{ marginBottom: 12 }}>Kon de kennisgraaf niet laden.</p>
        <button onClick={retry} style={{
          padding: '8px 16px',
          background: 'var(--accent)',
          color: '#000',
          border: 'none',
          borderRadius: 6,
          cursor: 'pointer',
        }}>Opnieuw proberen</button>
      </div>
    );
  }

  const totalNodes = graphData.nodes.length;

  return (
    <div ref={containerRef} style={{ position: 'fixed', inset: 0, background: 'transparent' }}>
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData as any}
        width={size.w}
        height={size.h}
        cooldownTicks={FORCE_CONFIG.cooldownTicks}
        d3AlphaDecay={0.02}
        linkDirectionalArrowLength={0}
        enableNodeDrag={false}
        backgroundColor="rgba(0,0,0,0)"
        nodeRelSize={1}
        linkCanvasObjectMode={() => 'replace'}
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          const state: NodeState = kgState.get(node.id) ?? 'default';
          const renderable: RenderableNode = {
            article_id: node.id,
            cluster: node.cluster,
            degree: node.degree,
            rank: node.rank,
            label: node.label,
            state,
            x: node.x,
            y: node.y,
            isInspected: inspectedNode === node.id,
            totalNodes,
          };
          drawNode(renderable, ctx, globalScale, pulseRef.current);
        }}
        nodePointerAreaPaint={(node: any, paintColor, ctx) => {
          // Hit-test area — larger than visual for easier clicking.
          ctx.fillStyle = paintColor;
          ctx.beginPath();
          ctx.arc(node.x, node.y, Math.max(8, 4 + 1.8 * Math.sqrt(node.degree)), 0, Math.PI * 2);
          ctx.fill();
        }}
        onNodeClick={(node: any) => inspectNode(node.id)}
        linkCanvasObject={(link: any, ctx, globalScale) => {
          const key = `${link.source.id ?? link.source}::${link.target.id ?? link.target}`;
          const state: EdgeState = edgeState.get(key) ?? 'default';
          const sweepStart = sweeps.current.get(key);
          const sweepProgress = sweepStart ? Math.min(1, (performance.now() - sweepStart) / SWEEP_DURATION_MS) : 0;
          const renderable: RenderableEdge = {
            source: link.source,
            target: link.target,
            targetCluster: link.targetCluster,
            state,
            sweepProgress,
          };
          drawEdge(renderable, ctx, globalScale);
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. If `react-force-graph-2d` has no bundled types, add a `// @ts-expect-error` above the import or install `@types/react-force-graph-2d` if it exists. (At time of writing the package ships its own `.d.ts` — the `any` ref typing is intentional since the lib's ref type is loose.)

- [ ] **Step 3: Commit**

```bash
git add web/src/components/graph/Graph.tsx
git commit -m "feat(web): full-viewport force-directed Graph component"
```

---

## Task 10: `ClusterLegend` + `NodeTooltip`

**Files:**
- Create: `web/src/components/graph/ClusterLegend.tsx`
- Create: `web/src/components/graph/NodeTooltip.tsx`

- [ ] **Step 1: Create `ClusterLegend.tsx`**

```tsx
import { CLUSTER_KEYS, clusterColor, clusterLabel } from '../../theme';

export default function ClusterLegend() {
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 16,
        left: 16,
        padding: '12px 14px',
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 10,
        fontSize: 12,
        color: 'var(--text-secondary)',
        zIndex: 10,
      }}
    >
      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>Clusters</div>
      {CLUSTER_KEYS.map((key) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: clusterColor[key],
            }}
          />
          <span>{clusterLabel[key]}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create `NodeTooltip.tsx`**

```tsx
interface NodeTooltipProps {
  label: string;
  title: string;
  x: number;
  y: number;
}

export default function NodeTooltip({ label, title, x, y }: NodeTooltipProps) {
  return (
    <div
      style={{
        position: 'fixed',
        left: x + 12,
        top: y + 12,
        padding: '8px 10px',
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 6,
        fontSize: 12,
        color: 'var(--text-primary)',
        pointerEvents: 'none',
        zIndex: 20,
        maxWidth: 260,
      }}
    >
      <div style={{ fontWeight: 600 }}>{label}</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 2 }}>{title}</div>
    </div>
  );
}
```

- [ ] **Step 3: Wire tooltip into `Graph.tsx`**

Modify `web/src/components/graph/Graph.tsx`:

Add import at the top:
```tsx
import NodeTooltip from './NodeTooltip';
```

Add tooltip state near the other `useState`:
```tsx
const [hover, setHover] = useState<{ label: string; title: string; x: number; y: number } | null>(null);
```

Pass `onNodeHover` to `<ForceGraph2D>`:
```tsx
onNodeHover={(node: any, _prev: any) => {
  if (node) {
    setHover({ label: node.label, title: node.title, x: 0, y: 0 });
  } else {
    setHover(null);
  }
}}
```

And a mouse-move tracker on the container to position the tooltip (since the lib's hover doesn't give us client coords):

```tsx
onMouseMove={(e) => {
  if (hover) setHover((h) => (h ? { ...h, x: e.clientX, y: e.clientY } : null));
}}
```

(Add that `onMouseMove` on the outer `<div ref={containerRef} ...>`.)

Render the tooltip at the bottom of the component's JSX, after `</ForceGraph2D>`:
```tsx
{hover && <NodeTooltip label={hover.label} title={hover.title} x={hover.x} y={hover.y} />}
```

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/graph/ClusterLegend.tsx web/src/components/graph/NodeTooltip.tsx web/src/components/graph/Graph.tsx
git commit -m "feat(web): cluster legend + hover tooltip"
```

---

## Task 11: `Panel.tsx` + `CollapseHandle.tsx`

**Files:**
- Create: `web/src/components/panel/Panel.tsx`
- Create: `web/src/components/panel/CollapseHandle.tsx`

- [ ] **Step 1: Create `CollapseHandle.tsx`**

```tsx
import { useRunStore } from '../../state/runStore';

export default function CollapseHandle() {
  const collapsed = useRunStore((s) => s.panelCollapsed);
  const toggle = useRunStore((s) => s.toggleCollapse);
  return (
    <button
      onClick={toggle}
      aria-label={collapsed ? 'Paneel uitklappen' : 'Paneel inklappen'}
      style={{
        position: 'absolute',
        left: -32,
        top: '50%',
        transform: 'translateY(-50%)',
        width: 28,
        height: 48,
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRight: 'none',
        borderRadius: '8px 0 0 8px',
        color: 'var(--text-primary)',
        cursor: 'pointer',
        fontSize: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {collapsed ? '‹' : '›'}
    </button>
  );
}
```

- [ ] **Step 2: Create `Panel.tsx`** — container with collapse animation + phase router

```tsx
import { AnimatePresence, motion } from 'framer-motion';
import { useRunStore } from '../../state/runStore';
import { usePhase } from '../../hooks/usePhase';
import CollapseHandle from './CollapseHandle';
import IdlePhase from './phases/IdlePhase';
import RunningPhase from './phases/RunningPhase';
import AnswerReadyPhase from './phases/AnswerReadyPhase';
import InspectNodePhase from './phases/InspectNodePhase';

const PANEL_WIDTH = 440;
const COLLAPSE_OFFSET = PANEL_WIDTH + 48;

export default function Panel() {
  const phase = usePhase();
  const collapsed = useRunStore((s) => s.panelCollapsed);

  return (
    <motion.aside
      animate={{ x: collapsed ? COLLAPSE_OFFSET : 0 }}
      transition={{ type: 'spring', stiffness: 180, damping: 22 }}
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        bottom: 16,
        width: PANEL_WIDTH,
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
      <CollapseHandle />
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 20 }}>
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
    </motion.aside>
  );
}
```

**Note:** the phase components below are stubs for this task — they'll be filled in subsequent tasks. For now add placeholder files:

- [ ] **Step 3: Create placeholder phase files**

Create each of:
- `web/src/components/panel/phases/IdlePhase.tsx`
- `web/src/components/panel/phases/RunningPhase.tsx`
- `web/src/components/panel/phases/AnswerReadyPhase.tsx`
- `web/src/components/panel/phases/InspectNodePhase.tsx`

Each with:

```tsx
export default function _Phase() {
  return <div>TODO</div>;
}
```

Rename the default export per file (e.g., `IdlePhase`, `RunningPhase`, etc.).

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/panel/
git commit -m "feat(web): Panel shell + CollapseHandle + phase placeholders"
```

---

## Task 12: Panel common components — `PipelineProgress`, `AgentThinking`, `TraceLines`

**Files:**
- Create: `web/src/components/panel/PipelineProgress.tsx`
- Create: `web/src/components/panel/AgentThinking.tsx`
- Create: `web/src/components/panel/TraceLines.tsx`

- [ ] **Step 1: Create `PipelineProgress.tsx`**

```tsx
import { useRunStore } from '../../state/runStore';
import { color } from '../../theme';

const AGENTS = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;
const LABELS: Record<(typeof AGENTS)[number], string> = {
  decomposer: 'Ontleden',
  statute_retriever: 'Wet',
  case_retriever: 'Jurisprudentie',
  synthesizer: 'Antwoord',
  validator: 'Check',
};

type AgentStatus = 'pending' | 'active' | 'done';

export default function PipelineProgress() {
  const traceLog = useRunStore((s) => s.traceLog);

  const statusByAgent: Record<string, AgentStatus> = {};
  for (const agent of AGENTS) statusByAgent[agent] = 'pending';
  for (const ev of traceLog) {
    if (!ev.agent) continue;
    if (ev.type === 'agent_started') statusByAgent[ev.agent] = 'active';
    if (ev.type === 'agent_finished') statusByAgent[ev.agent] = 'done';
  }

  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
      {AGENTS.map((agent) => {
        const st = statusByAgent[agent];
        const bg =
          st === 'done' ? 'rgba(134, 207, 154, 0.25)' :
          st === 'active' ? 'rgba(245, 194, 74, 0.3)' :
          'rgba(255,255,255,0.04)';
        const border =
          st === 'done' ? 'rgba(134, 207, 154, 0.6)' :
          st === 'active' ? color.accent :
          'rgba(255,255,255,0.1)';
        const text =
          st === 'active' ? color.textPrimary : 'var(--text-secondary)';
        return (
          <div
            key={agent}
            style={{
              flex: 1,
              padding: '6px 4px',
              borderRadius: 6,
              background: bg,
              border: `1px solid ${border}`,
              fontSize: 10,
              textAlign: 'center',
              color: text,
            }}
          >
            {LABELS[agent]}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Create `AgentThinking.tsx`**

```tsx
interface Props {
  agent: string;
  text: string;
}

export default function AgentThinking({ agent, text }: Props) {
  if (!text) return null;
  return (
    <div
      style={{
        marginTop: 12,
        paddingLeft: 12,
        borderLeft: '2px solid var(--accent)',
        color: 'var(--text-secondary)',
        fontSize: 12,
        whiteSpace: 'pre-wrap',
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
        {agent} — gedachten
      </div>
      {text}
    </div>
  );
}
```

- [ ] **Step 3: Create `TraceLines.tsx`** (absorbs old `TracePanel`'s line formatting logic)

```tsx
import type { TraceEvent } from '../../types/events';

function eventLine(ev: TraceEvent): string | null {
  switch (ev.type) {
    case 'agent_started': return 'start';
    case 'agent_finished': return 'klaar';
    case 'tool_call_started':
      return `→ ${ev.data.tool}`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary ?? ''}`;
    case 'node_visited':
      return `bezocht ${ev.data.article_id}`;
    case 'edge_traversed':
      return null; // too noisy — graph shows these
    case 'search_started':
      return 'zoekt jurisprudentie';
    case 'case_found':
      return `gevonden ${ev.data.ecli} (sim=${Number(ev.data.similarity).toFixed(2)})`;
    case 'reranked':
      return `gekozen: ${(ev.data.kept as string[]).join(', ')}`;
    case 'citation_resolved':
      return `bron ${ev.data.kind} ${ev.data.id}`;
    case 'answer_delta':
      return null; // rendered as streaming prose elsewhere
    case 'agent_thinking':
      return null; // shown in AgentThinking
    default:
      return ev.type;
  }
}

export default function TraceLines({ events }: { events: TraceEvent[] }) {
  const lines = events.map(eventLine).filter((l) => l !== null);
  if (lines.length === 0) return null;
  return (
    <ul style={{
      listStyle: 'none',
      padding: 0,
      margin: '8px 0 0',
      fontFamily: 'ui-monospace, monospace',
      fontSize: 11,
      color: 'var(--text-tertiary)',
      lineHeight: 1.5,
    }}>
      {lines.map((l, i) => <li key={i}>{l}</li>)}
    </ul>
  );
}
```

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/panel/PipelineProgress.tsx web/src/components/panel/AgentThinking.tsx web/src/components/panel/TraceLines.tsx
git commit -m "feat(web): panel common components (progress, thinking, trace lines)"
```

---

## Task 13: `IdlePhase.tsx`

**Files:**
- Modify: `web/src/components/panel/phases/IdlePhase.tsx`

- [ ] **Step 1: Implement**

Replace the placeholder:

```tsx
import { useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import { ask } from '../../../api/ask';
import { subscribe } from '../../../api/sse';

const LOCKED_QUESTION = 'Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?';

export default function IdlePhase() {
  const [input, setInput] = useState(LOCKED_QUESTION);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = useRunStore((s) => s.start);
  const apply = useRunStore((s) => s.apply);

  const submit = async () => {
    const q = input.trim();
    if (!q) return;
    setSubmitting(true);
    setError(null);
    try {
      const { question_id } = await ask(q);
      start(question_id, q);
      subscribe(question_id, (ev) => apply(ev));
    } catch (e) {
      setError('Kon de vraag niet versturen. Probeer opnieuw.');
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4, color: 'var(--text-primary)' }}>
        Jurist
      </h2>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>
        Dutch huurrecht — multi-agent demo
      </p>

      <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        Je vraag
      </label>
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        disabled={submitting}
        rows={5}
        style={{
          display: 'block',
          width: '100%',
          marginTop: 6,
          padding: 12,
          fontSize: 14,
          fontFamily: 'inherit',
          color: 'var(--text-primary)',
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid var(--panel-border)',
          borderRadius: 8,
          resize: 'vertical',
        }}
      />

      {error && (
        <p style={{ color: 'var(--error)', fontSize: 12, marginTop: 8 }}>{error}</p>
      )}

      <button
        onClick={() => void submit()}
        disabled={submitting || input.trim().length === 0}
        style={{
          marginTop: 16,
          width: '100%',
          padding: '12px 16px',
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          cursor: submitting ? 'not-allowed' : 'pointer',
          opacity: submitting ? 0.6 : 1,
        }}
      >
        {submitting ? 'Bezig…' : 'Vraag stellen'}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/panel/phases/IdlePhase.tsx
git commit -m "feat(web): IdlePhase — dark question input"
```

---

## Task 14: `RunningPhase.tsx`

**Files:**
- Modify: `web/src/components/panel/phases/RunningPhase.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useRunStore } from '../../../state/runStore';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function RunningPhase() {
  const question = useRunStore((s) => s.question);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const answerText = useRunStore((s) => s.answerText);

  // Which agent is currently active (most recent agent_started without a matching agent_finished)?
  const active = (() => {
    const done = new Set<string>();
    let current: string | null = null;
    for (const ev of traceLog) {
      if (!ev.agent) continue;
      if (ev.type === 'agent_started') current = ev.agent;
      if (ev.type === 'agent_finished') {
        done.add(ev.agent);
        if (current === ev.agent) current = null;
      }
    }
    return current;
  })();

  const byAgent: Record<string, typeof traceLog> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

  return (
    <div>
      <div style={{
        fontSize: 12,
        color: 'var(--text-secondary)',
        padding: '6px 10px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 6,
        marginBottom: 16,
      }}>
        {question}
      </div>

      <PipelineProgress />

      {AGENT_ORDER.map((agent) => {
        if (!byAgent[agent]) return null;
        const isActive = active === agent;
        return (
          <div key={agent} style={{ marginBottom: isActive ? 16 : 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: isActive ? 'var(--accent)' : 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {agent}
            </div>
            {isActive && thinkingByAgent[agent] && (
              <AgentThinking agent={agent} text={thinkingByAgent[agent]} />
            )}
            <TraceLines events={byAgent[agent]} />
          </div>
        );
      })}

      {answerText && (
        <div style={{
          marginTop: 16,
          padding: 12,
          background: 'rgba(134, 207, 154, 0.08)',
          border: '1px solid rgba(134, 207, 154, 0.3)',
          borderRadius: 8,
          fontSize: 13,
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.5,
        }}>
          {answerText}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/panel/phases/RunningPhase.tsx
git commit -m "feat(web): RunningPhase — pipeline progress + live thinking + streaming answer"
```

---

## Task 15: `ErrorCard.tsx` + `AnswerReadyPhase.tsx`

**Files:**
- Create: `web/src/components/panel/phases/ErrorCard.tsx`
- Modify: `web/src/components/panel/phases/AnswerReadyPhase.tsx`

- [ ] **Step 1: Create `ErrorCard.tsx`**

```tsx
import { useRunStore } from '../../../state/runStore';

const REASON_COPY: Record<string, string> = {
  citation_grounding: 'De AI kon de citaten niet verifiëren. Probeer de vraag opnieuw.',
  decomposition: 'De vraag kon niet worden geanalyseerd. Probeer hem anders te formuleren.',
  case_rerank: 'Geen relevante jurisprudentie gevonden voor deze vraag.',
  rate_limit: 'Even rustig aan — probeer het over een minuut opnieuw.',
  llm_error: 'Er ging iets mis bij het AI-model. Probeer het opnieuw.',
  connection_lost: 'Verbinding verloren. Probeer het opnieuw.',
};

function copyFor(reason: string | undefined): string {
  if (!reason) return 'Er ging iets mis.';
  return REASON_COPY[reason] ?? 'Er ging iets mis.';
}

export default function ErrorCard() {
  const traceLog = useRunStore((s) => s.traceLog);
  const question = useRunStore((s) => s.question);
  const reset = useRunStore((s) => s.reset);

  // Find the run_failed event's reason.
  const failEv = [...traceLog].reverse().find((e) => e.type === 'run_failed');
  const reason = (failEv?.data?.reason as string | undefined);

  return (
    <div style={{
      padding: 16,
      background: 'rgba(240, 113, 120, 0.1)',
      border: '1px solid rgba(240, 113, 120, 0.3)',
      borderRadius: 10,
    }}>
      <div style={{ fontWeight: 600, color: 'var(--error)', marginBottom: 6 }}>
        Fout
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 12 }}>
        {copyFor(reason)}
      </p>
      <button
        onClick={() => {
          reset();
          // Re-populate with the same question for a quick retry — handled by IdlePhase's default.
          // (We just reset; the user clicks Ask again in idle.)
        }}
        style={{
          padding: '8px 14px',
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Opnieuw proberen
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Implement `AnswerReadyPhase.tsx`**

Replace the placeholder:

```tsx
import { useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import CitationLink from '../../CitationLink';
import { InsufficientContextBanner } from '../../InsufficientContextBanner';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';
import ErrorCard from './ErrorCard';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function AnswerReadyPhase() {
  const status = useRunStore((s) => s.status);
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const question = useRunStore((s) => s.question);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const reset = useRunStore((s) => s.reset);

  const [showReasoning, setShowReasoning] = useState(false);

  const byAgent: Record<string, typeof traceLog> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

  return (
    <div>
      <div style={{
        fontSize: 12,
        color: 'var(--text-secondary)',
        padding: '6px 10px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 6,
        marginBottom: 16,
      }}>
        {question}
      </div>

      {status === 'failed' ? (
        <ErrorCard />
      ) : !finalAnswer ? (
        <p style={{ color: 'var(--text-secondary)' }}>Geen antwoord ontvangen.</p>
      ) : finalAnswer.kind === 'insufficient_context' ? (
        <InsufficientContextBanner {...finalAnswer} />
      ) : (
        <>
          <Section title="Korte conclusie">
            <p style={{ fontSize: 15, lineHeight: 1.55 }}>{finalAnswer.korte_conclusie}</p>
          </Section>

          <Section title="Relevante wetsartikelen">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.relevante_wetsartikelen.map((c, i) => (
                <li key={`${c.bwb_id}-${i}`} style={{ marginBottom: 10, fontSize: 13, lineHeight: 1.55 }}>
                  <CitationLink kind="artikel" id={c.bwb_id}>
                    {c.article_label}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 2 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Vergelijkbare uitspraken">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.vergelijkbare_uitspraken.map((c, i) => (
                <li key={`${c.ecli}-${i}`} style={{ marginBottom: 10, fontSize: 13, lineHeight: 1.55 }}>
                  <CitationLink kind="uitspraak" id={c.ecli}>
                    {c.ecli}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 2 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Aanbeveling">
            <p style={{ fontSize: 13, lineHeight: 1.55 }}>{finalAnswer.aanbeveling}</p>
          </Section>
        </>
      )}

      {/* Collapsed reasoning disclosure */}
      {traceLog.length > 0 && (
        <div style={{ marginTop: 20, borderTop: '1px solid var(--panel-border)', paddingTop: 16 }}>
          <button
            onClick={() => setShowReasoning((v) => !v)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: 12,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            {showReasoning ? '▾ Verberg redenering' : '▸ Toon redenering'}
          </button>
          {showReasoning && (
            <div style={{ marginTop: 10 }}>
              <PipelineProgress />
              {AGENT_ORDER.map((agent) => {
                if (!byAgent[agent]) return null;
                return (
                  <div key={agent} style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      {agent}
                    </div>
                    {thinkingByAgent[agent] && <AgentThinking agent={agent} text={thinkingByAgent[agent]} />}
                    <TraceLines events={byAgent[agent]} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <button
        onClick={reset}
        style={{
          marginTop: 20,
          width: '100%',
          padding: '10px 14px',
          background: 'rgba(255,255,255,0.05)',
          color: 'var(--text-primary)',
          border: '1px solid var(--panel-border)',
          borderRadius: 8,
          fontSize: 13,
          cursor: 'pointer',
        }}
      >
        Nieuwe vraag
      </button>

      <p style={{ fontSize: 10, color: 'var(--text-tertiary)', textAlign: 'center', marginTop: 14 }}>
        Demo. Geen juridisch advies.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 18 }}>
      <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
        {title}
      </h3>
      {children}
    </section>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/panel/phases/AnswerReadyPhase.tsx web/src/components/panel/phases/ErrorCard.tsx
git commit -m "feat(web): AnswerReadyPhase — structured answer + Redenering disclosure + error sub-state"
```

---

## Task 16: `InspectNodePhase.tsx`

**Files:**
- Modify: `web/src/components/panel/phases/InspectNodePhase.tsx`

- [ ] **Step 1: Implement**

Replace the placeholder:

```tsx
import { useRunStore } from '../../../state/runStore';
import { useKgData } from '../../../hooks/useKgData';
import CitationLink from '../../CitationLink';
import { shortLabelFor } from '../../graph/clusters';

export default function InspectNodePhase() {
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const citedSet = useRunStore((s) => s.citedSet);
  const closeInspector = useRunStore((s) => s.closeInspector);
  const inspectNode = useRunStore((s) => s.inspectNode);
  const { data } = useKgData();

  if (!inspectedNode || !data) return null;
  const node = data.nodes.find((n) => n.article_id === inspectedNode);
  if (!node) {
    return (
      <div>
        <BackButton onBack={closeInspector} />
        <p style={{ color: 'var(--text-secondary)' }}>Artikel niet gevonden.</p>
      </div>
    );
  }

  const isCited = citedSet.has(node.article_id);

  return (
    <div>
      <BackButton onBack={closeInspector} />

      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{shortLabelFor(node)}</h3>
        <CitationLink kind="artikel" id={node.article_id}>
          Bron ↗
        </CitationLink>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
        {node.title}
      </div>

      {isCited && (
        <div style={{
          display: 'inline-block',
          marginTop: 10,
          padding: '3px 8px',
          background: 'rgba(134, 207, 154, 0.15)',
          border: '1px solid rgba(134, 207, 154, 0.4)',
          borderRadius: 12,
          fontSize: 11,
          color: '#86cf9a',
        }}>
          Geciteerd in dit antwoord
        </div>
      )}

      <div style={{
        marginTop: 16,
        fontSize: 13,
        lineHeight: 1.6,
        color: 'var(--text-primary)',
        whiteSpace: 'pre-wrap',
      }}>
        {node.body_text || '(geen tekst beschikbaar)'}
      </div>

      {node.outgoing_refs.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            Verwijst naar
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {node.outgoing_refs
              .filter((ref) => data.nodes.some((n) => n.article_id === ref))
              .map((ref) => {
                const target = data.nodes.find((n) => n.article_id === ref)!;
                return (
                  <button
                    key={ref}
                    onClick={() => inspectNode(ref)}
                    style={{
                      padding: '4px 10px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--panel-border)',
                      borderRadius: 12,
                      fontSize: 11,
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                    }}
                  >
                    {shortLabelFor(target)}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button
      onClick={onBack}
      style={{
        background: 'none',
        border: 'none',
        color: 'var(--text-secondary)',
        fontSize: 13,
        cursor: 'pointer',
        padding: 0,
      }}
    >
      ← Terug
    </button>
  );
}
```

- [ ] **Step 2: Wire Esc to close the inspector**

Modify `web/src/components/panel/Panel.tsx` — add a keyboard listener at the top of the component:

```tsx
import { useEffect } from 'react';
// ... existing imports
```

Inside the component:

```tsx
const inspectedNode = useRunStore((s) => s.inspectedNode);
const closeInspector = useRunStore((s) => s.closeInspector);

useEffect(() => {
  if (!inspectedNode) return;
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closeInspector();
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [inspectedNode, closeInspector]);
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/panel/phases/InspectNodePhase.tsx web/src/components/panel/Panel.tsx
git commit -m "feat(web): InspectNodePhase + Esc-to-close"
```

---

## Task 17: Restyle `CitationLink` + `InsufficientContextBanner` for dark theme

**Files:**
- Modify: `web/src/components/CitationLink.tsx`
- Modify: `web/src/components/InsufficientContextBanner.tsx`

- [ ] **Step 1: Replace `web/src/components/CitationLink.tsx`**

Full replacement — preserves the pending/resolved logic, swaps Tailwind light classes for dark inline styles:

```tsx
import { useRunStore } from '../state/runStore';

interface Props {
  kind: 'artikel' | 'uitspraak';
  id: string;
  children: React.ReactNode;
}

export default function CitationLink({ kind, id, children }: Props) {
  const resolved = useRunStore((s) => s.resolutions.find((r) => r.kind === kind && r.id === id));
  if (!resolved) {
    return (
      <span style={{
        color: 'var(--text-tertiary)',
        fontStyle: 'italic',
        opacity: 0.7,
      }}>
        {children}
      </span>
    );
  }
  return (
    <a
      href={resolved.resolved_url}
      target="_blank"
      rel="noreferrer"
      style={{
        color: 'var(--accent)',
        textDecoration: 'none',
        borderBottom: '1px dashed rgba(245, 194, 74, 0.4)',
      }}
    >
      {children}
    </a>
  );
}
```

- [ ] **Step 2: Replace `web/src/components/InsufficientContextBanner.tsx`**

Full replacement:

```tsx
import type { StructuredAnswer } from '../types/events';

type Props = Extract<StructuredAnswer, { kind: 'insufficient_context' }>;

export function InsufficientContextBanner(props: Props) {
  return (
    <div style={{
      padding: 16,
      background: 'rgba(245, 194, 74, 0.08)',
      border: '1px solid rgba(245, 194, 74, 0.3)',
      borderRadius: 10,
    }}>
      <h3 style={{
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--accent)',
        marginTop: 0,
        marginBottom: 8,
      }}>
        Geen voldoende bronnen voor deze vraag
      </h3>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: '0 0 8px' }}>
        {props.korte_conclusie}
      </p>
      <p style={{ fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic', margin: '0 0 10px' }}>
        {props.insufficient_context_reason}
      </p>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: 0 }}>
        {props.aanbeveling}
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/CitationLink.tsx web/src/components/InsufficientContextBanner.tsx
git commit -m "refactor(web): dark-theme restyle of CitationLink + InsufficientContextBanner"
```

---

## Task 18: Replace `App.tsx` + delete old components + drop old deps

This is the big integration commit. After this, the app uses only the new stack.

**Files:**
- Modify: `web/src/App.tsx`
- Delete: `web/src/components/KGPanel.tsx`
- Delete: `web/src/components/TracePanel.tsx`
- Delete: `web/src/components/AnswerPanel.tsx`
- Modify: `web/package.json` (drop old deps)

- [ ] **Step 1: Replace `web/src/App.tsx`**

```tsx
import Graph from './components/graph/Graph';
import Panel from './components/panel/Panel';
import ClusterLegend from './components/graph/ClusterLegend';

export default function App() {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'linear-gradient(to bottom, var(--bg-gradient-top), var(--bg-gradient-bot))',
      overflow: 'hidden',
    }}>
      <Graph />
      <ClusterLegend />
      <Panel />
    </div>
  );
}
```

- [ ] **Step 2: Delete the three old components**

Run:
```bash
rm web/src/components/KGPanel.tsx web/src/components/TracePanel.tsx web/src/components/AnswerPanel.tsx
```

- [ ] **Step 3: Remove old deps**

Run:
```bash
cd web && npm uninstall @xyflow/react dagre @types/dagre
```

Expected: deps removed from `package.json` and `package-lock.json`.

- [ ] **Step 4: Typecheck + run tests**

Run:
```bash
cd web && npx tsc --noEmit && npm run test
```

Expected: both clean. If `tsc` flags missing imports, check whether any file still references the deleted components or old libs — fix it.

- [ ] **Step 5: Build sanity check**

Run: `cd web && npm run build`
Expected: successful Vite build. Bundle size printed.

- [ ] **Step 6: Commit**

```bash
git add -A web/src/App.tsx web/src/components/ web/package.json web/package-lock.json
git commit -m "feat(web): wire new shell — full-viewport graph + docked panel, drop old panels"
```

---

## Task 19: SSE error → synthetic `run_failed{reason:"connection_lost"}`

**Files:**
- Modify: `web/src/api/sse.ts`

- [ ] **Step 1: Replace `web/src/api/sse.ts`**

Full replacement — tracks whether a terminal event was seen and synthesises `run_failed{connection_lost}` if the stream closes without one:

```ts
import type { TraceEvent } from '../types/events';

export interface Subscription {
  close: () => void;
}

export function subscribe(
  questionId: string,
  onEvent: (ev: TraceEvent) => void,
  onError?: (err: Event) => void,
): Subscription {
  let terminalSeen = false;
  let explicitlyClosed = false;

  const es = new EventSource(`/api/stream?question_id=${encodeURIComponent(questionId)}`);

  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as TraceEvent;
      if (ev.type === 'run_finished' || ev.type === 'run_failed') {
        terminalSeen = true;
      }
      onEvent(ev);
      if (terminalSeen) {
        explicitlyClosed = true;
        es.close();
      }
    } catch (e) {
      console.error('bad SSE payload', msg.data, e);
    }
  };

  es.onerror = (err) => {
    // If the stream died without a terminal event and we didn't close it ourselves,
    // synthesise a client-side run_failed{connection_lost}.
    if (!terminalSeen && !explicitlyClosed && es.readyState === EventSource.CLOSED) {
      onEvent({
        type: 'run_failed',
        agent: null,
        run_id: questionId,
        ts: new Date().toISOString(),
        data: { reason: 'connection_lost' },
      } as unknown as TraceEvent);
      terminalSeen = true;
    }
    if (onError) onError(err);
  };

  return {
    close: () => {
      explicitlyClosed = true;
      es.close();
    },
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/api/sse.ts
git commit -m "feat(web): synthesise run_failed{connection_lost} on SSE drop"
```

---

## Task 20: Manual smoke test

**Files:** none (verification only).

- [ ] **Step 1: Backend prep**

Confirm both ingest artefacts exist:
```bash
ls data/kg/huurrecht.json data/lancedb/cases.lance
```
Expected: both present. If either is missing, run:
```bash
uv run python -m jurist.ingest --refresh -v
uv run python -m jurist.ingest.caselaw -v
```

- [ ] **Step 2: Start the backend**

Run (in a separate terminal):
```bash
uv run python -m jurist.api
```
Expected: listens on `http://127.0.0.1:8766`, no startup errors.

- [ ] **Step 3: Start the frontend dev server**

Run:
```bash
cd web && npm run dev
```
Expected: Vite reports `http://localhost:5173`.

- [ ] **Step 4: Open the browser and verify each spec §8.3 checkpoint**

Open `http://localhost:5173` and tick each item:

- [ ] Idle state shows dark canvas + docked panel with the locked huur question pre-filled.
- [ ] Graph renders — organic force-directed layout, cluster colors visible, ~30 nodes have labels.
- [ ] Bottom-left legend lists all 7 clusters.
- [ ] Click *Vraag stellen*. Panel morphs to running state. Pipeline pills light up in order.
- [ ] Graph animates: current node pulses amber, edges sweep, visited nodes keep their stroke.
- [ ] Hover a node → tooltip shows its label + chapter title.
- [ ] Click the collapse handle. Panel slides right; graph now fills the viewport. Click again to expand.
- [ ] Answer streams into the bottom of the panel during running.
- [ ] On completion, panel transitions to `answer-ready`. Structured answer shows: Korte conclusie, Relevante wetsartikelen (with clickable CitationLinks), Vergelijkbare uitspraken, Aanbeveling.
- [ ] Exactly the articles listed in *Relevante wetsartikelen* are glowing `cited` on the graph (others are `visited` with subtle strokes).
- [ ] Click a glowing (cited) node. Panel switches to inspector showing article body + outgoing_refs chips. "Geciteerd in dit antwoord" badge appears.
- [ ] Click an outgoing-ref chip → inspector navigates to that article.
- [ ] Press Esc / click ← Terug → panel returns to the answer-ready view.
- [ ] *Toon redenering* disclosure expands to show the per-agent trace.
- [ ] Click *Nieuwe vraag* → returns to idle with the question pre-filled.

- [ ] **Step 5: Shut down, report**

Stop both servers. If any checkpoint failed, document the issue, fix it, and re-run this task (add a new task if the fix is substantial).

- [ ] **Step 6: Final commit (if any touch-up changes were made)**

```bash
git status
# If any files changed:
git add -A
git commit -m "fix(web): smoke-test fixes"
```

---

## Notes for the implementing engineer

- **Commit cadence.** Each numbered task ≈ one commit. Do not bundle across tasks; the repo convention (per CLAUDE.md) is "one task ≈ one commit."
- **TDD rule.** Tasks 3, 4, 5, 6 are strict TDD — write the failing test first, see it fail, then implement. Later UI tasks don't have automated tests; they rely on typecheck + the final manual smoke test (§8.3 of the spec).
- **Don't re-introduce the old panels.** If during Task 18 you see references to `KGPanel`, `TracePanel`, or `AnswerPanel`, find and remove them — those three files no longer exist.
- **`runStore` existing fields are sacred.** Do not rename, restructure, or remove any existing field in `runStore.ts`. Only ADD the three new fields.
- **Windows notes.** The repo is Windows + bash via Git Bash. `npm run test` works. LF→CRLF warnings on git commit are benign.
- **Port.** Backend is on 8766 (not 8000). Vite proxies `/api/*` to `127.0.0.1:8766` — don't change this without updating `vite.config.ts`.
- **No backend changes.** If you find yourself editing anything in `src/jurist/` or `data/`, stop — this plan is view-layer only.
