# Jurist v1 — M1 Implementation Plan (Statute ingestion + KG viewer)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/api/kg` fake with a real huurrecht KG built from BWB XML via a new `python -m jurist.ingest.statutes` CLI; load the KG at FastAPI startup and render real nodes in the existing KGPanel.

**Architecture:** A new `src/jurist/ingest/` package fetches BWB XML (cached locally, live-fetch on miss), parses articles with `lxml` using a schema-conformant ancestor-chain walk, extracts cross-references from explicit `<intref>`/`<extref>` elements (preferred) and a same-BWB regex fallback, and writes `data/kg/huurrecht.json` + per-article markdown dumps. A new `src/jurist/kg/` package exposes a minimal `KnowledgeGraph` Protocol backed by NetworkX; `src/jurist/api/app.py` loads the KG at startup via `lifespan` and hard-fails on missing file. `fakes.py` stays intact — the fake agents still drive the run; only the KG source changes.

**Tech Stack:** Python 3.11+, uv, FastAPI (lifespan), Pydantic 2, `lxml`, `httpx`, `networkx`, pytest, pytest-asyncio. Frontend: Vite + React + TypeScript (KGPanel tweaks only — no new components).

**Scope note:** This plan covers **M1 only** per the design spec. M1 ships the 3 core BWBs (BW7 Titel 4, Uhw, Besluit huurprijzen). The widened ~8-BWB corpus is deferred to **M1.5**, which requires no parser code changes.

**Authoritative design:** `docs/superpowers/specs/2026-04-20-jurist-m1-design.md` (parent: `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`).

---

## File structure

### Backend (new)

| Path | Responsibility |
| --- | --- |
| `src/jurist/kg/__init__.py` | Package marker. |
| `src/jurist/kg/interface.py` | `KnowledgeGraph` Protocol. |
| `src/jurist/kg/networkx_kg.py` | `NetworkXKG` concrete impl + `load_from_json` classmethod. |
| `src/jurist/ingest/__init__.py` | Package marker. |
| `src/jurist/ingest/allowlist.py` | `BWB_ALLOWLIST` — single scope knob. |
| `src/jurist/ingest/fetch.py` | `fetch_bwb_xml(bwb_id)` — cache + live `httpx.Client` fetch. |
| `src/jurist/ingest/parser.py` | `parse_bwb_xml(xml_bytes, bwb_id, entry)` → `(list[ArticleNode], list[ArticleEdge])`. |
| `src/jurist/ingest/xrefs.py` | Regex pass + dedup merge of explicit + regex edges. |
| `src/jurist/ingest/statutes.py` | Orchestrator: per BWB, fetch → parse → xrefs → dedup; write JSON + markdown dumps; idempotency via `source_versions`. |
| `src/jurist/ingest/__main__.py` | `python -m jurist.ingest.statutes` CLI with argparse. |

### Backend (modified)

| Path | Change |
| --- | --- |
| `src/jurist/schemas.py` | Add `KGSnapshot` Pydantic model. |
| `src/jurist/config.py` | Add `kg_path` property. |
| `src/jurist/api/app.py` | Remove `FAKE_KG` import; add `lifespan` that loads KG; `/api/kg` reads `app.state.kg`. |
| `pyproject.toml` | Add runtime deps `lxml`, `httpx`, `networkx`. |

### Frontend (modified)

| Path | Change |
| --- | --- |
| `web/src/components/KGPanel.tsx` | Dagre `nodesep:40 ranksep:90`; native `title` tooltip; BWB border tint (default-state only); inline 3-entry legend. |

### Tests (new)

| Path | Responsibility |
| --- | --- |
| `tests/ingest/__init__.py` | Package marker. |
| `tests/ingest/fixtures/BWBR0005290_excerpt.xml` | Real BW7 XML excerpt (Titel 4, incl. art. 246-265). |
| `tests/ingest/fixtures/BWBR0002888_excerpt.xml` | Real Uhw excerpt (incl. art. 6 + 10). |
| `tests/ingest/fixtures/BWBR0003402_excerpt.xml` | Real Besluit excerpt (a few articles). |
| `tests/ingest/test_parser.py` | Parser behavior — inline mini-XML + fixture-based `test_parses_art_7_248_bw`. |
| `tests/ingest/test_xrefs.py` | Regex pass + dedup merge, table-driven. |
| `tests/ingest/test_idempotency.py` | `source_versions` short-circuit; `--refresh` bypass. |
| `tests/kg/__init__.py` | Package marker. |
| `tests/kg/test_networkx_kg.py` | JSON roundtrip; `get_node`; dup detection. |
| `tests/api/test_kg_endpoint.py` | `/api/kg` shape with tmp-dir KG; hard-fail on missing file. |
| `tests/integration/__init__.py` | Package marker. |
| `tests/integration/test_ingest_end_to_end.py` | Full pipeline on 3 fixture XMLs. |
| `tests/integration/test_fake_paths_in_real_kg.py` | Drift catch — `FAKE_VISIT_PATH ⊂ parsed_nodes`. |

---

## Tasks

### Task 1: Add runtime dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime deps to `[project].dependencies`**

Open `pyproject.toml` and extend the `dependencies` array to include `lxml>=5.3`, `httpx>=0.27`, `networkx>=3.3`. `httpx` may already be under `[project.optional-dependencies].dev` — if so, leave the dev entry but also add to runtime. Example runtime list after edit:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
    "sse-starlette>=2.1",
    "lxml>=5.3",
    "httpx>=0.27",
    "networkx>=3.3",
]
```

- [ ] **Step 2: Sync environment**

Run: `uv sync --extra dev`
Expected: no errors; new packages installed. On Windows, `lxml` wheels install cleanly for Python 3.11 — if a build fails, the user is on an unsupported Python version.

- [ ] **Step 3: Smoke-import the new modules**

Run: `uv run python -c "import lxml.etree, httpx, networkx; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add lxml, httpx, networkx runtime deps for M1 ingest"
```

---

### Task 2: Add `kg_path` to config

**Files:**
- Modify: `src/jurist/config.py`
- Test: `tests/test_schemas.py` (or a new `tests/test_config.py` if the existing tests file is schema-only)

- [ ] **Step 1: Inspect current `config.py`**

Run: `sed -n '1,80p' src/jurist/config.py` (or read in editor). Note how `data_dir` and other paths are derived; match the style.

- [ ] **Step 2: Add `kg_path` property**

In `src/jurist/config.py`, add a property (if `Settings` is a Pydantic model) or computed attribute on the settings class:

```python
@property
def kg_path(self) -> Path:
    return self.data_dir / "kg" / "huurrecht.json"
```

If `Settings` is a dataclass instead, add an equivalent method. If `data_dir` isn't already defined, define it first as `Path(os.environ.get("JURIST_DATA_DIR", "./data"))`.

- [ ] **Step 3: Write a test**

Create or extend `tests/test_config.py`:

```python
from pathlib import Path
from jurist.config import settings

def test_kg_path_defaults_under_data_dir():
    assert settings.kg_path.parts[-2:] == ("kg", "huurrecht.json")
    assert isinstance(settings.kg_path, Path)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/config.py tests/test_config.py
git commit -m "feat: config.kg_path — points at data/kg/huurrecht.json"
```

---

### Task 3: Add `KGSnapshot` Pydantic model

**Files:**
- Modify: `src/jurist/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_schemas.py`:

```python
import json
from jurist.schemas import KGSnapshot, ArticleNode, ArticleEdge

def test_kg_snapshot_roundtrip():
    snap = KGSnapshot(
        generated_at="2026-04-20T10:00:00Z",
        source_versions={"BWBR0005290": "2024-01-01"},
        nodes=[
            ArticleNode(
                article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                bwb_id="BWBR0005290",
                label="Boek 7, Artikel 248",
                title="Huurverhoging",
                body_text="De verhuurder kan ...",
                outgoing_refs=["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"],
            )
        ],
        edges=[
            ArticleEdge(
                from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                to_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                kind="explicit",
                context=None,
            )
        ],
    )
    payload = snap.model_dump_json()
    restored = KGSnapshot.model_validate_json(payload)
    assert restored == snap

def test_kg_snapshot_rejects_missing_fields():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        KGSnapshot.model_validate({"nodes": [], "edges": []})  # missing required fields
```

- [ ] **Step 2: Run and see it fail**

Run: `uv run pytest tests/test_schemas.py::test_kg_snapshot_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'KGSnapshot'`.

- [ ] **Step 3: Implement `KGSnapshot`**

Append to `src/jurist/schemas.py`:

```python
# ---------------- KG snapshot (M1) ----------------

class KGSnapshot(BaseModel):
    generated_at: str
    source_versions: dict[str, str]
    nodes: list[ArticleNode]
    edges: list[ArticleEdge]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: PASS for both new tests; previously existing tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/schemas.py tests/test_schemas.py
git commit -m "feat: schemas.KGSnapshot — KG JSON file shape"
```

---

### Task 4: `KnowledgeGraph` Protocol

**Files:**
- Create: `src/jurist/kg/__init__.py`
- Create: `src/jurist/kg/interface.py`

- [ ] **Step 1: Create package marker**

Create `src/jurist/kg/__init__.py` (empty file).

- [ ] **Step 2: Write the Protocol**

Create `src/jurist/kg/interface.py`:

```python
"""Minimal KnowledgeGraph Protocol — widened in M2 as tool impls need it."""
from __future__ import annotations

