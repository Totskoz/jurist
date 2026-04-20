# Jurist v1 — M1 Implementation Plan (Statute ingestion + KG viewer)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/api/kg` fake with a real huurrecht KG built from BWB XML via a new `python -m jurist.ingest.statutes` CLI; load the KG at FastAPI startup and render real nodes in the existing KGPanel.

**Architecture:** A new `src/jurist/ingest/` package fetches BWB XML (cached locally, live-fetch on miss), parses articles with `lxml` using a schema-conformant ancestor-chain walk, extracts cross-references from explicit `<intref>`/`<extref>` elements (preferred) and a same-BWB regex fallback, and writes `data/kg/huurrecht.json` + per-article markdown dumps. A new `src/jurist/kg/` package exposes a minimal `KnowledgeGraph` Protocol backed by NetworkX; `src/jurist/api/app.py` loads the KG at startup via `lifespan` and hard-fails on missing file. `fakes.py` stays intact — the fake agents still drive the run; only the KG source changes.

**Tech Stack:** Python 3.11+, uv, FastAPI (lifespan), Pydantic 2, `lxml`, `httpx`, `networkx`, pytest, pytest-asyncio. Frontend: Vite + React + TypeScript (KGPanel tweaks only — no new components).

**Scope note:** This plan covers **M1 only** per the design spec. M1 ships the 2 core BWBs (BW7 Titel 4, Uhw). The Besluit huurprijzen woonruimte and the widened ~8-BWB corpus are deferred to **M1.5**, which requires no parser code changes.

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
| `tests/ingest/fixtures/BWBR0014315_excerpt.xml` | Real Uhw excerpt (incl. art. 3, 10, 16). |
| `tests/ingest/test_parser.py` | Parser behavior — inline mini-XML + fixture-based `test_parses_art_7_248_bw`. |
| `tests/ingest/test_xrefs.py` | Regex pass + dedup merge, table-driven. |
| `tests/ingest/test_idempotency.py` | `source_versions` short-circuit; `--refresh` bypass. |
| `tests/kg/__init__.py` | Package marker. |
| `tests/kg/test_networkx_kg.py` | JSON roundtrip; `get_node`; dup detection. |
| `tests/api/test_kg_endpoint.py` | `/api/kg` shape with tmp-dir KG; hard-fail on missing file. |
| `tests/integration/__init__.py` | Package marker. |
| `tests/integration/test_ingest_end_to_end.py` | Full pipeline on 2 fixture XMLs. |
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
"""Single scope knob for ingestion. M1 ships 2 core BWBs; M1.5 widens."""
from __future__ import annotations

from dataclasses import dataclass


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
    "BWBR0014315": BWBEntry(
        name="Uitvoeringswet huurprijzen woonruimte",
        label_prefix="Uhw",
    ),
}
```

- [ ] **Step 3: Smoke-import and spot-check**

Run: `uv run python -c "from jurist.ingest.allowlist import BWB_ALLOWLIST; print(len(BWB_ALLOWLIST), list(BWB_ALLOWLIST))"`
Expected: `2 ['BWBR0005290', 'BWBR0014315']`.

- [ ] **Step 4: Commit**

```bash
git add src/jurist/ingest/__init__.py src/jurist/ingest/allowlist.py
git commit -m "feat: ingest.allowlist — 2 core BWBs with filter_titel"
```

---

### Task 7: Fetcher with cache + live fallback

**Files:**
- Create: `src/jurist/ingest/fetch.py`
- Create: `tests/ingest/__init__.py`
- Create: `tests/ingest/test_fetch.py`

The fetcher returns BWB XML bytes. The cache layer avoids repeated network hits. `--no-fetch` mode is cache-only.

The fetcher uses a 2-step KOOP repository lookup — see spec §5.1. The manifest URL `https://repository.officiele-overheidspublicaties.nl/bwb/{bwb_id}/manifest.xml` returns the latest-version path via the `_latestItem` attribute, which is then fetched as the versioned XML. Tests mock both HTTP calls, so the live URLs are not exercised in CI.

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

    manifest_resp = MagicMock()
    manifest_resp.text = '<work _latestItem="some/path.xml">'
    manifest_resp.raise_for_status.return_value = None

    xml_resp = MagicMock()
    xml_resp.content = b"<wet>fresh</wet>"
    xml_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.side_effect = [manifest_resp, xml_resp]

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0014315")

    assert result == b"<wet>fresh</wet>"
    assert (tmp_path / "BWBR0014315.xml").read_bytes() == b"<wet>fresh</wet>"


