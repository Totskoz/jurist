# Frontend Redesign — Design

**Date:** 2026-04-22
**Status:** Draft. Awaiting user review.
**Parent spec:** `docs/superpowers/specs/2026-04-17-jurist-v1-design.md` (§7 UI / transport — event protocol unchanged)
**Branch:** `frontend-redesign` (proposed)

---

## 1. Context and goals

The frontend today is a functional but visually plain three-panel layout:
header input at the top, a left-hand knowledge-graph panel rendered by
`@xyflow/react` with a Dagre left-to-right rank layout, a right-hand trace
panel, and a bottom-section structured answer panel. It correctly visualises
the agent pipeline but does not look like a portfolio-grade demo.

This redesign reworks only the view layer. The backend event protocol, SSE
transport, agent contract, KG JSON shape, and `runStore` state shape are
untouched — every existing `TraceEvent` keeps its semantics. The goal is a
modern, single-screen, force-directed visualisation of the Dutch huurrecht
KG with the agent pipeline narrated in one consolidated floating panel.

**Done when:**

1. The previous three panels are replaced by a full-viewport force-directed
   graph plus a single right-docked, collapsible panel that morphs through
   phases (`idle → running → answer-ready → inspecting-node`).
2. Nodes are coloured by one of seven semantic clusters derived from the
   real `title` field, sized by edge degree, and labelled only for the top
   ~15% by degree.
3. Agent-walk events (`node_visited`, `edge_traversed`) animate the graph
   expressively (pulsing current node, amber edge sweeps), and the final
   `cited` glow lights up only the articles actually cited in
   `final_answer.relevante_wetsartikelen`.
4. The legend, inspector, collapse handle, error card, and all phase
   transitions ship behind no feature flag.
5. Dark theme only. No light/dark toggle.
6. Manual smoke test on the locked huur question on a fresh `npm run dev`
   server passes: run streams, graph animates, answer renders, inspect-a-node
   works, collapse works.

**Out of scope (v1):**

- Mobile layout below 900px viewport width.
- Screen-reader support for the canvas graph.
- Run cancellation, run persistence, prior-run history, replay controls.
- Any backend change. Any change to `TraceEvent` shape or agent semantics.
- A KG search bar. Users discover nodes by hover and click.

## 2. Principles

- **The KG is the stage, the panel is the narrator.** Never stack UI on top
  of the graph except the one docked panel, its collapse handle, and the
  fixed cluster legend.
- **Phase coherence.** The panel shows exactly one phase at a time. No two
  competing views.
- **The graph must read without the panel.** State transitions (current,
  visited, cited) communicate pipeline progress fully by themselves.
- **No fabrication.** Every label, cluster, and edge in the graph comes from
  real KG data. No synthetic nodes or fake edges.
- **Existing `runStore` state shape stays.** We add three UI fields
  (`inspectedNode`, `panelCollapsed`, `citedSet`). No field is renamed.

## 3. Visual system

### 3.1 Palette

Defined once as CSS custom properties in `web/src/index.css`; mirrored in
`web/src/theme.ts` for canvas drawing.

| Role | Value |
|---|---|
| Background | Linear gradient `#0a0b0f → #14161c` (vertical) |
| Panel surface | `rgba(20, 22, 28, 0.72)` + `backdrop-filter: blur(20px)` + 1px border `rgba(255,255,255,0.08)` |
| Text primary | `#e7eaf0` |
| Text secondary | `#9098a8` |
| Text tertiary | `#5d6370` |
| Accent (current node, Ask button, error retry) | `#f5c24a` |
| Error | `#f07178` |
| Edge default | `rgba(255,255,255,0.08)` |

### 3.2 Cluster palette

Seven semantic super-clusters derived from the KG's `title` field plus two
obvious semantic merges, with one "Overig" bucket for the long tail. The
mapping is a static lookup table in `web/src/components/graph/clusters.ts`.

| Cluster | Colour | Source `title` values | Approx node count |
|---|---|---|---|
| Verplichtingen onder huur | `#7fa3e0` muted blue | *De verplichtingen van de huurder* + *Verplichtingen van de verhuurder* | 23 |
| Algemeen | `#7bcdc4` muted teal | *Algemeen* | 22 |
| Huur van bedrijfsruimte | `#dece7b` muted yellow | *Huur van bedrijfsruimte* | 21 |
| Huurcommissie & procedure | `#b397db` muted purple | *Instelling... huurcommissie* + *De uitspraak en verdere bepalingen* + any `BWBR0014315` title not absorbed elsewhere | ~30 |
| Eindigen van de huur | `#e48fa8` muted pink | *Het eindigen van de huur* | 19 |
| Huurprijzen | `#86cf9a` muted green | *Huurprijzen* | 18 |
| Overig | `#6b7280` slate | everything else, incl. *Overgangs- en slotbepalingen* | ~96 |