from typing import Protocol

from jurist.schemas import ArticleEdge, ArticleNode


class KnowledgeGraph(Protocol):
    def all_nodes(self) -> list[ArticleNode]: ...
    def all_edges(self) -> list[ArticleEdge]: ...
    def get_node(self, article_id: str) -> ArticleNode | None: ...
```

- [ ] **Step 3: Smoke test the import**

Run: `uv run python -c "from jurist.kg.interface import KnowledgeGraph; print(KnowledgeGraph)"`
Expected: prints a typing.Protocol-ish repr; no errors.

- [ ] **Step 4: Commit**

```bash
git add src/jurist/kg/__init__.py src/jurist/kg/interface.py
git commit -m "feat: kg.interface — KnowledgeGraph Protocol (minimal for M1)"
```

---

### Task 5: `NetworkXKG` implementation

**Files:**
- Create: `src/jurist/kg/networkx_kg.py`
- Create: `tests/kg/__init__.py`
- Create: `tests/kg/test_networkx_kg.py`

- [ ] **Step 1: Create test package marker**

Create `tests/kg/__init__.py` (empty).

- [ ] **Step 2: Write failing tests**

Create `tests/kg/test_networkx_kg.py`:

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jurist.kg.networkx_kg import NetworkXKG


def _sample_snapshot_json() -> str:
    return json.dumps({
        "generated_at": "2026-04-20T10:00:00Z",
        "source_versions": {"BWBR0005290": "2024-01-01"},
        "nodes": [
            {
                "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "bwb_id": "BWBR0005290",
                "label": "Boek 7, Artikel 248",
                "title": "Huurverhoging",
                "body_text": "De verhuurder kan ...",
                "outgoing_refs": ["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"],
            },
            {
                "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                "bwb_id": "BWBR0005290",
                "label": "Boek 7, Artikel 249",
                "title": "Voorstel",
                "body_text": "Een voorstel tot huurverhoging ...",
                "outgoing_refs": [],
            },
        ],
        "edges": [
            {
                "from_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "to_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                "kind": "explicit",
                "context": None,
            }
        ],
    })


def test_load_from_json_roundtrip(tmp_path: Path):
    path = tmp_path / "kg.json"
    path.write_text(_sample_snapshot_json(), encoding="utf-8")
    kg = NetworkXKG.load_from_json(path)
    assert len(kg.all_nodes()) == 2
    assert len(kg.all_edges()) == 1


def test_get_node_known_and_unknown(tmp_path: Path):
    path = tmp_path / "kg.json"
    path.write_text(_sample_snapshot_json(), encoding="utf-8")
    kg = NetworkXKG.load_from_json(path)
    node = kg.get_node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248")
    assert node is not None
    assert node.label == "Boek 7, Artikel 248"
    assert kg.get_node("does/not/exist") is None


def test_missing_file_raises_filenotfound(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        NetworkXKG.load_from_json(tmp_path / "nope.json")


def test_malformed_json_raises_validation_error(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{\"nodes\": []}", encoding="utf-8")  # missing required
    with pytest.raises(ValidationError):
        NetworkXKG.load_from_json(path)


def test_duplicate_node_id_raises_value_error(tmp_path: Path):
    snap = json.loads(_sample_snapshot_json())
    snap["nodes"].append(snap["nodes"][0])  # duplicate
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        NetworkXKG.load_from_json(path)
```

- [ ] **Step 3: Run and see them fail**

Run: `uv run pytest tests/kg/test_networkx_kg.py -v`
Expected: FAIL with `ImportError: cannot import name 'NetworkXKG'`.

- [ ] **Step 4: Implement `NetworkXKG`**

Create `src/jurist/kg/networkx_kg.py`:

```python
"""NetworkX-backed concrete KnowledgeGraph."""
from __future__ import annotations

from pathlib import Path

import networkx as nx

from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


class NetworkXKG:
    """Concrete KnowledgeGraph. DiGraph node attrs mirror ArticleNode fields
    (minus article_id, which is the node key); edge attrs carry kind + context.
    """

    def __init__(self, graph: nx.DiGraph) -> None:
        self._graph = graph

    @classmethod
    def load_from_json(cls, path: Path) -> "NetworkXKG":
        text = path.read_text(encoding="utf-8")  # FileNotFoundError propagates
        snap = KGSnapshot.model_validate_json(text)  # ValidationError propagates
        return cls.from_snapshot(snap)

    @classmethod
    def from_snapshot(cls, snap: KGSnapshot) -> "NetworkXKG":
        node_ids = [n.article_id for n in snap.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate article_id in KG snapshot")
        edge_keys = [(e.from_id, e.to_id) for e in snap.edges]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("duplicate edge in KG snapshot")

        g = nx.DiGraph()
        for n in snap.nodes:
            attrs = n.model_dump()
            attrs.pop("article_id")
            g.add_node(n.article_id, **attrs)
        for e in snap.edges:
            g.add_edge(e.from_id, e.to_id, kind=e.kind, context=e.context)
        return cls(g)

    def all_nodes(self) -> list[ArticleNode]:
        out: list[ArticleNode] = []
        for nid, attrs in self._graph.nodes(data=True):
            out.append(ArticleNode(article_id=nid, **attrs))
        return out

    def all_edges(self) -> list[ArticleEdge]:
        out: list[ArticleEdge] = []
        for u, v, attrs in self._graph.edges(data=True):
            out.append(ArticleEdge(from_id=u, to_id=v, **attrs))
        return out

    def get_node(self, article_id: str) -> ArticleNode | None:
        if article_id not in self._graph.nodes:
            return None
        attrs = dict(self._graph.nodes[article_id])
        return ArticleNode(article_id=article_id, **attrs)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/kg/ -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/kg/networkx_kg.py tests/kg/
git commit -m "feat: kg.networkx_kg — NetworkXKG with load_from_json"
```

---

### Task 6: Allowlist

**Files:**
- Create: `src/jurist/ingest/__init__.py`
- Create: `src/jurist/ingest/allowlist.py`

- [ ] **Step 1: Create package marker**

Create `src/jurist/ingest/__init__.py` (empty).

- [ ] **Step 2: Write the allowlist**

Create `src/jurist/ingest/allowlist.py`:

```python
"""Single scope knob for ingestion. M1 ships 3 core BWBs; M1.5 widens."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BWBEntry:
    name: str                                       # full legal title
    label_prefix: str                               # human-readable prefix for ArticleNode.label
    filter_titel: tuple[str, ...] | None = None     # None = no filter; e.g., ("4",) = only Titel 4


BWB_ALLOWLIST: dict[str, BWBEntry] = {
    "BWBR0005290": BWBEntry(
        name="Burgerlijk Wetboek Boek 7",
        label_prefix="Boek 7",
        filter_titel=("4",),   # Huur only
    ),
    "BWBR0002888": BWBEntry(
        name="Uitvoeringswet huurprijzen woonruimte",
        label_prefix="Uhw",
    ),
    "BWBR0003402": BWBEntry(
        name="Besluit huurprijzen woonruimte",
        label_prefix="Besluit huurprijzen",
    ),
}
```

- [ ] **Step 3: Smoke-import and spot-check**

Run: `uv run python -c "from jurist.ingest.allowlist import BWB_ALLOWLIST; print(len(BWB_ALLOWLIST), list(BWB_ALLOWLIST))"`
Expected: `3 ['BWBR0005290', 'BWBR0002888', 'BWBR0003402']`.

- [ ] **Step 4: Commit**

```bash
git add src/jurist/ingest/__init__.py src/jurist/ingest/allowlist.py
git commit -m "feat: ingest.allowlist — 3 core BWBs with filter_titel"
```

---

### Task 7: Fetcher with cache + live fallback

**Files:**
- Create: `src/jurist/ingest/fetch.py`
- Create: `tests/ingest/__init__.py`
- Create: `tests/ingest/test_fetch.py`

The fetcher returns BWB XML bytes. The cache layer avoids repeated network hits. `--no-fetch` mode is cache-only.

The exact upstream URL template is a known unknown — see spec §5.1. Start with a reasonable default (`https://wetten.overheid.nl/xml.php?regelingid={bwb_id}`) and be prepared to update in Task 18 verification if the endpoint returns non-XML or 404. Tests mock the HTTP call, so the URL template isn't exercised in CI.

- [ ] **Step 1: Create test package marker**

Create `tests/ingest/__init__.py` (empty).

- [ ] **Step 2: Write failing tests**