def test_fetch_refresh_bypasses_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    (tmp_path / "BWBR0014315.xml").write_bytes(b"<wet>old</wet>")

    manifest_resp = MagicMock()
    manifest_resp.text = '<work _latestItem="some/path.xml">'
    manifest_resp.raise_for_status.return_value = None

    xml_resp = MagicMock()
    xml_resp.content = b"<wet>new</wet>"
    xml_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.side_effect = [manifest_resp, xml_resp]

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0014315", refresh=True)

    assert result == b"<wet>new</wet>"


def test_fetch_no_fetch_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="cache miss"):
        fetch_bwb_xml("BWBR0009999", no_fetch=True)


def test_fetch_raises_on_manifest_missing_latest_item(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)

    manifest_resp = MagicMock()
    manifest_resp.text = "<work>no attr here</work>"
    manifest_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = manifest_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        with pytest.raises(ValueError, match="manifest missing _latestItem"):
            fetch_bwb_xml("BWBR0014315")
```

- [ ] **Step 3: Run and see them fail**

Run: `uv run pytest tests/ingest/test_fetch.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_bwb_xml'`.

- [ ] **Step 4: Implement the fetcher**

Create `src/jurist/ingest/fetch.py`:

```python
"""BWB XML fetcher — cache-first with live KOOP repository fallback."""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from jurist.config import settings

BWB_REPO_BASE = "https://repository.officiele-overheidspublicaties.nl/bwb"
CACHE_DIR: Path = settings.data_dir / "cache" / "bwb"


def fetch_bwb_xml(bwb_id: str, *, refresh: bool = False, no_fetch: bool = False) -> bytes:
    """Return latest BWB XML bytes for ``bwb_id`` from KOOP repository.

    Order of operations:
      1. If cache hit and not ``refresh``, return cached bytes.
      2. If ``no_fetch``, raise FileNotFoundError on cache miss.
      3. Otherwise GET the manifest, extract ``_latestItem``, GET that XML,
         atomically write to cache, return bytes.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = Path(bwb_id).name
    cache_path = CACHE_DIR / f"{safe_id}.xml"

    if cache_path.exists() and not refresh:
        return cache_path.read_bytes()

    if no_fetch:
        raise FileNotFoundError(f"cache miss for {bwb_id} and --no-fetch is set")

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        manifest_url = f"{BWB_REPO_BASE}/{bwb_id}/manifest.xml"
        m_resp = client.get(manifest_url)
        m_resp.raise_for_status()
        latest_item = _parse_latest_item(m_resp.text)

        xml_url = f"{BWB_REPO_BASE}/{bwb_id}/{latest_item}"
        x_resp = client.get(xml_url)
        x_resp.raise_for_status()
        data = x_resp.content

    tmp_path = cache_path.with_suffix(".tmp")
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(cache_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return data


_LATEST_ITEM_RE = re.compile(r'_latestItem="([^"]+)"')


def _parse_latest_item(manifest_xml: str) -> str:
    """Extract the _latestItem attribute from a BWB manifest root element."""
    m = _LATEST_ITEM_RE.search(manifest_xml)
    if not m:
        raise ValueError("BWB manifest missing _latestItem attribute")
    return m.group(1)
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
- Create: `tests/ingest/fixtures/BWBR0014315_excerpt.xml`

- [ ] **Step 1: Create the fixtures directory**

Run: `mkdir -p tests/ingest/fixtures`

- [ ] **Step 2: Fetch the full XMLs into the cache**

Run:
```bash
uv run python -c "
from jurist.ingest.fetch import fetch_bwb_xml
for bwb in ['BWBR0005290', 'BWBR0014315']:
    data = fetch_bwb_xml(bwb, refresh=True)
    print(bwb, len(data), 'bytes')