A property test covers every node in `data/kg/huurrecht.json` — each one
must land in exactly one bucket, and no bucket can be empty unexpectedly.

### 3.3 Node visual states

The cluster colour is the node's **identity**; the run state is a
**modulation** on top, never a colour swap.

| State | Rendering |
|---|---|
| `default` | Cluster colour at 55% alpha, no stroke |
| `current` | Cluster colour at full alpha + 2px amber stroke + pulsing amber halo (2× radius, opacity 0.4 → 0 at 1.5 Hz) |
| `visited` | Cluster colour at full alpha + 1px same-cluster stroke (static) |
| `cited` | Cluster colour at full alpha + persistent same-cluster soft glow (1.8× radius, 0.35 opacity) |

Node radius: `r = 4 + 1.8 × √degree`. Degree-0 → 4px, degree-16 → ~11.2px.

Labels: rendered only when node degree is in the top ~15% (~30 nodes).
Label format uses Dutch legal shorthand — `BWBR0005290/...Artikel247` →
"7:247", `BWBR0014315/...Artikel10` → "Uhw 10". Font: 10px tabular sans,
`#e7eaf0`, with a 2px dark text-stroke so it reads against edges.

### 3.4 Edge visual states

| State | Rendering |
|---|---|
| `default` | 1px hairline, `rgba(255,255,255,0.08)` |
| Transition → `traversed` | 200ms amber sweep from source → target |
| `traversed` (post-sweep) | 1.5px stroke, target-cluster-colour at 40% alpha |

Edge sweep animations queue and play at most one per 80ms to prevent
strobing during bursts.

### 3.5 Typography

Keep the existing Tailwind system-font stack:
`ui-sans-serif, system-ui, sans-serif`. Dense trace lines keep `font-mono`.
No custom web font.

### 3.6 Fixed cluster legend

A small card anchored to the viewport's bottom-left (16px margin). Each
cluster is a 10×10 colour swatch plus the cluster name. Non-interactive.
The legend is the only on-canvas chrome besides the panel and its handle.

## 4. Layout and phase state machine

### 4.1 Layout

- Full-viewport dark gradient. Graph canvas fills the window.
- Right-docked panel: 440px wide, full height, 16px margin from viewport
  edges (floats, not flush).
- Collapse handle: anchored to the panel's left edge at vertical-centre.
- Fixed cluster legend: bottom-left, 16px margin.
- Minimum supported viewport: 1280 × 720. Below 900px width, the graph is
  hidden and the panel becomes full-width (degraded single-column view).

### 4.2 Phase state machine

The panel is always in exactly one phase, derived from `runStore.status` +
`runStore.inspectedNode`.

```
            ┌─────────────────┐
    ┌──────▶│      idle       │──── ask ───┐
    │       └─────────────────┘            │
    │                ▲                     ▼
    │                │              ┌─────────────┐
    │           "nieuwe vraag"      │   running   │
    │                │              └─────────────┘
    │                │                     │
    │                │           run_finished / run_failed
    │                │                     │
    │                │                     ▼
    │       ┌─────────────────┐
    │       │   answer-ready  │  (includes error sub-state when status=failed)
    │       └─────────────────┘
    │                ▲
    │  node click   │
    │                │ close (← / Esc)
    │                ▼
    │       ┌─────────────────┐
    └───────│ inspecting-node │
            └─────────────────┘
```

`inspecting-node` is a stack overlay over any other phase. When it opens,
the previous phase is pushed; the back arrow pops back to exactly where the
user came from. A `run_finished` arriving while the inspector is open
updates the underlying phase silently — user focus wins; they see the new
state when they close.

### 4.3 Per-phase content

| Phase | Panel content |
|---|---|
| `idle` | Large question textarea (prominent, centred) with the locked question pre-filled. *Ask* button below. Nothing else. |
| `running` | Read-only question chip at top. Horizontal 5-step pipeline progress (decomposer → statute → case → synth → validator) with current step highlighted. Below: current agent's live `agent_thinking` stream + compact trace lines. When `answer_delta` tokens start arriving, streaming answer prose appears at the bottom of the panel (same slot the final answer will occupy). |
| `answer-ready` | Question chip. Structured answer: *Korte conclusie* (larger), *Relevante wetsartikelen*, *Vergelijkbare uitspraken*, *Aanbeveling*. Collapsed *Redenering* disclosure expands to show per-agent trace. *Nieuwe vraag* button. "Demo. Geen juridisch advies." footer line. |
| `inspecting-node` | Header: ← back + article short label + external-link chip (`CitationLink` logic). Body: `title`, full `body_text`, `outgoing_refs` as clickable chips (clicking replaces the inspected node, inspector stays open). If the article is in `citedSet`, a "Geciteerd in dit antwoord" badge appears. |
| error sub-state (inside `answer-ready`) | Question chip + error card driven by `run_failed.reason`. *Opnieuw proberen* button. |