Create `tests/ingest/test_fetch.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jurist.ingest.fetch import fetch_bwb_xml


def test_fetch_returns_cached_bytes_without_http(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    cache_file = tmp_path / "BWBR0005290.xml"
    cache_file.write_bytes(b"<wet>cached</wet>")

    # If HTTP is called, this test should fail — assert httpx.Client is not constructed.
    with patch("jurist.ingest.fetch.httpx.Client") as mock_client:
        result = fetch_bwb_xml("BWBR0005290")
        mock_client.assert_not_called()
    assert result == b"<wet>cached</wet>"


def test_fetch_live_writes_cache_then_returns_bytes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    fake_resp = MagicMock()
    fake_resp.content = b"<wet>fresh</wet>"
    fake_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0002888")

    assert result == b"<wet>fresh</wet>"
    assert (tmp_path / "BWBR0002888.xml").read_bytes() == b"<wet>fresh</wet>"


def test_fetch_refresh_bypasses_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    (tmp_path / "BWBR0003402.xml").write_bytes(b"<wet>old</wet>")

    fake_resp = MagicMock()
    fake_resp.content = b"<wet>new</wet>"
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0003402", refresh=True)

    assert result == b"<wet>new</wet>"


def test_fetch_no_fetch_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="cache miss"):
        fetch_bwb_xml("BWBR0009999", no_fetch=True)
```

- [ ] **Step 3: Run and see them fail**

Run: `uv run pytest tests/ingest/test_fetch.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_bwb_xml'`.

- [ ] **Step 4: Implement the fetcher**

Create `src/jurist/ingest/fetch.py`:

```python
"""BWB XML fetcher — cache-first with live httpx fallback."""
from __future__ import annotations

from pathlib import Path

import httpx

from jurist.config import settings

BWB_XML_URL_TEMPLATE = "https://wetten.overheid.nl/xml.php?regelingid={bwb_id}"
CACHE_DIR: Path = settings.data_dir / "cache" / "bwb"


def fetch_bwb_xml(bwb_id: str, *, refresh: bool = False, no_fetch: bool = False) -> bytes:
    """Return BWB XML bytes for ``bwb_id``.

    Order of operations:
      1. If cache hit and not ``refresh``, return cached bytes.
      2. If ``no_fetch``, raise FileNotFoundError on cache miss.
      3. Otherwise GET from the upstream endpoint, write to cache, return bytes.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{bwb_id}.xml"

    if cache_path.exists() and not refresh:
        return cache_path.read_bytes()

    if no_fetch:
        raise FileNotFoundError(f"cache miss for {bwb_id} and --no-fetch is set")

    url = BWB_XML_URL_TEMPLATE.format(bwb_id=bwb_id)
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content

    cache_path.write_bytes(data)
    return data
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ingest/test_fetch.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/ingest/fetch.py tests/ingest/__init__.py tests/ingest/test_fetch.py
git commit -m "feat: ingest.fetch — cache-first httpx BWB XML fetcher"
```

---

### Task 8: Obtain and commit fixture XMLs

Fixtures are real BWB XML excerpts trimmed to the minimum articles needed. They are obtained once via the fetcher and committed to the repo (small enough — ≤100 KB each).

**Files:**
- Create: `tests/ingest/fixtures/BWBR0005290_excerpt.xml`
- Create: `tests/ingest/fixtures/BWBR0002888_excerpt.xml`
- Create: `tests/ingest/fixtures/BWBR0003402_excerpt.xml`

- [ ] **Step 1: Create the fixtures directory**

Run: `mkdir -p tests/ingest/fixtures`

- [ ] **Step 2: Fetch the full XMLs into the cache**

Run:
```bash
uv run python -c "
from jurist.ingest.fetch import fetch_bwb_xml
for bwb in ['BWBR0005290', 'BWBR0002888', 'BWBR0003402']:
    data = fetch_bwb_xml(bwb, refresh=True)
    print(bwb, len(data), 'bytes')
"
```