"
```

Expected: two lines with byte counts (BW7 ~4.4 MB, Uhw ~430 KB). If any line shows an HTML 404 or connection error, the upstream KOOP endpoint may have changed — check spec §5.1 for the manifest-then-latest URL structure and verify `BWB_REPO_BASE` in `fetch.py`. As a last resort, manually download via browser from `https://wetten.overheid.nl/BWBR0005290` and drop into `data/cache/bwb/`.

- [ ] **Step 3: Trim each cached XML to an excerpt**

Open `data/cache/bwb/BWBR0005290.xml` in an editor. Keep the document root + wrapper elements (wet/intref-metadata) and the `<boek nr="7">` → `<titel nr="4">` → `<afdeling nr="5">` → articles. Specifically preserve articles 246 through 265 (plus any needed wrapping afdelingen in Titel 4). Remove Titels 1-3, 5+, and Afdelingen outside of Titel 4. Save to `tests/ingest/fixtures/BWBR0005290_excerpt.xml`. Aim for ≤100 KB.

For `BWBR0014315.xml` (Uhw): keep at least articles 3, 10, and 16 plus minimal wrapping (these are cross-referenced by BW7). Save to `tests/ingest/fixtures/BWBR0014315_excerpt.xml`.

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

Expected: two lines; BWBR0005290 excerpt shows ≥15 articles, BWBR0014315 shows ≥3.

- [ ] **Step 5: Confirm file sizes**

Run: `ls -la tests/ingest/fixtures/`
Expected: each file ≤100 KB.

- [ ] **Step 6: Commit**

```bash
git add tests/ingest/fixtures/
git commit -m "test: add BWB XML fixture excerpts (BW7 Titel 4, Uhw)"
```

---

### Task 9: Parser — walk, article_id, label

**Files:**
- Create: `src/jurist/ingest/parser.py`
- Create: `tests/ingest/test_parser.py`

> **Schema reality (confirmed from committed fixture XMLs):**
> Article identity lives in `bwb-ng-variabel-deel` attributes on each `<artikel>` element, not in `<nr>` child text or ancestor `nr` attributes. Container elements are `<boek>`, `<titeldeel>` (NOT `<titel>`), `<afdeling>`, `<paragraaf>`, `<sub-paragraaf>`, `<hoofdstuk>`. Explicit cross-references come from `<intref>` and `<extref>` elements, both carrying `bwb-id` and `bwb-ng-variabel-deel` attributes that give the resolved target directly — no sentinel stage needed.

- [ ] **Step 1: Write failing tests**

Create `tests/ingest/test_parser.py`:

```python
from pathlib import Path

from jurist.ingest.allowlist import BWB_ALLOWLIST, BWBEntry
from jurist.ingest.parser import parse_bwb_xml


def _bw7_entry() -> BWBEntry:
    return BWB_ALLOWLIST["BWBR0005290"]


# ---------------------------------------------------------------------------
# Fixture-based tests (real BWB XML excerpt)
# ---------------------------------------------------------------------------

def test_parses_art_7_248_from_fixture():
    """art. 7:248 BW: article_id, label, body text, outgoing_refs all correct."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())

    a248 = next(
        (n for n in nodes
         if n.article_id == "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248"),
        None,
    )
    assert a248 is not None, "art. 7:248 BW not found"
    assert a248.label == "Boek 7, Artikel 248"
    assert "huurprijs" in a248.body_text.lower()
    # 248 lid 1 carries an <intref> to art. 252
    assert any("Artikel252" in ref for ref in a248.outgoing_refs), (
        f"expected ref to Artikel252 in {a248.outgoing_refs}"
    )


def test_intref_edge_extracted_with_bwb_and_path():
    """Edge from 248 → 252 appears in explicit edges list."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, edges = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())

    from_248 = [
        e for e in edges
        if e.from_id.endswith("/Artikel248") and "Artikel252" in e.to_id
    ]
    assert len(from_248) >= 1, "expected intref edge 248→252"
    assert from_248[0].kind == "explicit"
    assert from_248[0].to_id.startswith("BWBR0005290/")


def test_extref_edge_to_other_bwb():
    """art. 248 lid 2 contains an <extref> to Uhw artikel 10 (BWBR0014315)."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, edges = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())

    cross = [
        e for e in edges
        if e.from_id.endswith("/Artikel248") and e.to_id.startswith("BWBR0014315/")
    ]
    assert len(cross) >= 1, "expected extref edge 248→BWBR0014315/..."


def test_filter_titel_applies_only_matching_titeldeel():
    """A filter_titel that matches no Titeldeel in the fixture yields 0 nodes."""
    from jurist.ingest.allowlist import BWBEntry
    fake_entry = BWBEntry(name="test", label_prefix="X", filter_titel=("99",))
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", fake_entry)
    assert nodes == [], f"expected 0 nodes for filter_titel=('99',), got {len(nodes)}"


def test_uhw_parses_with_no_filter():
    """Uhw fixture with no filter_titel yields ≥3 articles incl. Artikel3."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0014315_excerpt.xml"
    nodes, _ = parse_bwb_xml(
        fixture.read_bytes(), "BWBR0014315", BWB_ALLOWLIST["BWBR0014315"]
    )
    assert len(nodes) >= 3, f"expected ≥3 Uhw articles, got {len(nodes)}"
    ids = {n.article_id for n in nodes}
    assert any(aid.endswith("/Artikel3") for aid in ids), (
        f"Artikel3 not found in {ids}"
    )


def test_article_title_inherits_nearest_container_titel():
    """art. 248 sits inside sub-paragraaf 'Huurprijzen'; that title is inherited."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())

    a248 = next(
        (n for n in nodes if n.article_id.endswith("/Artikel248")), None
    )
    assert a248 is not None
    assert a248.title, "expected non-empty title for art. 248"
    # Nearest ancestor with a <kop><titel> is Sub-paragraaf1: "Huurprijzen"
    assert a248.title == "Huurprijzen", f"expected 'Huurprijzen', got '{a248.title}'"
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/ingest/test_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_bwb_xml'`.

- [ ] **Step 3: Implement the parser**

Create `src/jurist/ingest/parser.py`:

```python
"""BWB XML parser — real schema (bwb-ng-variabel-deel attribute edition).

Key schema facts confirmed from fixture XMLs:
- Article identity: `bwb-ng-variabel-deel` attribute on each <artikel> element.
  e.g. "/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248"
- Container elements: <boek>, <titeldeel>, <afdeling>, <paragraaf>, <sub-paragraaf>,
  <hoofdstuk> — NOT <titel>.
- Explicit refs: <intref> and <extref> both carry `bwb-id` + `bwb-ng-variabel-deel`
  giving the resolved target directly. No sentinel stage needed.
- Article title: inherit from nearest ancestor with <kop><titel> text; else use
  the `label` attribute value (e.g. "Artikel 248").
- filter_titel for BWBR0005290: check that the path contains "/Titeldeel{N}/" for N
  in the allowed set.
"""
from __future__ import annotations

from lxml import etree

from jurist.ingest.allowlist import BWBEntry
from jurist.schemas import ArticleEdge, ArticleNode


def parse_bwb_xml(
    xml_bytes: bytes, bwb_id: str, entry: BWBEntry
) -> tuple[list[ArticleNode], list[ArticleEdge]]:
    """Return (nodes, explicit_edges) from a single BWB XML document.

    Applies ``entry.filter_titel`` (checks bwb-ng-variabel-deel path).
    Skips ``status="goed"``-only articles — actually skips articles without
    a valid ``bwb-ng-variabel-deel`` attribute.
    Explicit edges resolved directly from <intref>/<extref> attribute pairs.
    """
    root = etree.fromstring(xml_bytes)
    nodes: list[ArticleNode] = []
    edges: list[ArticleEdge] = []

    for art in root.iter("artikel"):
        path = art.get("bwb-ng-variabel-deel", "")
        if not path:
            continue

        # Titel filter: require "/Titeldeel{N}/" segment in path
        if entry.filter_titel is not None:
            if not any(f"/Titeldeel{t}/" in path for t in entry.filter_titel):
                continue

        article_id = f"{bwb_id}{path}"
        raw_label = art.get("label", "")  # e.g. "Artikel 248"
        label = f"{entry.label_prefix}, {raw_label}" if raw_label else entry.label_prefix
        title = _nearest_container_title(art) or raw_label
        body_text = _extract_body_text(art)

        outgoing_ids: list[str] = []
        for ref in art.iter("intref"):
            tid = _ref_to_article_id(ref)
            if tid is not None:
                outgoing_ids.append(tid)
                edges.append(ArticleEdge(from_id=article_id, to_id=tid, kind="explicit", context=None))
        for ref in art.iter("extref"):
            tid = _ref_to_article_id(ref)
            if tid is not None:
                outgoing_ids.append(tid)
                edges.append(ArticleEdge(from_id=article_id, to_id=tid, kind="explicit", context=None))

        nodes.append(ArticleNode(
            article_id=article_id,
            bwb_id=bwb_id,
            label=label,
            title=title,
            body_text=body_text,
            outgoing_refs=outgoing_ids,
        ))

    return nodes, edges


def _ref_to_article_id(ref: etree._Element) -> str | None:
    """Extract article_id from an <intref> or <extref> element.

    Both element types carry ``bwb-id`` and ``bwb-ng-variabel-deel`` attributes.
    If either is missing (coarse BWB-level refs without article path), return None
    and the caller drops the edge.
    """
    bwb = ref.get("bwb-id")
    path = ref.get("bwb-ng-variabel-deel")
    if not bwb or not path:
        return None
    return f"{bwb}{path}"


def _extract_body_text(art: etree._Element) -> str:
    """Concatenate all <al> descendant text; collapse whitespace; join with space."""
    parts: list[str] = []
    for al in art.iter("al"):
        text = " ".join(al.itertext())
        text = " ".join(text.split())
        if text:
            parts.append(text)
    return " ".join(parts)


def _nearest_container_title(art: etree._Element) -> str:
    """Walk up from the article; return the first ancestor's <kop><titel> text."""
    for anc in art.iterancestors():
        if anc.tag == "artikel":
            continue
        kop = anc.find("kop")
        if kop is not None:
            t = kop.find("titel")
            if t is not None and t.text and t.text.strip():
                return t.text.strip()
    return ""
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ingest/test_parser.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/ingest/parser.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/ingest/parser.py tests/ingest/test_parser.py
git commit -m "feat: ingest.parser — parse BWB XML into ArticleNode+ArticleEdge"
```

---

### Task 10: Xrefs — regex fallback pass + dedup

**Files:**
- Create: `src/jurist/ingest/xrefs.py`
- Create: `tests/ingest/test_xrefs.py`

> **Schema reality:** `<intref>` and `<extref>` elements carry fully resolved `bwb-id + bwb-ng-variabel-deel` attributes. The parser (`Task 9`) extracts these into real `article_id` values directly — no sentinel stage is needed. This task's scope is therefore:
> 1. Regex fallback pass for same-BWB mentions not covered by explicit elements.
> 2. Merge (dedup) explicit + regex edges, explicit wins.

- [ ] **Step 1: Write failing tests**

Create `tests/ingest/test_xrefs.py`:

```python
from jurist.schemas import ArticleEdge, ArticleNode
from jurist.ingest.xrefs import extract_regex_edges, merge_edges


def _node(article_id: str, bwb: str, body: str = "") -> ArticleNode:
    return ArticleNode(
        article_id=article_id,
        bwb_id=bwb,
        label=article_id.rsplit("/", 1)[-1],
        title="",
        body_text=body,
        outgoing_refs=[],
    )


def test_regex_finds_same_bwb_reference():
    """body "zie artikel 249" → regex edge 248→249, kind="regex"."""
    n248 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",
        "BWBR0005290",
        "zie artikel 249",
    )
    n249 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel249",
        "BWBR0005290",
    )
    edges = extract_regex_edges([n248, n249])
    assert len(edges) == 1
    assert edges[0].from_id == n248.article_id
    assert edges[0].to_id == n249.article_id
    assert edges[0].kind == "regex"


def test_regex_ignores_cross_bwb_mentions():
    """Free-text mention of "artikel 10" when Uhw articles are not in same nodes list → no edge."""
    n248 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",
        "BWBR0005290",
        "artikel 10 van de Uitvoeringswet huurprijzen woonruimte",
    )
    # Uhw Artikel10 not in the nodes list passed to extract_regex_edges
    edges = extract_regex_edges([n248])
    assert edges == [], "cross-BWB text mention must not produce a regex edge"


def test_merge_dedupe_explicit_wins():
    """Same (from, to) pair in both lists → one edge, kind='explicit'."""
    a = "BWBR0005290/.../Artikel248"
    b = "BWBR0005290/.../Artikel252"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex    = [ArticleEdge(from_id=a, to_id=b, kind="regex")]
    merged = merge_edges(explicit, regex)
    assert len(merged) == 1
    assert merged[0].kind == "explicit"


def test_merge_keeps_distinct_pairs():
    """explicit (A→B) + regex (A→C) + regex (A→B duplicate) → 2 edges."""
    a = "BWBR0005290/.../Artikel248"
    b = "BWBR0005290/.../Artikel252"
    c = "BWBR0005290/.../Artikel253"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex    = [
        ArticleEdge(from_id=a, to_id=c, kind="regex"),
        ArticleEdge(from_id=a, to_id=b, kind="regex"),  # duplicate of explicit pair
    ]
    merged = merge_edges(explicit, regex)
    assert len(merged) == 2
    by_target = {e.to_id: e.kind for e in merged}
    assert by_target[b] == "explicit"
    assert by_target[c] == "regex"
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/ingest/test_xrefs.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_regex_edges'`.

- [ ] **Step 3: Implement `xrefs.py`**

Create `src/jurist/ingest/xrefs.py`:

```python
"""Cross-reference extraction: regex fallback pass + dedup merge.

See spec §5.3. Explicit edges from <intref>/<extref> are already fully resolved
by the parser (Task 9) — no sentinel resolution step needed.

This module:
  1. extract_regex_edges — same-BWB leading-number regex scan over body_text.
  2. merge_edges — dedup by (from_id, to_id); explicit wins over regex.
"""
from __future__ import annotations

import re

from jurist.schemas import ArticleEdge, ArticleNode

# Matches "artikel 248", "artikelen 249", "artikel 248a", optionally followed
# by ordinal "... lid" (lid ignored — edges are article-level).
# Word-boundary before "artikel" guards against mid-sentence number matches.
_ARTIKEL_RE = re.compile(r"\bartikel(?:en)?\s+(\d+[a-z]?)", re.IGNORECASE)


def extract_regex_edges(nodes: list[ArticleNode]) -> list[ArticleEdge]:
    """Scan each node's body_text for article references; emit same-BWB edges.

    Resolution strategy: look up "Artikel{N}" suffix within the same bwb_id.
    Ambiguous (multiple candidates) or missing targets → drop silently.
    Cross-BWB text mentions cannot be resolved — dropped too (use explicit edges
    from <extref> for cross-BWB coverage).
    """
    # Build per-BWB map: "Artikel{N}" → article_id (unique within BWB or ambiguous)
    by_bwb: dict[str, dict[str, str]] = {}
    for n in nodes:
        # label ends with e.g. "Artikel 248" → normalize to "Artikel248"
        # But more reliably: use the last path segment of article_id
        suffix = n.article_id.rsplit("/", 1)[-1]  # e.g. "Artikel248"
        by_bwb.setdefault(n.bwb_id, {})[suffix] = n.article_id  # last write wins on dup

    edges: list[ArticleEdge] = []
    seen: set[tuple[str, str]] = set()
    for n in nodes:
        for m in _ARTIKEL_RE.finditer(n.body_text):
            target_suffix = f"Artikel{m.group(1)}"
            target_id = by_bwb.get(n.bwb_id, {}).get(target_suffix)
            if target_id is None or target_id == n.article_id:
                continue
            key = (n.article_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(ArticleEdge(from_id=n.article_id, to_id=target_id, kind="regex", context=None))
    return edges


def merge_edges(
    explicit: list[ArticleEdge], regex: list[ArticleEdge]
) -> list[ArticleEdge]:
    """Dedup by ``(from_id, to_id)``; explicit wins over regex."""
    seen: dict[tuple[str, str], ArticleEdge] = {}
    for e in explicit:
        seen[(e.from_id, e.to_id)] = e  # explicit always wins
    for e in regex:
        seen.setdefault((e.from_id, e.to_id), e)
    return list(seen.values())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ingest/test_xrefs.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Ruff**

```bash
uv run ruff check src/jurist/ingest/xrefs.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/ingest/xrefs.py tests/ingest/test_xrefs.py
git commit -m "feat: ingest.xrefs — regex fallback + merge (explicit wins)"
```

---

### Task 11: Statutes orchestrator

**Files:**
- Create: `src/jurist/ingest/statutes.py`
- Create: `tests/ingest/test_idempotency.py`

The orchestrator:
1. Reads the version stamp from each fetched BWB XML.
2. Short-circuits if all match the existing `source_versions` in `huurrecht.json` and not `--refresh`.
3. Otherwise parses each BWB, collects nodes + explicit edges (already fully resolved — no sentinels).
4. Runs `extract_regex_edges` over the union of all nodes.
5. Merges explicit + regex edges (dedup; explicit wins).
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
        {"BWBR0014315": BWBEntry(name="Test", label_prefix="Test")},
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
    assert snap_before["source_versions"]["BWBR0014315"] == "2024-01-01"

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V2):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    snap_after = json.loads(out.read_text(encoding="utf-8"))
    assert snap_after["source_versions"]["BWBR0014315"] == "2025-06-01"
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
  3. Parse → (nodes, explicit_edges).  # edges already resolved; no sentinel stage
  4. Collect across BWBs; run regex pass over union.
  5. Merge explicit + regex (dedup, explicit wins).
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
    # all_explicit already carries resolved article_ids (no sentinel stage needed)
    regex_edges = extract_regex_edges(all_nodes)
    merged = merge_edges(all_explicit, regex_edges)

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
  'BWBR0014315': '#be185d',  // Uhw — pink
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
    const label = bwb === 'BWBR0005290' ? 'Boek 7' : 'Uhw';
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

Expected: terminal summary like `Ingest complete: 73 articles, 112 edges from 2 sources (...) in 3.4 s`. Exact numbers will vary — the acceptance criterion is **≥50 articles and ≥50 edges**.

If the summary shows fewer than 50 articles or 50 edges:
- Verify the BW7 Titel 4 filter is actually including articles. Spot-check: `uv run python -c "import json; d=json.load(open('data/kg/huurrecht.json', encoding='utf-8')); print(len(d['nodes']), len(d['edges']))"`.
- Inspect the count by BWB: `uv run python -c "import json,collections; d=json.load(open('data/kg/huurrecht.json', encoding='utf-8')); print(collections.Counter(n['bwb_id'] for n in d['nodes']))"`.
- If BW7 Titel 4 shows fewer than expected (~80 articles), the Titel-filter logic may be excluding too much — inspect `_passes_titel_filter` in parser.py.

If the upstream endpoint returns errors (the KOOP manifest URL at `https://repository.officiele-overheidspublicaties.nl/bwb/{bwb_id}/manifest.xml` should work without authentication):
- Verify `BWB_REPO_BASE` in `src/jurist/ingest/fetch.py` matches the spec §5.1 KOOP URL.
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