`InsufficientContextBanner` renders inside `answer-ready` in place of the
structured sections when `final_answer.kind === "insufficient_context"`.

### 4.4 Transitions

- Phase cross-fades use Framer Motion spring transitions (~240ms, low
  stiffness). Fade + 12px vertical slide.
- Inspector slides in from the right; the underlying phase stays mounted
  (pushed slightly left) so return is instant.
- Collapse handle toggles a single `x` translate on the panel (no content
  re-render).

## 5. Event → visual mapping

### 5.1 Events that change the graph

| Event | Graph effect |
|---|---|
| `run_started` | Reset all node/edge state to `default`. Clear `inspectedNode`. |
| `node_visited` | Demote previous `current` → `visited`. Set this `article_id` → `current`. No camera pan. |
| `edge_traversed` | Queue a 200ms amber sweep source → target; on completion, set edge to `traversed`. Queue throttles to one per 80ms. |
| `run_finished` | Populate `citedSet` from `final_answer.relevante_wetsartikelen[].bwb_id` (these are full article_ids in our schema). Only those nodes flip to `cited`. Other `visited` nodes keep their `visited` styling. |
| `run_failed` | No new visual change. Visited trails remain so the viewer can see how far the pipeline got. |

### 5.2 Events that only change the panel

| Event | Panel effect |
|---|---|
| `agent_started` | Pipeline pill for that agent lights up. Fresh `thinking` buffer started. |
| `agent_thinking` | Append delta to that agent's live buffer. Only the currently-running agent's block is visible in `running` phase. |
| `tool_call_started` / `tool_call_completed` | Compact `font-mono` line in current agent's trace. |
| `search_started` | Case-retriever pill shows spinner + "Zoeken in jurisprudentie". |
| `case_found` | Line "ECLI:... — sim 0.72" in case-retriever trace. |
| `reranked` | Line "gekozen: ECLI1, ECLI2, ECLI3". |
| `answer_delta` | Append to `answerText`. Displayed in panel's bottom section during `running`. |
| `citation_resolved` | Register in `resolutions` map. Matching `CitationLink` becomes clickable. |
| `agent_finished` | Collapse live thinking for that agent. Pill flips to "✓ done". |
| `run_finished` | Phase transitions `running → answer-ready`. `finalAnswer` stored. |
| `run_failed` | Phase transitions `running → answer-ready` error sub-state. `reason` drives copy. |

### 5.3 User actions (not from SSE)

| Action | Effect |
|---|---|
| Click a graph node | `inspectedNode = article_id`. Panel opens inspector. Node gets 1.5px white stroke. |
| Click back arrow / press Esc in inspector | Clear `inspectedNode`. Panel pops to previous phase. |
| Click `outgoing_refs` chip in inspector | Replace `inspectedNode` with target. |
| Click `CitationLink` in answer | Open resolved URL in new tab. |
| Click collapse handle | Toggle `panelCollapsed`. Panel slides ±400px on x axis. |
| Drag / pinch-zoom / wheel on canvas | Pan / zoom (lib built-ins). |
| Hover a node | Floating tooltip: `label + title`. |

## 6. Component structure

### 6.1 Existing files edited

| File | Change |
|---|---|
| `web/src/App.tsx` | Gutted — thin shell rendering `<Graph>` + `<Panel>` + `<ClusterLegend>` inside a full-viewport dark container. |
| `web/src/components/KGPanel.tsx` | **Deleted.** Replaced by `components/graph/Graph.tsx`. |
| `web/src/components/TracePanel.tsx` | **Deleted.** Absorbed into `panel/phases/RunningPhase.tsx` + the `Redenering` disclosure in `AnswerReadyPhase`. |
| `web/src/components/AnswerPanel.tsx` | **Deleted.** Absorbed into `panel/phases/AnswerReadyPhase.tsx`. |
| `web/src/components/InsufficientContextBanner.tsx` | Restyled for dark theme. Logic unchanged. |
| `web/src/components/CitationLink.tsx` | Restyled for dark theme. Logic unchanged. |
| `web/src/state/runStore.ts` | Add `inspectedNode: string \| null`, `panelCollapsed: boolean`, `citedSet: Set<string>`. Add reducer cases `UI_INSPECT_NODE`, `UI_CLOSE_INSPECTOR`, `UI_TOGGLE_COLLAPSE`. Edit `run_finished` to populate `citedSet` from the final answer and only promote those nodes to `cited`. |
| `web/src/index.css` | Replace body styles with dark root + CSS custom properties for every palette value. |
| `web/package.json` | Remove `@xyflow/react`, `dagre`, `@types/dagre`. Add `react-force-graph-2d`, `framer-motion`. |