Expected: three lines with byte counts. If any line shows an HTML 404 or connection error, the upstream endpoint has shifted — update `BWB_XML_URL_TEMPLATE` in `fetch.py` (candidates in spec §5.1) and re-run. If nothing works, manually download via browser from `https://wetten.overheid.nl/BWBR0005290` (there's an XML link) and drop files into `data/cache/bwb/`.

- [ ] **Step 3: Trim each cached XML to an excerpt**

Open `data/cache/bwb/BWBR0005290.xml` in an editor. Keep the document root + wrapper elements (wet/intref-metadata) and the `<boek nr="7">` → `<titel nr="4">` → `<afdeling nr="5">` → articles. Specifically preserve articles 246 through 265 (plus any needed wrapping afdelingen in Titel 4). Remove Titels 1-3, 5+, and Afdelingen outside of Titel 4. Save to `tests/ingest/fixtures/BWBR0005290_excerpt.xml`. Aim for ≤100 KB.

For `BWBR0002888.xml`: keep at least articles 6 and 10 plus minimal wrapping. Save to `tests/ingest/fixtures/BWBR0002888_excerpt.xml`.

For `BWBR0003402.xml`: keep any 2-3 articles (skip the bijlage). Save to `tests/ingest/fixtures/BWBR0003402_excerpt.xml`.

- [ ] **Step 4: Validate excerpts parse as XML**

Run:
```bash
uv run python -c "
from pathlib import Path
from lxml import etree
for p in Path('tests/ingest/fixtures').glob('*.xml'):
    tree = etree.parse(str(p))
    arts = tree.getroot().findall('.//artikel')
    print(p.name, len(arts), 'articles')
"
```

Expected: three lines; BWBR0005290 excerpt shows ≥15 articles, BWBR0002888 shows ≥2, BWBR0003402 shows ≥2.

- [ ] **Step 5: Confirm file sizes**

Run: `ls -la tests/ingest/fixtures/`
Expected: each file ≤100 KB.

- [ ] **Step 6: Commit**

```bash
git add tests/ingest/fixtures/
git commit -m "test: add BWB XML fixture excerpts (BW7 Titel 4, Uhw, Besluit)"
```

---

### Task 9: Parser — walk, article_id, label

**Files:**
- Create: `src/jurist/ingest/parser.py`
- Create: `tests/ingest/test_parser.py`

- [ ] **Step 1: Write failing tests — basic walk + article_id**

Create `tests/ingest/test_parser.py`:

```python
from pathlib import Path

import pytest
from lxml import etree

from jurist.ingest.allowlist import BWB_ALLOWLIST, BWBEntry
from jurist.ingest.parser import parse_bwb_xml


MINI_BW7_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet>
  <boek nr="7">
    <titel nr="4">
      <afdeling nr="5">
        <artikel nr="248">
          <kop><titel>Huurverhoging</titel></kop>
          <lid><al>De verhuurder kan tot aan ...</al></lid>
          <lid><al>Wanneer de huurder bezwaar maakt ...</al></lid>
        </artikel>
        <artikel nr="249">
          <kop><titel>Voorstel</titel></kop>
          <lid><al>Een voorstel tot huurverhoging bevat ...</al></lid>
        </artikel>
        <artikel nr="248a">
          <kop><titel>Bijzondere gevallen</titel></kop>
          <lid><al>In bijzondere gevallen ...</al></lid>
        </artikel>
        <artikel nr="999" status="vervallen">
          <kop><titel>[Vervallen]</titel></kop>
        </artikel>
      </afdeling>
    </titel>
    <titel nr="5">
      <afdeling nr="1">
        <artikel nr="500">
          <kop><titel>Niet huurrecht</titel></kop>
          <lid><al>Dit artikel staat buiten Titel 4.</al></lid>
        </artikel>
      </afdeling>
    </titel>
  </boek>
</wet>
"""


def _bw7_entry() -> BWBEntry:
    return BWB_ALLOWLIST["BWBR0005290"]


def test_parses_structural_article_id():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    ids = {n.article_id for n in nodes}
    assert "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248" in ids
    assert "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249" in ids


def test_preserves_letter_suffix():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    ids = {n.article_id for n in nodes}
    assert "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248a" in ids


def test_skips_vervallen():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    ids = {n.article_id for n in nodes}
    assert not any("999" in i for i in ids)


def test_titel_filter_drops_titel_5():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    ids = {n.article_id for n in nodes}
    assert not any("Titel5" in i for i in ids)
    assert not any("500" in i for i in ids)


def test_label_uses_prefix_and_number():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    labels = {n.label for n in nodes}
    assert "Boek 7, Artikel 248" in labels


def test_body_text_concatenates_leden():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    a248 = next(n for n in nodes if n.article_id.endswith("/Artikel248"))
    assert "De verhuurder kan" in a248.body_text
    assert "Wanneer de huurder" in a248.body_text
    assert "\n\n" in a248.body_text


def test_title_extracted():
    nodes, _ = parse_bwb_xml(MINI_BW7_XML, "BWBR0005290", _bw7_entry())
    a248 = next(n for n in nodes if n.article_id.endswith("/Artikel248"))
    assert a248.title == "Huurverhoging"


MINI_UHW_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet>
  <artikel nr="6">
    <kop><titel>Maximaal huurverhogingspercentage</titel></kop>
    <lid><al>Het maximale percentage ...</al></lid>
  </artikel>
  <artikel nr="10">
    <kop><titel>Geschilbeslechting</titel></kop>
    <lid><al>Een geschil ...</al></lid>
  </artikel>
</wet>
"""


def test_flat_bwb_article_id():
    nodes, _ = parse_bwb_xml(MINI_UHW_XML, "BWBR0002888", BWB_ALLOWLIST["BWBR0002888"])
    ids = {n.article_id for n in nodes}
    assert "BWBR0002888/Artikel6" in ids
    assert "BWBR0002888/Artikel10" in ids


def test_flat_bwb_label_uses_uhw_prefix():
    nodes, _ = parse_bwb_xml(MINI_UHW_XML, "BWBR0002888", BWB_ALLOWLIST["BWBR0002888"])
    labels = {n.label for n in nodes}
    assert "Uhw, Artikel 6" in labels


# Spec-required test against the committed fixture
def test_parses_art_7_248_bw_from_fixture():
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    xml = fixture.read_bytes()
    nodes, _ = parse_bwb_xml(xml, "BWBR0005290", _bw7_entry())
    a248 = next(
        (n for n in nodes if n.article_id == "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"),
        None,
    )
    assert a248 is not None, "art. 7:248 BW not found in parsed fixture"
    assert a248.label == "Boek 7, Artikel 248"
    assert len(a248.body_text) > 50  # real article has substantive body
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/ingest/test_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_bwb_xml'`.

- [ ] **Step 3: Implement the parser**

Create `src/jurist/ingest/parser.py`:

```python
"""Schema-conformant BWB XML parser.

Walks the tree, emits ArticleNodes + explicit edges from <intref>/<extref>.
The node walk is generic; widening the allowlist to new BWBs must not need
parser changes.
"""
from __future__ import annotations

import re

from lxml import etree

from jurist.ingest.allowlist import BWBEntry
from jurist.schemas import ArticleEdge, ArticleNode

CONTAINER_TAGS = frozenset({"boek", "titel", "afdeling", "hoofdstuk", "paragraaf"})


def parse_bwb_xml(
    xml_bytes: bytes, bwb_id: str, entry: BWBEntry
) -> tuple[list[ArticleNode], list[ArticleEdge]]:
    """Return (nodes, explicit_edges) from a single BWB XML document.

    Applies ``entry.filter_titel`` and skips ``vervallen`` articles.
    Explicit edges come from <intref> and <extref> elements; targets
    that don't resolve (or are cross-BWB to an out-of-allowlist id)
    are dropped silently — the caller can't validate targets anyway
    since we only have this BWB's nodes at call time.
    """
    root = etree.fromstring(xml_bytes)

    nodes: list[ArticleNode] = []
    explicit_edges: list[ArticleEdge] = []

    for artikel in root.iter("artikel"):
        if _is_vervallen(artikel):
            continue
        nr = artikel.get("nr")
        if not nr:
            continue

        path_segments = _container_path(artikel)
        if entry.filter_titel is not None and not _passes_titel_filter(
            path_segments, entry.filter_titel
        ):
            continue

        article_id = _build_article_id(bwb_id, path_segments, nr)
        node = ArticleNode(
            article_id=article_id,
            bwb_id=bwb_id,
            label=f"{entry.label_prefix}, Artikel {nr}",
            title=_extract_title(artikel),
            body_text=_extract_body(artikel),
            outgoing_refs=[],
        )
        nodes.append(node)

        for edge in _extract_explicit_edges(artikel, article_id, bwb_id):
            explicit_edges.append(edge)

    _populate_outgoing_refs(nodes, explicit_edges)
    return nodes, explicit_edges


def _is_vervallen(artikel: etree._Element) -> bool:
    if artikel.get("status") == "vervallen":
        return True
    kop = artikel.find("kop")
    if kop is not None:
        text = " ".join(kop.itertext()).strip()
        if text == "[Vervallen]" or text == "":
            return True
    return False


def _container_path(artikel: etree._Element) -> list[str]:
    path: list[str] = []
    for anc in artikel.iterancestors():
        if anc.tag in CONTAINER_TAGS:
            nr = anc.get("nr", "")
            path.append(f"{anc.tag.capitalize()}{nr}")
    return list(reversed(path))


def _passes_titel_filter(path_segments: list[str], allowed: tuple[str, ...]) -> bool:
    for seg in path_segments:
        if seg.startswith("Titel"):
            return seg[len("Titel"):] in allowed
    return False  # no Titel ancestor → fails a titel-filter entry


def _build_article_id(bwb_id: str, path_segments: list[str], nr: str) -> str:
    if path_segments:
        return f"{bwb_id}/{'/'.join(path_segments)}/Artikel{nr}"
    return f"{bwb_id}/Artikel{nr}"


def _extract_title(artikel: etree._Element) -> str:
    kop = artikel.find("kop")
    if kop is None:
        return ""
    titel = kop.find("titel")
    if titel is None:
        return ""
    return " ".join(titel.itertext()).strip()


def _extract_body(artikel: etree._Element) -> str:
    parts: list[str] = []
    for al in artikel.iter("al"):
        text = " ".join(al.itertext()).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


_HREF_INTREF_RE = re.compile(r"#artikel(\d+[a-z]?)", re.IGNORECASE)
_HREF_EXTREF_RE = re.compile(r"(BWBR\d+)[#/]artikel(\d+[a-z]?)", re.IGNORECASE)


def _extract_explicit_edges(
    artikel: etree._Element, source_article_id: str, source_bwb: str
) -> list[ArticleEdge]:
    out: list[ArticleEdge] = []
    for ref in artikel.iter("intref"):
        href = ref.get("href", "")
        m = _HREF_INTREF_RE.search(href)
        if m:
            out.append(
                ArticleEdge(
                    from_id=source_article_id,
                    to_id=f"{source_bwb}::Artikel{m.group(1)}",  # sentinel; resolved later
                    kind="explicit",
                )
            )
    for ref in artikel.iter("extref"):
        # Try attribute form first: bwb-id="BWBR0002888" + either artikel-nr or aref
        bwb_attr = ref.get("bwb-id")
        nr_attr = ref.get("artikel-nr") or ref.get("aref")
        if bwb_attr and nr_attr:
            out.append(
                ArticleEdge(
                    from_id=source_article_id,
                    to_id=f"{bwb_attr}::Artikel{nr_attr}",  # sentinel
                    kind="explicit",
                )
            )
            continue
        # Fall back to href parsing
        href = ref.get("href", "")
        m = _HREF_EXTREF_RE.search(href)
        if m:
            out.append(
                ArticleEdge(
                    from_id=source_article_id,
                    to_id=f"{m.group(1).upper()}::Artikel{m.group(2)}",
                    kind="explicit",
                )
            )
    return out


def _populate_outgoing_refs(nodes: list[ArticleNode], edges: list[ArticleEdge]) -> None:
    """Fill ArticleNode.outgoing_refs from the edges list. Sentinel to_ids
    (format ``{bwb}::Artikel{nr}``) are kept as-is at this stage — the xrefs
    module resolves them against the full cross-BWB node set.
    """
    by_source: dict[str, list[str]] = {}
    for e in edges:
        by_source.setdefault(e.from_id, []).append(e.to_id)
    for n in nodes:
        if n.article_id in by_source:
            n.outgoing_refs = list(by_source[n.article_id])
```

Note on sentinels: `to_id` from `_extract_explicit_edges` may be a `{bwb}::Artikel{nr}` sentinel because this function doesn't know the full cross-BWB node set yet. Task 10 (`xrefs.py`) resolves sentinels against the union of all parsed nodes. Same-BWB `<intref>` targets use the source BWB; cross-BWB `<extref>` uses the declared BWB. If no node matches, the edge is dropped.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ingest/test_parser.py -v`
Expected: all tests PASS, including the fixture-based `test_parses_art_7_248_bw_from_fixture`.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/parser.py tests/ingest/test_parser.py
git commit -m "feat: ingest.parser — schema-conformant BWB XML walk"
```

---

### Task 10: Xrefs — regex pass, sentinel resolution, dedup

**Files:**
- Create: `src/jurist/ingest/xrefs.py`
- Create: `tests/ingest/test_xrefs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/ingest/test_xrefs.py`:

```python
from jurist.schemas import ArticleEdge, ArticleNode
from jurist.ingest.xrefs import (
    extract_regex_edges,
    merge_edges,
    resolve_sentinel_edges,
)


def _node(article_id: str, bwb: str, body: str = "") -> ArticleNode:
    return ArticleNode(
        article_id=article_id,
        bwb_id=bwb,
        label=article_id,
        title="",
        body_text=body,
        outgoing_refs=[],
    )


def test_regex_matches_simple_article_ref():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "De verhuurder verwijst naar artikel 249.",
    )
    target = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249", "BWBR0005290"
    )
    edges = extract_regex_edges([n, target])
    assert ArticleEdge(
        from_id=n.article_id, to_id=target.article_id, kind="regex"
    ) in edges


def test_regex_ignores_lid_suffix():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "Zie artikel 249 lid 2 voor details.",
    )
    target = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249", "BWBR0005290"
    )
    edges = extract_regex_edges([n, target])
    assert any(e.to_id.endswith("/Artikel249") for e in edges)


def test_regex_preserves_letter_suffix():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "Zie artikel 249a.",
    )
    target = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249a", "BWBR0005290"
    )
    edges = extract_regex_edges([n, target])
    assert any(e.to_id.endswith("/Artikel249a") for e in edges)


def test_regex_compound_ref_matches_only_leading():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "de artikelen 249 en 250",
    )
    t1 = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249", "BWBR0005290"
    )
    t2 = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel250", "BWBR0005290"
    )
    edges = extract_regex_edges([n, t1, t2])
    matched_targets = {e.to_id for e in edges if e.from_id == n.article_id}
    assert t1.article_id in matched_targets
    # Trailing "250" is expected to be picked up by explicit <intref>, not regex
    assert t2.article_id not in matched_targets


def test_regex_prose_false_positive_guard():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "In 249 gevallen was de uitkomst anders.",
    )
    # Target article exists but should not be linked — "249" here is a count, not a ref.
    target = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249", "BWBR0005290"
    )
    edges = extract_regex_edges([n, target])
    assert not any(e.from_id == n.article_id for e in edges)


def test_regex_drops_missing_target():
    n = _node(
        "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        "BWBR0005290",
        "Zie artikel 9999.",
    )
    edges = extract_regex_edges([n])  # no target for 9999
    assert edges == []


def test_resolve_sentinel_intref():
    all_nodes = [
        _node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248", "BWBR0005290"),
        _node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249", "BWBR0005290"),
    ]
    sentinel = ArticleEdge(
        from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        to_id="BWBR0005290::Artikel249",
        kind="explicit",
    )
    resolved = resolve_sentinel_edges([sentinel], all_nodes)
    assert len(resolved) == 1
    assert resolved[0].to_id == "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"


def test_resolve_sentinel_extref_to_other_bwb():
    all_nodes = [
        _node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248", "BWBR0005290"),
        _node("BWBR0002888/Artikel6", "BWBR0002888"),
    ]
    sentinel = ArticleEdge(
        from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        to_id="BWBR0002888::Artikel6",
        kind="explicit",
    )
    resolved = resolve_sentinel_edges([sentinel], all_nodes)
    assert resolved[0].to_id == "BWBR0002888/Artikel6"


def test_resolve_sentinel_drops_out_of_allowlist():
    all_nodes = [
        _node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248", "BWBR0005290"),
    ]
    sentinel = ArticleEdge(
        from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        to_id="BWBR0099999::Artikel1",  # not in node set
        kind="explicit",
    )
    assert resolve_sentinel_edges([sentinel], all_nodes) == []


def test_resolve_sentinel_drops_ambiguous():
    # Two candidates in same BWB matching /Artikel1 — drop rather than guess
    all_nodes = [
        _node("BWBR0005290/Boek6/Titel1/Artikel1", "BWBR0005290"),
        _node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel1", "BWBR0005290"),
    ]
    sentinel = ArticleEdge(
        from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel1",
        to_id="BWBR0005290::Artikel1",
        kind="explicit",
    )
    # Ambiguous lookup → drop
    assert resolve_sentinel_edges([sentinel], all_nodes) == []


def test_merge_prefers_explicit_over_regex():
    a = "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"
    b = "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex = [ArticleEdge(from_id=a, to_id=b, kind="regex")]
    merged = merge_edges(explicit, regex)
    assert len(merged) == 1
    assert merged[0].kind == "explicit"


def test_merge_keeps_regex_only_when_no_explicit_match():
    a = "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"
    b = "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"
    c = "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel250"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex = [ArticleEdge(from_id=a, to_id=c, kind="regex")]
    merged = merge_edges(explicit, regex)
    kinds_by_target = {e.to_id: e.kind for e in merged}
    assert kinds_by_target[b] == "explicit"
    assert kinds_by_target[c] == "regex"
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/ingest/test_xrefs.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_regex_edges'`.

- [ ] **Step 3: Implement `xrefs.py`**

Create `src/jurist/ingest/xrefs.py`:

```python
"""Cross-reference extraction: regex fallback pass + sentinel resolution + dedup.

See spec §5.3. Explicit edges from <intref>/<extref> come from the parser
carrying sentinel ``to_id`` like ``"BWBR0005290::Artikel249"``. This module
resolves sentinels against the full multi-BWB node set, emits regex-based
same-BWB edges from body_text, and merges with dedup preferring explicit.
"""
from __future__ import annotations

import re

from jurist.schemas import ArticleEdge, ArticleNode

# Matches "artikel 248", "artikelen 249", "artikel 248a", optionally followed
# by "eerste|tweede|...|Ne lid" (lid ignored — edges are article-level).
# Uses a word boundary before "artikel" to skip mid-word matches.
ARTICLE_REF_PATTERN = re.compile(
    r"\bartikel(?:en)?\s+(\d+[a-z]?)"
    r"(?:\s+(?:eerste|tweede|derde|vierde|vijfde|zesde|zevende|achtste|negende|tiende|\d+e)\s+lid)?",
    re.IGNORECASE,
)


def extract_regex_edges(nodes: list[ArticleNode]) -> list[ArticleEdge]:
    """Run the regex pass over each node's body_text; emit same-BWB edges.

    Resolves each hit against the passed-in node set by suffix match in the
    same BWB. Ambiguous or missing targets → drop silently.
    """
    by_bwb_suffix: dict[tuple[str, str], list[str]] = {}
    for n in nodes:
        # Each node's article_id ends with "/Artikel<nr>"; index by (bwb, suffix).
        suffix = n.article_id.rsplit("/", 1)[-1]  # e.g., "Artikel249"
        by_bwb_suffix.setdefault((n.bwb_id, suffix), []).append(n.article_id)

    edges: list[ArticleEdge] = []
    seen: set[tuple[str, str]] = set()
    for n in nodes:
        for m in ARTICLE_REF_PATTERN.finditer(n.body_text):
            nr = m.group(1)
            key = (n.bwb_id, f"Artikel{nr}")
            candidates = by_bwb_suffix.get(key, [])
            if len(candidates) != 1:  # ambiguous or missing → drop
                continue
            target = candidates[0]
            if target == n.article_id:  # self-link — skip
                continue
            dedup_key = (n.article_id, target)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            edges.append(
                ArticleEdge(from_id=n.article_id, to_id=target, kind="regex")
            )
    return edges


def resolve_sentinel_edges(
    edges: list[ArticleEdge], all_nodes: list[ArticleNode]
) -> list[ArticleEdge]:
    """Resolve ``{bwb}::Artikel{nr}`` sentinels in ``edges[*].to_id`` against
    ``all_nodes``. Ambiguous or missing targets → drop silently.
    """
    by_bwb_suffix: dict[tuple[str, str], list[str]] = {}
    for n in all_nodes:
        suffix = n.article_id.rsplit("/", 1)[-1]
        by_bwb_suffix.setdefault((n.bwb_id, suffix), []).append(n.article_id)

    resolved: list[ArticleEdge] = []
    for e in edges:
        if "::" not in e.to_id:
            resolved.append(e)  # already a real article_id
            continue
        bwb, suffix = e.to_id.split("::", 1)
        candidates = by_bwb_suffix.get((bwb, suffix), [])
        if len(candidates) != 1:
            continue  # drop ambiguous / missing
        resolved.append(
            ArticleEdge(
                from_id=e.from_id,
                to_id=candidates[0],
                kind=e.kind,
                context=e.context,
            )
        )
    return resolved


def merge_edges(
    explicit: list[ArticleEdge], regex: list[ArticleEdge]
) -> list[ArticleEdge]:
    """Dedup by ``(from_id, to_id)``. Prefer ``kind="explicit"`` over ``"regex"``."""
    by_key: dict[tuple[str, str], ArticleEdge] = {}
    for e in explicit:
        by_key[(e.from_id, e.to_id)] = e
    for e in regex:
        key = (e.from_id, e.to_id)
        if key not in by_key:
            by_key[key] = e
    return list(by_key.values())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ingest/test_xrefs.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/xrefs.py tests/ingest/test_xrefs.py
git commit -m "feat: ingest.xrefs — regex pass + sentinel resolution + explicit-wins dedup"
```

---

### Task 11: Statutes orchestrator

**Files:**
- Create: `src/jurist/ingest/statutes.py`
- Create: `tests/ingest/test_idempotency.py`

The orchestrator:
1. Reads the version stamp from each fetched BWB XML.
2. Short-circuits if all match the existing `source_versions` in `huurrecht.json` and not `--refresh`.
3. Otherwise parses each BWB, collects nodes + explicit edges.
4. Runs `extract_regex_edges` over the union of all nodes.
5. Resolves sentinel edges; merges explicit + regex.
6. Writes `huurrecht.json` atomically and `data/articles/<bwb>/<flat>.md` dumps.

Version-stamp extraction reads `root.get("vigerend-sinds")` (or `"inwerkingtreding"`, whichever the XML provides). If both are missing, use the current UTC date — idempotency becomes a no-op for that source, but the pipeline still runs.

- [ ] **Step 1: Write failing tests — idempotency**