### 6.2 New files

```
web/src/
  theme.ts                              palette constants mirrored from CSS vars
  hooks/
    useKgData.ts                        fetch /api/kg once, memoize clustered result
    usePhase.ts                         derive panel phase from runStore
  components/
    graph/
      Graph.tsx                         full-viewport react-force-graph-2d wrapper
      clusters.ts                       clusterOf(node) + colour lookup + label-short form
      nodeRender.ts                     canvas draw fns: circle, halo, pulse, label
      edgeRender.ts                     canvas draw fns: hairline, sweep, traversed tint
      forceConfig.ts                    force-simulation tuning
      ClusterLegend.tsx                 bottom-left legend
      NodeTooltip.tsx                   hover tooltip
    panel/
      Panel.tsx                         right-docked container; phase switch + collapse anim
      CollapseHandle.tsx                edge chevron
      PipelineProgress.tsx              5-step agent pill row
      AgentThinking.tsx                 single agent's live thinking block
      TraceLines.tsx                    compact list of non-thinking trace events
      phases/
        IdlePhase.tsx
        RunningPhase.tsx
        AnswerReadyPhase.tsx
        InspectNodePhase.tsx
        ErrorCard.tsx
```

### 6.3 Data flow

1. `App.tsx` mounts once. Triggers `useKgData()` fetch; renders shell.
2. `Graph.tsx` subscribes to `runStore` slices (`kgState`, `edgeState`,
   `citedSet`, `inspectedNode`) via granular selectors. Drives the canvas
   imperatively through `react-force-graph-2d`'s `nodeCanvasObject` and
   `linkCanvasObject` hooks, calling pure functions from `nodeRender.ts` /
   `edgeRender.ts`.
3. `Panel.tsx` calls `usePhase()` to pick a phase component; wraps in
   `AnimatePresence mode="wait"`.
4. Each phase component subscribes only to the `runStore` slice it needs.
5. UI state changes flow through small action creators: `inspectNode`,
   `closeInspector`, `toggleCollapse`, `askQuestion`, `resetRun`. No direct
   `set()` calls from components.

### 6.4 Dependencies

| Lib | Role | Net size (gzip) |
|---|---|---|
| `react-force-graph-2d` | Canvas force graph + pan/zoom/drag/hover | +50 KB |
| `framer-motion` | Phase transitions, collapse, pulse | +35 KB |
| `@xyflow/react` | (removed) | −40 KB |
| `dagre` | (removed) | −5 KB |

Net bundle impact: ~+40 KB gzip. Acceptable for a local demo.

## 7. Error handling

### 7.1 Startup failures

| Scenario | Behavior |
|---|---|
| `GET /api/kg` fails or returns empty | Full-viewport dark error card: "Kon de kennisgraaf niet laden." + "Opnieuw proberen" retry button. Panel hidden until load. |
| KG node has an unknown `title` | Falls through to "Overig" slate. No crash. Dev-only `console.warn` lists unmapped titles. |
| Force simulation doesn't settle | `react-force-graph-2d` `cooldownTicks` capped at 150. |

### 7.2 Run failures (backend `run_failed`)

`ErrorCard` inside `AnswerReadyPhase` maps `reason` to Dutch copy:

| `reason` | Copy |
|---|---|
| `citation_grounding` | "De AI kon de citaten niet verifiëren. Probeer de vraag opnieuw." |
| `decomposition` | "De vraag kon niet worden geanalyseerd. Probeer hem anders te formuleren." |
| `case_rerank` | "Geen relevante jurisprudentie gevonden voor deze vraag." |
| `rate_limit` | "Even rustig aan — probeer het over een minuut opnieuw." |
| `llm_error` | "Er ging iets mis bij het AI-model. Probeer het opnieuw." |
| `connection_lost` (client-synthesised) | "Verbinding verloren. Probeer het opnieuw." |
| any other / missing | Generic "Er ging iets mis." |