Create `tests/ingest/test_idempotency.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

from jurist.ingest.statutes import run_ingest


MINI_XML_V1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet vigerend-sinds="2024-01-01">
  <artikel nr="1">
    <kop><titel>First</titel></kop>
    <lid><al>Body one.</al></lid>
  </artikel>
</wet>
"""

MINI_XML_V2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet vigerend-sinds="2025-06-01">
  <artikel nr="1">
    <kop><titel>First updated</titel></kop>
    <lid><al>Body updated.</al></lid>
  </artikel>
</wet>
"""


def _isolate(tmp_path, monkeypatch):
    """Redirect data dir + patch allowlist to a single BWB for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings.data_dir", data_dir)
    # Cache dir used by fetch.fetch_bwb_xml:
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data_dir / "cache" / "bwb")
    # Shrink allowlist to one BWB for a focused test
    from jurist.ingest.allowlist import BWBEntry
    monkeypatch.setattr(
        "jurist.ingest.statutes.BWB_ALLOWLIST",
        {"BWBR0002888": BWBEntry(name="Test", label_prefix="Test")},
    )
    return data_dir


def test_idempotent_short_circuits_when_versions_match(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1) as m:
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
        assert m.call_count == 1

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1) as m:
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
        # Still fetches (to compare versions) but does NOT rewrite the parse
        assert m.call_count == 1

    # The JSON should exist
    out = data_dir / "kg" / "huurrecht.json"
    assert out.exists()


def test_refresh_forces_reparse_on_matching_versions(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)
    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    first_mtime = out.stat().st_mtime

    import time
    time.sleep(0.05)  # ensure mtime changes on rewrite

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=True, no_fetch=False, bwb_ids=None, limit=None)

    assert out.stat().st_mtime > first_mtime


def test_version_change_triggers_reparse(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    snap_before = json.loads(out.read_text(encoding="utf-8"))
    assert snap_before["source_versions"]["BWBR0002888"] == "2024-01-01"

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V2):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    snap_after = json.loads(out.read_text(encoding="utf-8"))
    assert snap_after["source_versions"]["BWBR0002888"] == "2025-06-01"
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/ingest/test_idempotency.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_ingest'`.

- [ ] **Step 3: Implement the orchestrator**

Create `src/jurist/ingest/statutes.py`:

```python
"""Orchestrates the full ingest pipeline.

Per-BWB:
  1. Fetch (cache-first) + extract version stamp.
  2. Short-circuit on matching source_versions unless --refresh.
  3. Parse → (nodes, explicit_sentinel_edges).
  4. Collect across BWBs; run regex pass over union.
  5. Resolve sentinels; merge explicit + regex.
  6. Write huurrecht.json atomically; dump per-article .md files.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from lxml import etree

from jurist.config import settings
from jurist.ingest.allowlist import BWB_ALLOWLIST
from jurist.ingest.fetch import fetch_bwb_xml
from jurist.ingest.parser import parse_bwb_xml
from jurist.ingest.xrefs import (
    extract_regex_edges,
    merge_edges,
    resolve_sentinel_edges,
)
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


def run_ingest(
    *,
    refresh: bool,
    no_fetch: bool,
    bwb_ids: list[str] | None,
    limit: int | None,
    verbose: bool = False,
) -> KGSnapshot:
    """Run the full pipeline. Returns the written snapshot.

    Parameters mirror the CLI flags in __main__.py.
    """
    selected = bwb_ids or list(BWB_ALLOWLIST.keys())
    started = time.perf_counter()

    # --- Pass 1: fetch + version gating ---
    fetched: dict[str, tuple[bytes, str]] = {}  # bwb_id -> (bytes, version)
    for bwb in selected:
        if bwb not in BWB_ALLOWLIST:
            raise ValueError(f"{bwb} not in allowlist")
        data = fetch_bwb_xml(bwb, refresh=refresh, no_fetch=no_fetch)
        version = _extract_version(data)
        fetched[bwb] = (data, version)

    out_path = settings.data_dir / "kg" / "huurrecht.json"
    existing = _load_existing(out_path) if out_path.exists() else None
    if (
        not refresh
        and existing is not None
        and all(
            existing.source_versions.get(bwb) == ver for bwb, (_, ver) in fetched.items()
        )
        and set(existing.source_versions.keys()) >= set(fetched.keys())
    ):
        if verbose:
            print("Ingest: no changes; skipping parse.")
        return existing

    # --- Pass 2: parse each BWB ---
    all_nodes: list[ArticleNode] = []
    all_explicit: list[ArticleEdge] = []
    per_bwb_counts: dict[str, int] = {}
    for bwb, (data, _) in fetched.items():
        entry = BWB_ALLOWLIST[bwb]
        nodes, explicit = parse_bwb_xml(data, bwb, entry)
        if limit is not None:
            nodes = nodes[:limit]
            kept_ids = {n.article_id for n in nodes}
            explicit = [e for e in explicit if e.from_id in kept_ids]
        per_bwb_counts[bwb] = len(nodes)
        all_nodes.extend(nodes)
        all_explicit.extend(explicit)

    # --- Pass 3: edges ---
    resolved_explicit = resolve_sentinel_edges(all_explicit, all_nodes)
    regex_edges = extract_regex_edges(all_nodes)
    merged = merge_edges(resolved_explicit, regex_edges)

    # Repopulate ArticleNode.outgoing_refs from the merged edge list
    refs_by_source: dict[str, list[str]] = {}
    for e in merged:
        refs_by_source.setdefault(e.from_id, []).append(e.to_id)
    for n in all_nodes:
        n.outgoing_refs = refs_by_source.get(n.article_id, [])

    # --- Pass 4: serialize ---
    snap = KGSnapshot(
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        source_versions={bwb: ver for bwb, (_, ver) in fetched.items()},
        nodes=all_nodes,
        edges=merged,
    )
    _write_snapshot_atomic(snap, out_path)
    _write_article_dumps(all_nodes)

    if verbose:
        dur = time.perf_counter() - started
        by = ", ".join(
            f"{BWB_ALLOWLIST[bwb].label_prefix} {n}" for bwb, n in per_bwb_counts.items()
        )
        print(
            f"Ingest complete: {len(all_nodes)} articles, {len(merged)} edges "
            f"from {len(fetched)} sources ({by}) in {dur:.1f}s."
        )
        size_kb = out_path.stat().st_size / 1024
        print(f"Output: {out_path} ({size_kb:.0f} KB)")

    return snap


def _extract_version(xml_bytes: bytes) -> str:
    root = etree.fromstring(xml_bytes)
    for attr in ("vigerend-sinds", "inwerkingtreding"):
        v = root.get(attr)
        if v:
            return v
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_existing(path: Path) -> KGSnapshot | None:
    try:
        return KGSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_snapshot_atomic(snap: KGSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_article_dumps(nodes: list[ArticleNode]) -> None:
    root = settings.data_dir / "articles"
    for n in nodes:
        flat = n.article_id.split("/", 1)[1].replace("/", "-") if "/" in n.article_id else n.article_id
        target = root / n.bwb_id / f"{flat}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            f"article_id: {n.article_id}\n"
            f"label: {n.label}\n"
            f"title: {json.dumps(n.title)}\n"
            f"outgoing_refs: {json.dumps(n.outgoing_refs)}\n"
            "---\n\n"
            f"# {n.label}\n\n"
            f"{n.body_text}\n"
        )
        target.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ingest/test_idempotency.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/statutes.py tests/ingest/test_idempotency.py
git commit -m "feat: ingest.statutes — orchestrator with source_versions short-circuit"
```

---

### Task 12: CLI entry (`python -m jurist.ingest.statutes`)

**Files:**
- Create: `src/jurist/ingest/__main__.py`

- [ ] **Step 1: Implement the CLI**

Create `src/jurist/ingest/__main__.py`:

```python
"""`python -m jurist.ingest.statutes` — CLI entry."""
from __future__ import annotations

import argparse
import sys

from jurist.ingest.statutes import run_ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jurist.ingest.statutes",
        description="Fetch + parse BWB XML; write data/kg/huurrecht.json.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch and re-parse (bypass source_versions check).",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Cache-only; fail if cache is empty for any allowlist BWB.",
    )
    parser.add_argument(
        "--bwb",
        action="append",
        dest="bwb_ids",
        default=None,
        metavar="BWB_ID",
        help="Restrict to specific BWB IDs (debug; repeatable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap articles per BWB (debug).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print per-step summary."
    )
    args = parser.parse_args(argv)

    try:
        run_ingest(
            refresh=args.refresh,
            no_fetch=args.no_fetch,
            bwb_ids=args.bwb_ids,
            limit=args.limit,
            verbose=True,  # always verbose for CLI; library callers opt in
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test — help message**

Run: `uv run python -m jurist.ingest.statutes --help`
Expected: argparse usage output, no errors.

- [ ] **Step 3: Smoke test — --no-fetch with no cache**

Run (in a shell where `data/cache/bwb/` may be empty — not a problem if it isn't, the point is just to check the error path):
```bash
rm -rf /tmp/jurist_cli_test_cache
JURIST_DATA_DIR=/tmp/jurist_cli_test_cache uv run python -m jurist.ingest.statutes --no-fetch --bwb BWBR0005290 -v
```
Expected: exits with code 2 and prints `error: cache miss for BWBR0005290 and --no-fetch is set`.

- [ ] **Step 4: Commit**

```bash
git add src/jurist/ingest/__main__.py
git commit -m "feat: ingest CLI — python -m jurist.ingest.statutes"
```

---

### Task 13: Integration — end-to-end ingest on fixtures

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_ingest_end_to_end.py`

- [ ] **Step 1: Create package marker**

Create `tests/integration/__init__.py` (empty).

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_ingest_end_to_end.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from jurist.ingest.allowlist import BWB_ALLOWLIST
from jurist.ingest.statutes import run_ingest
from jurist.schemas import KGSnapshot

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


def _fixture_bytes_for(bwb_id: str) -> bytes:
    return (FIXTURES / f"{bwb_id}_excerpt.xml").read_bytes()


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings.data_dir", data)
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data / "cache" / "bwb")
    return data


def _fake_fetch(bwb_id: str, **_kw) -> bytes:
    return _fixture_bytes_for(bwb_id)


def test_end_to_end_ingest_on_fixtures(isolated_data, monkeypatch):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    assert isinstance(snap, KGSnapshot)
    out_path = isolated_data / "kg" / "huurrecht.json"
    assert out_path.exists()

    parsed = KGSnapshot.model_validate_json(out_path.read_text(encoding="utf-8"))
    assert set(parsed.source_versions.keys()) == set(BWB_ALLOWLIST.keys())
    assert len(parsed.nodes) > 0
    # Article dumps written for each node
    for n in parsed.nodes[:5]:  # spot check
        flat = n.article_id.split("/", 1)[1].replace("/", "-")
        dump = isolated_data / "articles" / n.bwb_id / f"{flat}.md"
        assert dump.exists(), f"missing dump for {n.article_id}"
        content = dump.read_text(encoding="utf-8")
        assert n.label in content
        assert n.body_text in content
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/integration/test_ingest_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_ingest_end_to_end.py
git commit -m "test: integration — end-to-end ingest on fixture XMLs"
```

---

### Task 14: Integration — fake-path drift catch

**Files:**
- Create: `tests/integration/test_fake_paths_in_real_kg.py`

- [ ] **Step 1: Write the drift-catch test**

Create `tests/integration/test_fake_paths_in_real_kg.py`:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from jurist.fakes import FAKE_ANSWER, FAKE_VISIT_PATH
from jurist.ingest.statutes import run_ingest

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings.data_dir", data)
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data / "cache" / "bwb")
    return data


def _fake_fetch(bwb_id: str, **_kw) -> bytes:
    return (FIXTURES / f"{bwb_id}_excerpt.xml").read_bytes()


def test_fake_visit_path_ids_exist_in_real_kg(isolated_data):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
    node_ids = {n.article_id for n in snap.nodes}
    missing = [aid for aid in FAKE_VISIT_PATH if aid not in node_ids]
    assert not missing, f"FAKE_VISIT_PATH drift: missing {missing} in real KG"


def test_fake_answer_citations_resolve_to_real_kg(isolated_data):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
    labels = {n.label for n in snap.nodes}
    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        assert cit.article_label in labels, (
            f"FAKE_ANSWER citation drift: {cit.article_label!r} not among real labels"
        )
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/integration/test_fake_paths_in_real_kg.py -v`
Expected: PASS. If it fails with "missing X in real KG", the parser's article_id format has drifted from FAKE_VISIT_PATH or the fixture excerpts don't cover those articles — fix the fixture first (add the missing articles), or adjust `fakes.py` to match real output.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_fake_paths_in_real_kg.py
git commit -m "test: integration — fake-path drift catch (FAKE_VISIT_PATH ⊂ real KG)"
```

---

### Task 15: API — lifespan load + `/api/kg` swap

**Files:**
- Modify: `src/jurist/api/app.py`
- Create: `tests/api/test_kg_endpoint.py`

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_kg_endpoint.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_SAMPLE_SNAPSHOT = {
    "generated_at": "2026-04-20T10:00:00Z",
    "source_versions": {"BWBR0005290": "2024-01-01"},
    "nodes": [
        {
            "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            "bwb_id": "BWBR0005290",
            "label": "Boek 7, Artikel 248",
            "title": "Huurverhoging",
            "body_text": "De verhuurder kan ...",
            "outgoing_refs": ["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"],
        },
        {
            "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
            "bwb_id": "BWBR0005290",
            "label": "Boek 7, Artikel 249",
            "title": "Voorstel",
            "body_text": "Een voorstel ...",
            "outgoing_refs": [],
        },
    ],
    "edges": [
        {
            "from_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            "to_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
            "kind": "explicit",
            "context": None,
        }
    ],
}


def _write_kg(tmp_path: Path) -> Path:
    p = tmp_path / "kg" / "huurrecht.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_SAMPLE_SNAPSHOT), encoding="utf-8")
    return p


def test_api_kg_returns_loaded_nodes_and_edges(tmp_path: Path, monkeypatch):
    # Patch data_dir (plain field) rather than kg_path (property) so the
    # property recomputes cleanly on each access.
    monkeypatch.setattr("jurist.config.settings.data_dir", tmp_path)
    _write_kg(tmp_path)  # writes to tmp_path/kg/huurrecht.json, which kg_path now points at
    from jurist.api.app import app  # imported after monkeypatch

    with TestClient(app) as client:
        resp = client.get("/api/kg")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) == 2
        assert len(body["edges"]) == 1
        assert body["nodes"][0]["article_id"].startswith("BWBR0005290/")


def test_api_startup_hard_fails_on_missing_kg(tmp_path: Path, monkeypatch):
    # data_dir exists but kg/huurrecht.json under it does not
    monkeypatch.setattr("jurist.config.settings.data_dir", tmp_path)
    from jurist.api.app import app

    with pytest.raises(RuntimeError, match="KG not found"):
        with TestClient(app):
            pass
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/api/test_kg_endpoint.py -v`
Expected: FAIL because `app.py` still serves `FAKE_KG` and has no lifespan.

- [ ] **Step 3: Update `src/jurist/api/app.py`**

Replace the contents of `src/jurist/api/app.py` with:

```python
"""FastAPI app: POST /api/ask + GET /api/stream (SSE) + GET /api/kg."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import settings
from jurist.kg.interface import KnowledgeGraph
from jurist.kg.networkx_kg import NetworkXKG

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.kg = NetworkXKG.load_from_json(settings.kg_path)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"KG not found at {settings.kg_path}. "
            f"Run: uv run python -m jurist.ingest.statutes"
        ) from e
    logger.info(
        "Loaded KG: %d nodes, %d edges from %s",
        len(app.state.kg.all_nodes()),
        len(app.state.kg.all_edges()),
        settings.kg_path,
    )
    yield


app = FastAPI(title="Jurist", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question_id: str


_runs: dict[str, EventBuffer] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    question_id = f"run_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=settings.max_history_per_run)
    _runs[question_id] = buf
    task = asyncio.create_task(run_question(req.question, question_id, buf))
    _tasks[question_id] = task
    return AskResponse(question_id=question_id)


@app.get("/api/stream")
async def stream(question_id: str):
    buf = _runs.get(question_id)
    if buf is None:
        raise HTTPException(status_code=404, detail="unknown question_id")

    async def gen():
        async for ev in buf.subscribe():
            yield {"data": ev.model_dump_json()}

    return EventSourceResponse(gen())


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/kg")
async def kg(request: Request) -> dict:
    g: KnowledgeGraph = request.app.state.kg
    return {
        "nodes": [n.model_dump() for n in g.all_nodes()],
        "edges": [e.model_dump() for e in g.all_edges()],
    }
```

Key changes vs. M0:
- Removed `from jurist.fakes import FAKE_KG`.
- Added `lifespan` context manager that loads `NetworkXKG` and hard-fails on missing file.
- `FastAPI(...)` now takes `lifespan=lifespan`.
- `/api/kg` reads `request.app.state.kg` instead of `FAKE_KG`.

- [ ] **Step 4: Run the new API tests**

Run: `uv run pytest tests/api/test_kg_endpoint.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the full test suite — verify M0 tests still pass**

Run: `uv run pytest -v`
Expected: all tests PASS (new M1 tests + unchanged M0 tests). If `tests/api/test_endpoints.py` (M0) fails because TestClient now hard-fails at startup on missing KG — update that test to provide a stub KG via the same `monkeypatch.setattr("jurist.api.app.settings.kg_path", ...)` pattern used in the new tests, pointing at a minimal fixture JSON. The M0 orchestrator / SSE tests don't touch `/api/kg`, but the TestClient lifespan runs regardless, so the monkeypatch is required.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/api/app.py tests/api/test_kg_endpoint.py tests/api/test_endpoints.py
git commit -m "feat: api.app — lifespan-load KG; /api/kg reads real graph"
```