Retry button: `resetRun()` + `askQuestion(question)`. No new backend
contract.

### 7.3 Network / SSE failures

| Scenario | Behavior |
|---|---|
| `POST /api/ask` rejects | Inline error under textarea in `IdlePhase`. Ask button stays enabled. Question persists. |
| SSE connection drops mid-run | `subscribe()` wrapper catches → dispatches synthetic `run_failed{reason:"connection_lost"}`. This reason exists only client-side (never emitted by the backend) and has its own row in the `ErrorCard` copy table (§7.2). |
| SSE never emits a terminal event | No client-side timeout in v1. Documented gap. User refreshes. |

### 7.4 User-driven edge cases

| Scenario | Behavior |
|---|---|
| *Nieuwe vraag* mid-run | Not possible (button only in `answer-ready`). |
| Esc while not inspecting | No-op. |
| `outgoing_refs` chip target not in KG | Filtered by `useKgData` at load time; cannot happen. |
| Inspector open when `run_finished` arrives | Panel stays on inspector. Back arrow returns to updated `answer-ready`. |
| Panel collapsed when `run_failed` arrives | Panel stays collapsed. Graph visible. |
| `citedSet` contains id not in KG | Silently skipped. Dev log. |

## 8. Testing

Per project CLAUDE.md convention (TDD + one task ≈ one commit). Only pure
logic is unit-tested. Canvas drawing and motion transitions are manually
verified.

### 8.1 Unit-tested (Vitest)

- `clusters.ts::clusterOf(node)` — lookup table correctness. Property test:
  every node in `data/kg/huurrecht.json` maps to exactly one cluster key.
  Every expected cluster key is non-empty.
- `clusters.ts::shortLabelFor(node)` — "BWBR0005290/Boek7/.../Artikel247"
  → "7:247"; Uhw variants → "Uhw 10". Edge cases (missing segments).
- `usePhase.ts` — pure function `(status, inspectedNode) → PhaseKey`.
  Exhaustive table.
- `runStore` — edited `run_finished` reducer: given a final answer with 3
  cited bwb_ids, only those 3 nodes end up in `citedSet`. Non-cited
  `visited` nodes remain `visited`.
- `runStore` — `UI_INSPECT_NODE`, `UI_CLOSE_INSPECTOR`, `UI_TOGGLE_COLLAPSE`
  reducer cases.
- `nodeRender.ts::radiusFromDegree(d)` — math.
- `nodeRender.ts::shouldShowLabel(degreeRank, totalNodes)` — rank-based
  threshold logic.

### 8.2 Not tested automatically

- Canvas drawing output (no image-diff infrastructure).
- Framer Motion transitions.
- Force simulation layout stability (stochastic).
- End-to-end graph interaction (no Playwright in scope).

### 8.3 Manual verification gate

Before declaring the redesign done, run `npm run dev` + the backend (with
KG and `cases.lance` present) and verify on the locked huur question:

1. Idle state shows the dark canvas + panel with question pre-filled.
2. Clicking *Ask* transitions the panel to `running`.
3. Graph: watch the retriever's path — current node pulses amber, edges
   sweep, visited nodes keep soft strokes.
4. Answer streams in the bottom of the panel, then settles into the
   structured `answer-ready` view on `run_finished`.
5. Cited articles glow in their cluster colour (exactly those listed in
   *Relevante wetsartikelen*).
6. Clicking a glowing node opens the inspector showing the article body.
7. `outgoing_refs` chips navigate between articles.
8. ← back returns to `answer-ready`.
9. Collapse handle hides the panel; graph fills the full viewport. Expand
   returns.
10. *Nieuwe vraag* returns to `idle` with the question pre-filled.

## 9. Open questions / deferred decisions

- **Node-label short form for Uhw variants.** Current proposal: "Uhw 10",
  "Uhw 4a". If the lookup table pattern ("BWBR0014315/..." → "Uhw ...") is
  awkward in data, fall back to using `node.label` verbatim.
- **Cluster mega-labels.** Not in v1 (decided during brainstorming). If
  post-demo feedback wants them, they'd be cluster-centroid overlays drawn
  after layout settles — no synthetic graph structure.
- **Search bar** for large graphs — not in v1. Could become a `Cmd+K` popover
  later without structural changes.

## 10. Non-goals (v1)

- No backend changes of any kind.
- No change to the event protocol or any `TraceEvent` shape.
- No mobile layout below 900px.
- No run cancellation, run history, replay, or persistence.
- No screen-reader support for the canvas graph (panel DOM remains a11y-ok).
- No analytics, telemetry, or auth.