(If you didn't end up touching `tests/api/test_endpoints.py` because it already passes, drop it from `git add`.)

---

### Task 16: Frontend KGPanel tweaks

**Files:**
- Modify: `web/src/components/KGPanel.tsx`

- [ ] **Step 1: Read the current file**

Read `web/src/components/KGPanel.tsx` in full (~106 lines). Identify the `layout` function's `setGraph` call, the `stateStyle` constants, and the default-case node style.

- [ ] **Step 2: Bump dagre spacing**

In `layout()`, change:

```ts
g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 60 });
```

to:

```ts
g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90 });
```

- [ ] **Step 3: Add BWB color palette + helper**

Near the top of the file (after the existing type declarations, before `layout`), add:

```ts
const BWB_COLORS: Record<string, string> = {
  'BWBR0005290': '#1e40af',  // Boek 7 — blue
  'BWBR0002888': '#be185d',  // Uhw — pink
  'BWBR0003402': '#047857',  // Besluit — green
};

function bwbBorder(articleId: string): string {
  return BWB_COLORS[articleId.split('/')[0]] ?? '#6b7280';
}
```

- [ ] **Step 4: Inject BWB tint and tooltip into node data**

In `layout()`, change the node-mapping block to preserve `title` and emit a BWB-tinted default border:

```ts
const rfNodes: Node[] = nodes.map((n) => {
  const pos = g.node(n.article_id);
  return {
    id: n.article_id,
    position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
    data: { label: n.label, title: n.title },
    type: 'default',
    style: {
      width: NODE_W,
      height: NODE_H,
      padding: 8,
      fontSize: 12,
      border: `1px solid ${bwbBorder(n.article_id)}`,
      background: '#fff',
    },
  };
});
```

- [ ] **Step 5: Apply state-driven style only when not in default**

In the component body, update the `rfNodes` memo so `stateStyle[st]` *overrides* the BWB-tinted default but leaves it in place when `st === 'default'`:

```tsx
const rfNodes = useMemo(() => {
  if (!base) return [];
  return base.nodes.map((n) => {
    const st = kgState.get(n.id) ?? 'default';
    const baseStyle = n.style as Record<string, unknown>;
    const stateOverride = st === 'default' ? {} : stateStyle[st];
    return {
      ...n,
      style: { ...baseStyle, ...stateOverride, transition: 'all 300ms' },
    };
  });
}, [base, kgState]);
```

- [ ] **Step 6: Add hover tooltip via a custom node renderer**

React Flow's `type: 'default'` doesn't expose a `title` attribute on the node DOM. Two options:
- (a) Render `title` inside `data.label` as a composed JSX element (simpler, renders in every node)
- (b) Register a custom node type (cleaner separation)

For option (b) — which stays closer to spec §8's "minimal tweaks" — add a tiny custom node before the component:

```tsx
import { Handle, Position } from '@xyflow/react';

const BWBNode = ({ data }: { data: { label: string; title: string } }) => (
  <div title={data.title} style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
    <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
    <span style={{ fontSize: 12, textAlign: 'center' }}>{data.label}</span>
    <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
  </div>
);

const nodeTypes = { bwb: BWBNode };
```

Then change `type: 'default'` → `type: 'bwb'` in the node mapping, and pass `nodeTypes={nodeTypes}` to `<ReactFlow>`.

- [ ] **Step 7: Add the inline legend**

Inside the component's returned JSX, wrap `<ReactFlow>` in a container `<div className="h-full w-full border rounded relative">` and add before `<ReactFlow>`:

```tsx
<div className="absolute top-2 right-2 z-10 bg-white/90 border rounded px-2 py-1 text-xs space-y-0.5">
  {Object.entries(BWB_COLORS).map(([bwb, color]) => {
    const label = bwb === 'BWBR0005290' ? 'Boek 7' : bwb === 'BWBR0002888' ? 'Uhw' : 'Besluit';
    return (
      <div key={bwb} className="flex items-center gap-1.5">
        <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
        <span>{label}</span>
      </div>
    );
  })}
</div>
```

- [ ] **Step 8: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. If there are, fix them inline (most likely imports or minor type mismatches).

- [ ] **Step 9: Visual sanity check — start dev servers and look**

Start backend in one terminal:
```bash
uv run python -m jurist.api
```
Start frontend in another:
```bash
cd web && npm run dev
```
Open `http://localhost:5173`. Expected: the KGPanel shows real BWB nodes with blue/pink/green borders grouping by source; hover on a node shows a native tooltip with the article title; the legend appears top-right. If the dev server logs a KG-loading error, verify the ingest step (Task 18) has run.

This is a manual check — there's no automated browser test in M1 scope.

- [ ] **Step 10: Commit**

```bash
git add web/src/components/KGPanel.tsx
git commit -m "feat: KGPanel — BWB border tint, hover tooltip, inline legend, wider dagre spacing"
```

---

### Task 17: Wire `data/` into `.gitignore` (if not already)

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check current gitignore**

Run: `grep -n '^data' .gitignore || echo "MISSING"`

If `data/` is already listed, skip to Step 3.

- [ ] **Step 2: Add data/ to gitignore**

If missing, append:

```
# M1 ingest output (built locally via `python -m jurist.ingest.statutes`)
data/
```

- [ ] **Step 3: Verify no data/ files are staged**

Run: `git status --short`
Expected: no `data/...` entries in the untracked/modified list. If any are tracked, `git rm --cached <file>` to untrack, then commit.

- [ ] **Step 4: Commit (only if .gitignore changed)**

```bash
git add .gitignore
git commit -m "chore: gitignore M1 ingest output (data/)"
```

---

### Task 18: Acceptance — real ingest + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md`

This task verifies the spec §11.M1 acceptance criteria (≥50 nodes, ≥50 edges from real BWB XML) and updates the project documentation.

- [ ] **Step 1: Run the full ingest against live BWB XML**

Run:
```bash
uv run python -m jurist.ingest.statutes --refresh -v
```

Expected: terminal summary like `Ingest complete: 73 articles, 112 edges from 3 sources (...) in 3.4 s`. Exact numbers will vary — the acceptance criterion is **≥50 articles and ≥50 edges**.

If the summary shows fewer than 50 articles or 50 edges:
- Verify the BW7 Titel 4 filter is actually including articles. Spot-check: `uv run python -c "import json; d=json.load(open('data/kg/huurrecht.json', encoding='utf-8')); print(len(d['nodes']), len(d['edges']))"`.
- Inspect the count by BWB: `uv run python -c "import json,collections; d=json.load(open('data/kg/huurrecht.json', encoding='utf-8')); print(collections.Counter(n['bwb_id'] for n in d['nodes']))"`.
- If BW7 Titel 4 shows fewer than expected (~80 articles), the Titel-filter logic may be excluding too much — inspect `_passes_titel_filter` in parser.py.

If the upstream endpoint returns HTML instead of XML or 404s:
- Update `BWB_XML_URL_TEMPLATE` in `src/jurist/ingest/fetch.py`. Candidates from spec §5.1: the KOOP FRBR repository URL, or a newer wetten.overheid.nl pattern.
- As a last resort, manually download each BWB's XML via browser and drop into `data/cache/bwb/{bwb_id}.xml`; then re-run with `--no-fetch`.

- [ ] **Step 2: Start the API and verify the frontend renders the real KG**

Start backend + frontend as in Task 16.9. Open `http://localhost:5173` and confirm:
- KGPanel renders ≥50 nodes with BWB tints grouping by source.
- The ask flow still runs through M0 fakes without error. Node animations may light up known FAKE_VISIT_PATH IDs — if any of those IDs are missing from the real KG, the drift-catch test in Task 14 already flagged it.

- [ ] **Step 3: Update CLAUDE.md fake-vs-real table**

In `CLAUDE.md`, find the "fake vs. real" table (near the bottom of the "Architecture" section). Change the `/api/kg` row:

| From | To |
| --- | --- |
| `` \| `/api/kg` \| Serves `FAKE_KG` from memory \| M1 (loads `data/kg/huurrecht.json` from BWB XML ingestion) \| `` | `` \| `/api/kg` \| Real — loads `data/kg/huurrecht.json` at startup (built by `jurist.ingest.statutes`) \| — \| `` |

- [ ] **Step 4: Update CLAUDE.md Commands section**

In `CLAUDE.md`, under "Backend (Python 3.11, `uv`)", add a line before "Start API server":

```
- Build KG (prerequisite for API start): `uv run python -m jurist.ingest.statutes --refresh -v`
```

Also add a one-liner under the heading that explains the prerequisite: "The API hard-fails at startup if `data/kg/huurrecht.json` is missing — run the ingest step first on a fresh clone."

- [ ] **Step 5: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — M1 flips /api/kg to real; adds ingest as prerequisite"
```

- [ ] **Step 7: Tag the milestone**

Run:
```bash
git tag -a m1-statute-ingestion -m "M1 complete — real huurrecht KG from BWB XML"
```

This matches the `m0-skeleton` tag convention.

---

## Summary

After all 18 tasks are committed:
- `data/kg/huurrecht.json` builds from real BWB XML via `uv run python -m jurist.ingest.statutes`.
- FastAPI loads the KG at startup and hard-fails with a clear message if missing.
- `/api/kg` serves real nodes and edges; KGPanel renders them with dagre + BWB tints + legend.
- M0 fakes continue to drive the run; the drift-catch test asserts FAKE paths still resolve in the real KG.
- Spec §11.M1 success criteria verified on real data (≥50 nodes, ≥50 edges, `art. 7:248 BW` parseable).

Ready to brainstorm M2 (real statute retriever with Claude tool-use loop) whenever M1 is tagged.
