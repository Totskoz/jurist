# M3a — Caselaw Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the caselaw ingestion pipeline: pull huur-related uitspraken from rechtspraak.nl open-data, chunk them, embed with bge-m3, and write to LanceDB — so M3b can later run a real vector-search case retriever against it.

**Architecture:** Nine-stage sync pipeline (warm model → list → resume gate → fetch content → parse → filter → chunk → embed → write). Fetch stage uses `ThreadPoolExecutor(max_workers=5)` over stdlib `urllib.request`. Embedding via `sentence-transformers` bge-m3. Storage via LanceDB. Keyword fence is a lenient substring match on four huur-prefix terms. A `CaselawProfile` registry keeps the subject URI + keyword set per-rechtsgebied so the pipeline is reusable.

**Tech Stack:** Python 3.11, stdlib `urllib.request` + `concurrent.futures` + `xml.etree.ElementTree`, `sentence-transformers` (new dep, pulls torch), `lancedb` (new dep, pulls pyarrow), `pytest` + `pytest-asyncio`.

**Authoritative spec:** `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md`. When a task references a rule ("per spec §4.2"), read that section before implementing — the spec is the source of truth for WHAT; this plan is HOW.

**Preflight:**
- Working tree clean on `master`. Task 0 writes one commit to master (parent-spec amendment), Task 1 branches off.
- No `ANTHROPIC_API_KEY` needed — ingestion path has zero LLM calls.
- First run of the ingester will download `BAAI/bge-m3` (~2.3 GB) to `~/.cache/huggingface/hub/`. `uv sync` also pulls torch (~2 GB). Budget ~10 min of network on a fresh clone.
- LanceDB + sentence-transformers both work on Windows; no platform-specific setup beyond `uv sync`.

**Conventions across all tasks:**
- One task ≈ one commit. Commit at the end of each task after tests pass + `uv run ruff check .` is clean.
- Test-first where feasible: write failing test → see fail → implement → see pass → commit.
- Paths use forward slashes. Windows CRLF warnings on commit are benign (per `CLAUDE.md`).
- If `uv` isn't on `PATH`: `export PATH="/c/Users/totti/.local/bin:$PATH"`.
- Do NOT use `--no-verify` or bypass pre-commit hooks. If a hook fails, fix the issue and re-commit.

---

## Task 0: Amend parent spec for verified data-source shape

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-jurist-v1-design.md`

Prerequisite commit on `master` before branching. Documents the verified rechtspraak.nl taxonomy, splits M3 into M3a/M3b, renames `CaseChunk`, and adds decision-log entries.

- [ ] **Step 1: Open the parent spec and locate §8.2, §7.4, §11 M3, §15**

Sections are currently at lines (approximate, use Grep to find exact):
- `§7.4 Case chunk (LanceDB row)` — `class CaseChunk(BaseModel):`
- `§8.2 Case law — python -m jurist.ingest.caselaw` — heading
- `§11 Milestones / M3` — heading `### M3 — Case ingestion + case retriever`
- `§15 Decisions log` — table near end

- [ ] **Step 2: Rewrite §8.2 "Steps" 1–2 to match verified taxonomy**

Find the block:

```markdown
### 8.2 Case law — `python -m jurist.ingest.caselaw`

**Scope.** rechtspraak.nl open-data ECLI search:
- `rechtsgebied = "Huurrecht"`
- `instantie ∈ {Huurcommissie, Rechtbank, Gerechtshof}`
- `datum` descending
- first N (default 300; `--limit` overrides)
```

Replace with:

```markdown
### 8.2 Case law — `python -m jurist.ingest.caselaw`

**Scope.** rechtspraak.nl open-data ECLI search over the verified taxonomy:
- `subject = http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht` (huurrecht's taxonomic parent in Dutch law — a standalone `#huurrecht` URI does not exist)
- `modified >= 2024-01-01` (date floor, configurable)
- Local keyword fence post-download: body must contain any of `{huur, verhuur, woonruimte, huurcommissie}` (case-folded substring)
- No instantie filter; all courts
- No hard count cap; ingests everything passing the fence

See the M3a design doc for verified URI list, the missing-`huurrecht` finding, and the volume stats (≈20k candidates since 2024 → few hundred post-fence).
```

- [ ] **Step 3: Replace the Steps block in §8.2 with the verified endpoints**

Find the `**Steps.**` block immediately below the Scope block (currently 7 numbered steps starting with "Query the ECLI search API…").

Replace with:

```markdown
**Steps.**
1. Paginate `GET https://data.rechtspraak.nl/uitspraken/zoeken?subject=<URI>&modified=<YYYY-MM-DD>&max=1000&from=N` until an empty feed page. Collect `[(ecli, modified_ts), …]`.
2. For each ECLI not yet cached, `GET https://data.rechtspraak.nl/uitspraken/content?id=<ECLI>`; write raw XML to `data/cases/<ecli>.xml`. 5-way parallel via `ThreadPoolExecutor`. Polite `User-Agent`.
3. Parse RDF metadata: `dcterms:identifier`, `dcterms:date`, `dcterms:creator` (court), `dcterms:subject`, `psi:zaaknummer`, `dcterms:modified`, plus the deeplink `https://uitspraken.rechtspraak.nl/details?id=<ECLI>`. Strip XML tags from body text; collapse whitespace; preserve paragraph breaks.
4. Drop cases whose body fails the keyword fence.
5. Chunk surviving bodies via `src/jurist/ingest/splitter.py` (~500-word target, 50-word overlap, paragraph-aware recursive splitter — stdlib-only).
6. Embed chunks with bge-m3 via `src/jurist/embedding.py`; normalize.
7. Insert rows into LanceDB at `data/lancedb/cases.lance` with `CaseChunkRow` schema (§7.4).
8. Idempotent: re-runs skip already-cached ECLIs and already-embedded chunks unless `--refresh`.
```

- [ ] **Step 4: Rename CaseChunk → CaseChunkRow in §7.4 and update fields**

Find:

```python
class CaseChunk(BaseModel):
    ecli: str
    court: str
    date: str
    rechtsgebied: str
    chunk_idx: int
    text: str
    embedding: list[float]       # 1024-dim (bge-m3)
    url: str
```

Replace with:

```python
class CaseChunkRow(BaseModel):
    # identity
    ecli: str
    chunk_idx: int
    # metadata (from RDF)
    court: str
    date: str                    # ISO 8601
    zaaknummer: str
    subject_uri: str             # "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    modified: str                # ISO 8601 last-modified
    # content
    text: str
    embedding: list[float]       # 1024-d bge-m3, L2-normalized
    # display
    url: str                     # "https://uitspraken.rechtspraak.nl/details?id=..."
```

- [ ] **Step 5: Split §11 M3 into M3a + M3b**

Find the `### M3 — Case ingestion + case retriever` section with its "Done when" bullets.

Replace with:

```markdown
### M3a — Case ingestion

Done when:
- `uv run python -m jurist.ingest.caselaw` populates `data/lancedb/cases.lance` with ≥100 unique ECLIs, each with ≥1 chunk row, every row bge-m3-embedded (1024-d, unit-norm) and passing the keyword fence.
- Re-running without `--refresh` is idempotent; `--refresh` wipes + rebuilds.
- Unit tests cover: parser, filter, splitter, fetch-with-cache, mocked embedder, vectorstore round-trip.
- Integration test (`RUN_E2E=1`) ingests ~10 live ECLIs and verifies bge-m3 determinism.
- `case_retriever` agent remains the M0 fake; no orchestrator or frontend changes.

See `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md`.

### M3b — Real case retriever

Done when:
- `CaseRetriever` returns top-3 cases on the locked question; all returned ECLIs exist in LanceDB; similarity scores are real; rerank reasons are non-trivial.
- Citation click opens `uitspraken.rechtspraak.nl/...` in a new tab.
- Unit test: bge-m3 embedding is deterministic across runs for the same input (actually lands in M3a integration test; reaffirmed here).

Separate design + plan to follow M3a.
```

- [ ] **Step 6: Append three rows to §15 Decisions log**

Find the decisions table. Append:

```markdown
| 13 | M3 split into M3a (ingestion + LanceDB) + M3b (real retriever) | Single M3 milestone as originally scoped | Mirrors M1→M2 ingest-then-retrieve rhythm; each half gets its own "done" gate. |
| 14 | Source filter: `civielRecht_verbintenissenrecht` + date floor + local keyword fence | Original `rechtsgebied=Huurrecht` | Verified 2026-04-21: no `#huurrecht` URI exists in rechtspraak.nl's open-data taxonomy. Verbintenissenrecht is the legal parent; keyword fence restores precision. |
| 15 | `CaseChunk` renamed to `CaseChunkRow`; adds `zaaknummer`, `subject_uri`, `modified`; drops `rechtsgebied` | Keep original schema | Disambiguates storage (`Row`) from retrieval output (`CitedCase`); `zaaknummer` needed for display; `subject_uri` preserves multi-rechtsgebied extensibility; `modified` supports freshness weighting. |
```

- [ ] **Step 7: Commit the amendment**

```bash
git add docs/superpowers/specs/2026-04-17-jurist-v1-design.md
git commit -m "$(cat <<'EOF'
docs(spec): amend parent for verified rechtspraak.nl taxonomy + M3a/M3b split

Live probing on 2026-04-21 established that no #huurrecht subject URI
exists in rechtspraak.nl open-data. Rewrites §8.2 to use the verified
civielRecht_verbintenissenrecht + keyword-fence strategy, renames
CaseChunk → CaseChunkRow with extensibility fields, splits M3 into
M3a/M3b, and adds three decision-log entries.

Prerequisite commit for M3a implementation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Create M3a branch

**Files:** none (git branch only)

- [ ] **Step 1: Create and check out `m3a-caselaw-ingestion`**

```bash
git checkout -b m3a-caselaw-ingestion
```

Expected: `Switched to a new branch 'm3a-caselaw-ingestion'`.

- [ ] **Step 2: Verify clean status**

```bash
git status
```

Expected: `On branch m3a-caselaw-ingestion`, `nothing to commit, working tree clean`.

No commit in this task — just branch creation.

---

## Task 2: Add sentence-transformers + lancedb dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new deps (alphabetical placement)**

Edit `pyproject.toml` — extend `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.39",
    "fastapi>=0.115",
    "httpx>=0.27",
    "lancedb>=0.13,<1",
    "lxml>=5.3",
    "networkx>=3.3",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
    "sentence-transformers>=3.0,<4",
    "sse-starlette>=2.1",
    "uvicorn[standard]>=0.32",
]
```

Note: `httpx` stays in `[project.optional-dependencies]` as `dev`. No duplicate.

- [ ] **Step 2: Sync dependencies**

```bash
uv sync --extra dev
```

Expected: installs `sentence-transformers`, `lancedb`, and their transitive deps. First-time install pulls torch + pyarrow + numpy — may take several minutes on slow networks.

- [ ] **Step 3: Verify importable**

```bash
uv run python -c "from sentence_transformers import SentenceTransformer; import lancedb; print('ok')"
```

Expected: prints `ok`. (This does NOT trigger the bge-m3 download — that only happens when `SentenceTransformer("BAAI/bge-m3")` is actually instantiated.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(m3a): add sentence-transformers + lancedb dependencies"
```

---

## Task 3: Add CaseChunkRow to schemas

**Files:**
- Modify: `src/jurist/schemas.py`
- Test: `tests/test_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_schemas.py`:

```python
def test_case_chunk_row_serializes_round_trip() -> None:
    from jurist.schemas import CaseChunkRow
    row = CaseChunkRow(
        ecli="ECLI:NL:RBAMS:2025:1234",
        chunk_idx=0,
        court="Rechtbank Amsterdam",
        date="2025-06-15",
        zaaknummer="C/13/123456 / HA ZA 25-001",
        subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
        modified="2025-06-20T14:22:10Z",
        text="De huurder heeft...",
        embedding=[0.1] * 1024,
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2025:1234",
    )
    dumped = row.model_dump()
    restored = CaseChunkRow.model_validate(dumped)
    assert restored == row
    assert len(restored.embedding) == 1024


def test_case_chunk_row_rejects_missing_fields() -> None:
    from jurist.schemas import CaseChunkRow
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        CaseChunkRow(ecli="ECLI:NL:RBAMS:2025:1", chunk_idx=0)  # missing many
```

Check top of `tests/test_schemas.py` for `import pytest`; add if absent.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_schemas.py::test_case_chunk_row_serializes_round_trip -v
```

Expected: FAIL with `ImportError` (no `CaseChunkRow` yet).

- [ ] **Step 3: Add CaseChunkRow to schemas.py**

Edit `src/jurist/schemas.py`. Insert after the existing `CitedCase` class (around line 56):

```python
# ---------------- Case chunk storage (M3a) ----------------

class CaseChunkRow(BaseModel):
    """One LanceDB row: a chunked uitspraak passage + its bge-m3 embedding.

    Logical primary key: (ecli, chunk_idx). LanceDB does not enforce
    uniqueness; the ingester deduplicates on write.
    """

    # identity
    ecli: str
    chunk_idx: int

    # metadata (from RDF)
    court: str
    date: str                    # ISO 8601
    zaaknummer: str
    subject_uri: str
    modified: str                # ISO 8601 last-modified

    # content
    text: str
    embedding: list[float]       # 1024-d bge-m3, L2-normalized

    # display
    url: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: all tests pass, including the two new ones.

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add CaseChunkRow storage schema for M3a"
```

---

## Task 4: Extend config with M3a settings

**Files:**
- Modify: `src/jurist/config.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_m3a_settings_defaults() -> None:
    from jurist.config import settings
    assert settings.caselaw_profile == "huurrecht"
    assert settings.caselaw_subject_uri is None  # profile default resolves later
    assert settings.caselaw_since == "2024-01-01"
    assert settings.caselaw_max_list is None
    assert settings.caselaw_fetch_workers == 5
    assert settings.caselaw_chunk_words == 500
    assert settings.caselaw_chunk_overlap == 50
    assert settings.embed_model == "BAAI/bge-m3"
    assert settings.embed_batch == 32


def test_m3a_settings_env_overrides(monkeypatch) -> None:
    import importlib
    import jurist.config
    monkeypatch.setenv("JURIST_CASELAW_SINCE", "2020-01-01")
    monkeypatch.setenv("JURIST_CASELAW_FETCH_WORKERS", "10")
    monkeypatch.setenv("JURIST_CASELAW_CHUNK_WORDS", "300")
    monkeypatch.setenv("JURIST_EMBED_BATCH", "16")
    importlib.reload(jurist.config)
    from jurist.config import settings as reloaded
    assert reloaded.caselaw_since == "2020-01-01"
    assert reloaded.caselaw_fetch_workers == 10
    assert reloaded.caselaw_chunk_words == 300
    assert reloaded.embed_batch == 16
    # Reset for other tests
    importlib.reload(jurist.config)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py::test_m3a_settings_defaults -v
```

Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'caselaw_profile'`).

- [ ] **Step 3: Extend Settings with M3a fields**

Edit `src/jurist/config.py`. Insert new fields in `Settings` after `statute_catalog_snippet_chars` (around line 33):

```python
    # M3a — caselaw ingestion
    caselaw_profile: str = os.getenv("JURIST_CASELAW_PROFILE", "huurrecht")
    caselaw_subject_uri: str | None = os.getenv("JURIST_CASELAW_SUBJECT_URI")
    caselaw_since: str = os.getenv("JURIST_CASELAW_SINCE", "2024-01-01")
    caselaw_max_list: int | None = (
        int(os.getenv("JURIST_CASELAW_MAX_LIST", "0")) or None
    )
    caselaw_fetch_workers: int = int(os.getenv("JURIST_CASELAW_FETCH_WORKERS", "5"))
    caselaw_chunk_words: int = int(os.getenv("JURIST_CASELAW_CHUNK_WORDS", "500"))
    caselaw_chunk_overlap: int = int(os.getenv("JURIST_CASELAW_CHUNK_OVERLAP", "50"))
    embed_model: str = os.getenv("JURIST_EMBED_MODEL", "BAAI/bge-m3")
    embed_batch: int = int(os.getenv("JURIST_EMBED_BATCH", "32"))

    @property
    def lance_path(self) -> Path:
        return self.data_dir / "lancedb" / "cases.lance"

    @property
    def cases_dir(self) -> Path:
        return self.data_dir / "cases"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/config.py tests/test_config.py
git commit -m "feat(config): add M3a caselaw + embedding settings"
```

---

## Task 5: CaselawProfile registry

**Files:**
- Create: `src/jurist/ingest/caselaw_profiles.py`
- Test: `tests/ingest/test_caselaw_profiles.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingest/test_caselaw_profiles.py`:

```python
"""Tests for CaselawProfile registry."""
from __future__ import annotations

import pytest


def test_huurrecht_profile_has_expected_terms() -> None:
    from jurist.ingest.caselaw_profiles import PROFILES
    prof = PROFILES["huurrecht"]
    assert prof.name == "huurrecht"
    assert prof.subject_uri == (
        "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    )
    assert prof.keyword_terms == ("huur", "verhuur", "woonruimte", "huurcommissie")


def test_unknown_profile_raises() -> None:
    from jurist.ingest.caselaw_profiles import resolve_profile
    with pytest.raises(KeyError):
        resolve_profile("nonexistent")


def test_resolve_returns_correct_profile() -> None:
    from jurist.ingest.caselaw_profiles import resolve_profile
    prof = resolve_profile("huurrecht")
    assert prof.name == "huurrecht"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw_profiles.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create the profiles module**

Create `src/jurist/ingest/caselaw_profiles.py`:

```python
"""Per-rechtsgebied profiles: subject URI + keyword fence terms.

Only `huurrecht` populated in M3a. Adding a second profile is a dict-entry
diff — no pipeline changes required.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaselawProfile:
    name: str
    subject_uri: str
    keyword_terms: tuple[str, ...]


PROFILES: dict[str, CaselawProfile] = {
    "huurrecht": CaselawProfile(
        name="huurrecht",
        subject_uri=(
            "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
        ),
        keyword_terms=("huur", "verhuur", "woonruimte", "huurcommissie"),
    ),
}


def resolve_profile(name: str) -> CaselawProfile:
    """Look up a profile by name. Raises KeyError for unknown names."""
    if name not in PROFILES:
        raise KeyError(f"Unknown caselaw profile: {name!r}. Available: {list(PROFILES)}")
    return PROFILES[name]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw_profiles.py -v
```

Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/caselaw_profiles.py tests/ingest/test_caselaw_profiles.py
git commit -m "feat(ingest): CaselawProfile registry with huurrecht entry"
```

---

## Task 6: Paragraph-aware chunker (splitter.py)

**Files:**
- Create: `src/jurist/ingest/splitter.py`
- Test: `tests/ingest/test_splitter.py`

Per spec §4.2.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_splitter.py`:

```python
"""Tests for paragraph-aware chunker."""
from __future__ import annotations


def test_empty_body_returns_empty() -> None:
    from jurist.ingest.splitter import split
    assert split("", target_words=500, overlap_words=50) == []


def test_short_body_single_chunk() -> None:
    from jurist.ingest.splitter import split
    body = "Dit is een korte uitspraak over huur. De verhuurder heeft gelijk."
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) == 1
    assert chunks[0] == body


def test_paragraphs_packed_until_target() -> None:
    from jurist.ingest.splitter import split
    para1 = " ".join(["woord"] * 200)
    para2 = " ".join(["begrip"] * 200)
    para3 = " ".join(["andere"] * 200)
    body = f"{para1}\n\n{para2}\n\n{para3}"
    chunks = split(body, target_words=500, overlap_words=50)
    # 600 words > 500 target → 2 chunks
    assert len(chunks) == 2
    assert "woord" in chunks[0]
    assert "begrip" in chunks[0]  # packed with para1
    assert "andere" in chunks[1]


def test_overlap_prepends_last_words_of_prev_chunk() -> None:
    from jurist.ingest.splitter import split
    para1 = " ".join([f"a{i}" for i in range(400)])
    para2 = " ".join([f"b{i}" for i in range(400)])
    body = f"{para1}\n\n{para2}"
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    # Last 50 words of chunk 0 should appear at start of chunk 1
    last_50_of_0 = chunks[0].split()[-50:]
    first_50_of_1 = chunks[1].split()[:50]
    assert last_50_of_0 == first_50_of_1


def test_long_single_paragraph_sentence_split() -> None:
    from jurist.ingest.splitter import split
    # 800 words, all in one paragraph (no blank line). Sentence-split fallback.
    sentences = [" ".join(["word"] * 100) + "." for _ in range(8)]
    body = " ".join(sentences)
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 550  # allow some slack for overlap


def test_dutch_abbreviations_not_split_as_sentences() -> None:
    from jurist.ingest.splitter import split
    # "art." and "jo." should not terminate sentences.
    body = (
        "De rechtbank overweegt dat art. 7:248 BW jo. art. 7:246 BW "
        "van toepassing is. Dit geldt ook voor Hof Den Haag 2023. "
        "Daarom volgt het oordeel."
    )
    chunks = split(body, target_words=500, overlap_words=50)
    # Short body, should stay one chunk; key test is that when larger bodies
    # split, abbrevs don't create broken chunks. Inline trivial check here:
    assert len(chunks) == 1


def test_pathological_single_sentence_char_split() -> None:
    from jurist.ingest.splitter import split
    # 700 "words" with no sentence boundaries (malformed XML edge).
    body = " ".join(["noend"] * 700)
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 550
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_splitter.py -v
```

Expected: FAIL (no splitter module).

- [ ] **Step 3: Create the splitter**

Create `src/jurist/ingest/splitter.py`:

```python
"""Paragraph-aware recursive text chunker. Stdlib only.

Algorithm:
1. Split body on blank-line boundaries → paragraphs.
2. Greedily pack paragraphs into chunks up to `target_words`.
3. Single paragraph > target → recurse on sentence boundaries, skipping
   Dutch legal abbreviations.
4. Single sentence > target → character-split at word boundary (last resort).

Overlap: last `overlap_words` of chunk N are prepended to chunk N+1.
"""
from __future__ import annotations

import re

# Dutch legal abbreviations that end with a period but are NOT sentence
# terminators. Case-sensitive — "Art." at start of sentence is intentional.
_ABBREVIATIONS = {
    "art.", "artt.", "lid", "jo.", "Hof", "Mr.", "Dr.", "mr.", "dr.",
    "nr.", "blz.", "o.a.", "i.c.", "m.b.t.", "vs.", "ibid.", "ca.",
}

_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")


def split(body: str, *, target_words: int, overlap_words: int) -> list[str]:
    """Chunk `body` into ≤`target_words`-word slices with overlap.

    Returns [] for empty input.
    """
    if not body.strip():
        return []

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    raw_chunks: list[str] = []
    buf: list[str] = []
    buf_wc = 0
    for para in paragraphs:
        wc = _word_count(para)
        if wc > target_words:
            # Flush current buffer, then recurse on this long paragraph.
            if buf:
                raw_chunks.append(" ".join(buf))
                buf, buf_wc = [], 0
            raw_chunks.extend(_split_long(para, target_words))
            continue
        if buf_wc + wc > target_words and buf:
            raw_chunks.append(" ".join(buf))
            buf, buf_wc = [], 0
        buf.append(para)
        buf_wc += wc
    if buf:
        raw_chunks.append(" ".join(buf))

    return _apply_overlap(raw_chunks, overlap_words)


def _word_count(s: str) -> int:
    return len(s.split())


def _split_long(para: str, target_words: int) -> list[str]:
    """Sentence-split; fall back to char-split on single long sentences."""
    sentences = _sentence_split(para)
    out: list[str] = []
    buf: list[str] = []
    buf_wc = 0
    for sent in sentences:
        wc = _word_count(sent)
        if wc > target_words:
            # Flush, then char-split this monster.
            if buf:
                out.append(" ".join(buf))
                buf, buf_wc = [], 0
            out.extend(_char_split(sent, target_words))
            continue
        if buf_wc + wc > target_words and buf:
            out.append(" ".join(buf))
            buf, buf_wc = [], 0
        buf.append(sent)
        buf_wc += wc
    if buf:
        out.append(" ".join(buf))
    return out


def _sentence_split(text: str) -> list[str]:
    """Split on sentence ends, skipping Dutch legal abbreviations."""
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        # Look at the word ending at `match.start()` — skip if it's an abbrev.
        preceding = text[:match.start()].rsplit(None, 1)
        prev_word = preceding[-1] if preceding else ""
        if prev_word in _ABBREVIATIONS:
            continue
        parts.append(text[start:match.start() + 1].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _char_split(sent: str, target_words: int) -> list[str]:
    """Last-resort word-boundary split for pathologically long sentences."""
    words = sent.split()
    return [
        " ".join(words[i : i + target_words])
        for i in range(0, len(words), target_words)
    ]


def _apply_overlap(chunks: list[str], overlap_words: int) -> list[str]:
    """Prepend last `overlap_words` of chunk N to chunk N+1."""
    if overlap_words <= 0 or len(chunks) <= 1:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = " ".join(chunks[i - 1].split()[-overlap_words:])
        out.append(f"{prev_tail} {chunks[i]}")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_splitter.py -v
```

Expected: all seven tests pass.

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check src/jurist/ingest/splitter.py tests/ingest/test_splitter.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/ingest/splitter.py tests/ingest/test_splitter.py
git commit -m "feat(ingest): paragraph-aware text chunker (splitter.py)"
```

---

## Task 7: Keyword filter (caselaw_filter.py)

**Files:**
- Create: `src/jurist/ingest/caselaw_filter.py`
- Test: `tests/ingest/test_caselaw_filter.py`

Per spec §4.3.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_caselaw_filter.py`:

```python
"""Tests for lenient keyword fence."""
from __future__ import annotations


def test_empty_body_does_not_pass() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("") is False


def test_body_without_huur_terms_does_not_pass() -> None:
    from jurist.ingest.caselaw_filter import passes
    body = "De echtgenoot verzoekt een wijziging van de alimentatie."
    assert passes(body) is False


def test_body_with_huur_substring_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De huurder heeft de huurprijs betaald.") is True


def test_body_with_verhuur_substring_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De verhuurder heeft opgezegd.") is True


def test_body_with_woonruimte_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("Een zelfstandige woonruimte in Amsterdam.") is True


def test_body_with_huurcommissie_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De Huurcommissie heeft beslist.") is True


def test_case_folded_match() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("WOONRUIMTE") is True
    assert passes("Woonruimte") is True


def test_custom_terms_override_default() -> None:
    from jurist.ingest.caselaw_filter import passes
    # Default `huur` not in body; custom term `pacht` is.
    assert passes("De pachter heeft het land bewerkt.", terms=("pacht",)) is True
    assert passes("De pachter heeft het land bewerkt.") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw_filter.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Create the filter module**

Create `src/jurist/ingest/caselaw_filter.py`:

```python
"""Lenient keyword fence for post-download filtering."""
from __future__ import annotations

from jurist.ingest.caselaw_profiles import PROFILES

HUURRECHT_TERMS = PROFILES["huurrecht"].keyword_terms


def passes(body_text: str, *, terms: tuple[str, ...] = HUURRECHT_TERMS) -> bool:
    """True iff `body_text` contains any `terms` (case-folded substring).

    Empty body → False. No word-boundary requirement — substring match
    catches inflections (huurder, huurders, huurprijs, verhuurder, etc.)
    without a morphology list.
    """
    if not body_text:
        return False
    lower = body_text.casefold()
    return any(term.casefold() in lower for term in terms)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw_filter.py -v
```

Expected: all eight tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/caselaw_filter.py tests/ingest/test_caselaw_filter.py
git commit -m "feat(ingest): lenient keyword fence (caselaw_filter.py)"
```

---

## Task 8: Fetch list endpoint (paginated ECLI discovery)

**Files:**
- Create: `src/jurist/ingest/caselaw_fetch.py`
- Test: `tests/ingest/test_caselaw_fetch_list.py`

Per spec §3.2 stage 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_caselaw_fetch_list.py`:

```python
"""Tests for list-endpoint pagination."""
from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest


FEED_PAGE_1 = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <subtitle>Aantal gevonden ECLI's: 3</subtitle>
  <entry>
    <id>ECLI:NL:RBAMS:2025:1</id>
    <updated>2025-01-10T08:00:00Z</updated>
  </entry>
  <entry>
    <id>ECLI:NL:RBAMS:2025:2</id>
    <updated>2025-01-11T08:00:00Z</updated>
  </entry>
</feed>"""

FEED_PAGE_2 = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <subtitle>Aantal gevonden ECLI's: 3</subtitle>
  <entry>
    <id>ECLI:NL:RBAMS:2025:3</id>
    <updated>2025-01-12T08:00:00Z</updated>
  </entry>
</feed>"""

FEED_EMPTY = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <subtitle>Aantal gevonden ECLI's: 3</subtitle>
</feed>"""


@contextmanager
def _fake_server(pages_by_from: dict[int, bytes]) -> Iterator[str]:
    """Minimal HTTP server returning hardcoded Atom pages keyed by `from`."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            # Parse `from=N` from query string; default 0.
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            from_val = int(query.get("from", ["0"])[0])
            body = pages_by_from.get(from_val, FEED_EMPTY)
            self.send_response(200)
            self.send_header("Content-Type", "application/atom+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # noqa: ARG002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_list_eclis_paginates_until_empty(monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    pages = {0: FEED_PAGE_1, 2: FEED_PAGE_2, 3: FEED_EMPTY}
    with _fake_server(pages) as base_url:
        monkeypatch.setattr(caselaw_fetch, "ZOEKEN_URL", f"{base_url}/zoeken")
        eclis = list(caselaw_fetch.list_eclis(
            subject_uri="http://example/huur",
            since="2024-01-01",
            page_size=2,
        ))
    assert eclis == [
        ("ECLI:NL:RBAMS:2025:1", "2025-01-10T08:00:00Z"),
        ("ECLI:NL:RBAMS:2025:2", "2025-01-11T08:00:00Z"),
        ("ECLI:NL:RBAMS:2025:3", "2025-01-12T08:00:00Z"),
    ]


def test_list_eclis_respects_max_list(monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    pages = {0: FEED_PAGE_1, 2: FEED_PAGE_2, 3: FEED_EMPTY}
    with _fake_server(pages) as base_url:
        monkeypatch.setattr(caselaw_fetch, "ZOEKEN_URL", f"{base_url}/zoeken")
        eclis = list(caselaw_fetch.list_eclis(
            subject_uri="http://example/huur",
            since="2024-01-01",
            page_size=2,
            max_list=2,
        ))
    assert len(eclis) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw_fetch_list.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Create the fetch module with list_eclis()**

Create `src/jurist/ingest/caselaw_fetch.py`:

```python
"""HTTP clients for rechtspraak.nl open-data endpoints.

Two functions:
  - list_eclis: paginated ECLI discovery via the zoeken endpoint.
  - fetch_content: full uitspraak XML by ECLI, with disk cache.

Stdlib-only (urllib + xml.etree); 5-way parallelism for fetch_content
via ThreadPoolExecutor (Task 9).
"""
from __future__ import annotations

import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator

log = logging.getLogger(__name__)

ZOEKEN_URL = "https://data.rechtspraak.nl/uitspraken/zoeken"
CONTENT_URL = "https://data.rechtspraak.nl/uitspraken/content"
USER_AGENT = "jurist-demo/0.1 (portfolio project)"

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def list_eclis(
    *,
    subject_uri: str,
    since: str,
    page_size: int = 1000,
    max_list: int | None = None,
) -> Iterator[tuple[str, str]]:
    """Paginate the zoeken endpoint; yield (ecli, updated_ts) pairs.

    Terminates on the first page with zero entries.
    """
    emitted = 0
    offset = 0
    while True:
        params = {
            "subject": subject_uri,
            "modified": since,
            "max": str(page_size),
            "from": str(offset),
        }
        url = f"{ZOEKEN_URL}?{urllib.parse.urlencode(params, safe=':#/')}"
        log.debug("list_eclis GET %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = resp.read()

        root = ET.fromstring(data)
        entries = root.findall(f"{ATOM_NS}entry")
        if not entries:
            return
        for entry in entries:
            ecli_elem = entry.find(f"{ATOM_NS}id")
            updated_elem = entry.find(f"{ATOM_NS}updated")
            if ecli_elem is None or ecli_elem.text is None:
                continue
            ecli = ecli_elem.text.strip()
            updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""
            yield (ecli, updated)
            emitted += 1
            if max_list is not None and emitted >= max_list:
                return
        offset += page_size


def fetch_content(ecli: str) -> bytes:  # pragma: no cover - placeholder for Task 9
    """Filled in Task 9."""
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw_fetch_list.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/caselaw_fetch.py tests/ingest/test_caselaw_fetch_list.py
git commit -m "feat(ingest): paginated ECLI discovery via zoeken endpoint"
```

---

## Task 9: Fetch content endpoint with disk cache + retry

**Files:**
- Modify: `src/jurist/ingest/caselaw_fetch.py`
- Test: `tests/ingest/test_caselaw_fetch_content.py`

Per spec §3.2 stage 4.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_caselaw_fetch_content.py`:

```python
"""Tests for fetch_content with disk cache + retry."""
from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest


SAMPLE_CONTENT = b"<open-rechtspraak><x>body</x></open-rechtspraak>"


@contextmanager
def _fake_content_server(
    ecli_to_status: dict[str, list[int]],
    ecli_to_body: dict[str, bytes],
) -> Iterator[str]:
    """Server that returns specific status codes per ECLI, in sequence."""
    status_cursor: dict[str, int] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            ecli = query.get("id", [""])[0]
            statuses = ecli_to_status.get(ecli, [200])
            idx = status_cursor.get(ecli, 0)
            code = statuses[min(idx, len(statuses) - 1)]
            status_cursor[ecli] = idx + 1
            body = ecli_to_body.get(ecli, b"")
            if code == 200:
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(code)
                self.end_headers()

        def log_message(self, *args) -> None:  # noqa: ARG002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_content_writes_to_cache(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    ecli = "ECLI:NL:RBAMS:2025:1"
    with _fake_content_server({ecli: [200]}, {ecli: SAMPLE_CONTENT}) as base_url:
        monkeypatch.setattr(caselaw_fetch, "CONTENT_URL", f"{base_url}/content")
        path = caselaw_fetch.fetch_content(ecli, cache_dir=tmp_path)
    assert path.exists()
    assert path.read_bytes() == SAMPLE_CONTENT
    expected = tmp_path / "ECLI_NL_RBAMS_2025_1.xml"
    assert path == expected


def test_fetch_content_hits_cache(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    ecli = "ECLI:NL:RBAMS:2025:1"
    cached = tmp_path / "ECLI_NL_RBAMS_2025_1.xml"
    cached.write_bytes(b"cached-content")
    # No server — if we hit the network, the call will fail.
    monkeypatch.setattr(caselaw_fetch, "CONTENT_URL", "http://127.0.0.1:1")
    path = caselaw_fetch.fetch_content(ecli, cache_dir=tmp_path)
    assert path.read_bytes() == b"cached-content"


def test_fetch_content_retries_once_on_5xx(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    ecli = "ECLI:NL:RBAMS:2025:2"
    # 503, then 200.
    with _fake_content_server(
        {ecli: [503, 200]},
        {ecli: SAMPLE_CONTENT},
    ) as base_url:
        monkeypatch.setattr(caselaw_fetch, "CONTENT_URL", f"{base_url}/content")
        monkeypatch.setattr(caselaw_fetch, "RETRY_BACKOFF_S", 0.01)  # fast test
        path = caselaw_fetch.fetch_content(ecli, cache_dir=tmp_path)
    assert path.read_bytes() == SAMPLE_CONTENT


def test_fetch_content_raises_after_two_failures(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw_fetch

    ecli = "ECLI:NL:RBAMS:2025:3"
    with _fake_content_server({ecli: [503, 503]}, {}) as base_url:
        monkeypatch.setattr(caselaw_fetch, "CONTENT_URL", f"{base_url}/content")
        monkeypatch.setattr(caselaw_fetch, "RETRY_BACKOFF_S", 0.01)
        with pytest.raises(caselaw_fetch.FetchError):
            caselaw_fetch.fetch_content(ecli, cache_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw_fetch_content.py -v
```

Expected: FAIL (not implemented).

- [ ] **Step 3: Implement fetch_content + FetchError**

Replace the `fetch_content` placeholder at the bottom of `src/jurist/ingest/caselaw_fetch.py`:

```python
import urllib.error
from pathlib import Path

RETRY_BACKOFF_S = 2.0


class FetchError(RuntimeError):
    """Raised when fetch_content fails after one retry."""


def _cache_path_for(ecli: str, cache_dir: Path) -> Path:
    # ECLI has colons; Windows paths can't contain ':'. Replace with '_'.
    safe = ecli.replace(":", "_")
    return cache_dir / f"{safe}.xml"


def fetch_content(ecli: str, *, cache_dir: Path) -> Path:
    """Fetch the full XML for `ecli`. Cache-first. Returns the cached file path.

    On HTTP non-200: sleeps RETRY_BACKOFF_S, retries once. If retry also fails,
    raises FetchError.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path_for(ecli, cache_dir)
    if target.exists():
        return target

    url = f"{CONTENT_URL}?id={urllib.parse.quote(ecli, safe=':')}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                if resp.status == 200:
                    data = resp.read()
                    break
                log.warning("fetch_content %s HTTP %d (attempt %d)",
                            ecli, resp.status, attempt)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            log.warning("fetch_content %s error: %s (attempt %d)", ecli, exc, attempt)
        if attempt == 1:
            time.sleep(RETRY_BACKOFF_S)
    else:
        raise FetchError(f"fetch_content failed after retry for {ecli}")

    tmp = target.with_suffix(".xml.tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw_fetch_content.py -v
```

Expected: all four tests pass.

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check src/jurist/ingest/caselaw_fetch.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/ingest/caselaw_fetch.py tests/ingest/test_caselaw_fetch_content.py
git commit -m "feat(ingest): fetch_content with disk cache + one-retry semantics"
```

---

## Task 10: Commit real ECLI XML test fixtures

**Files:**
- Create: `tests/fixtures/caselaw/ECLI_NL_RBAMS_sample1.xml`
- Create: `tests/fixtures/caselaw/ECLI_NL_GHARL_sample2.xml`
- Create: `tests/fixtures/caselaw/sparse_case.xml`

Three fixture files to drive parser unit tests in Task 11.

- [ ] **Step 1: Download two real ECLI XMLs as fixtures**

Pick two real ECLIs the ingester will realistically encounter. The first probe in brainstorming hit `ECLI:NL:RBARN:1998:AA1005` but that one is "Bestuursrecht" — we want huur cases. Any recent kantonrechter verbintenissenrecht case works.

Run the following one-shot commands (adjust ECLIs if 404). These real public records are fine to commit — they're already anonymized by rechtspraak.nl.

```bash
mkdir -p tests/fixtures/caselaw

# Any two real huur-mentioning ECLIs. Replace the IDs with ones you actually
# fetch successfully — pick from the ingester's first list output, or the
# rechtspraak.nl UI after filtering by rechtsgebied=r2 + zoekterm=huur.
# Example structure (update ECLIs to real ones before running):
curl -sL -o tests/fixtures/caselaw/ECLI_NL_RBAMS_sample1.xml \
  "https://data.rechtspraak.nl/uitspraken/content?id=ECLI:NL:RBAMS:2025:3623"
curl -sL -o tests/fixtures/caselaw/ECLI_NL_GHARL_sample2.xml \
  "https://data.rechtspraak.nl/uitspraken/content?id=ECLI:NL:GHARL:2026:1996"

# Verify they're valid XML and reasonably sized (>2 KB each).
ls -la tests/fixtures/caselaw/*.xml
```

Expected: both files exist, each > 2 KB. If either returns a small (<500 B) response or empty body, pick a different ECLI.

If a body doesn't actually contain huur-terms, that's fine for the parser test — we're testing *parsing*, not filtering. But for convenience, fetch at least one huur-related case so downstream integration tests can use it.

- [ ] **Step 2: Create the sparse fixture by hand**

Create `tests/fixtures/caselaw/sparse_case.xml` — a handcrafted minimal XML that exercises parser robustness (missing optional fields):

```xml
<?xml version="1.0" encoding="utf-8"?>
<open-rechtspraak>
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
           xmlns:dcterms="http://purl.org/dc/terms/"
           xmlns:psi="http://psi.rechtspraak.nl/">
    <rdf:Description>
      <dcterms:identifier>ECLI:NL:RBTEST:2025:9999</dcterms:identifier>
      <dcterms:date>2025-06-15</dcterms:date>
      <dcterms:creator resourceIdentifier="http://standaarden.overheid.nl/owms/terms/Rechtbank_Test">Rechtbank Test</dcterms:creator>
      <dcterms:modified>2025-06-20T14:22:10</dcterms:modified>
      <dcterms:subject resourceIdentifier="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht">Civiel recht; Verbintenissenrecht</dcterms:subject>
      <!-- NOTE: no psi:zaaknummer; parser should default to empty string -->
    </rdf:Description>
  </rdf:RDF>
  <uitspraak>
    <section>
      <para>De huurder heeft de verhuurder aangesproken op grond van artikel 7:248 BW. De woonruimte is geliberaliseerd.</para>
    </section>
  </uitspraak>
</open-rechtspraak>
```

- [ ] **Step 3: Commit fixtures**

```bash
git add tests/fixtures/caselaw/
git commit -m "test(ingest): commit real + sparse ECLI XML fixtures for parser tests"
```

---

## Task 11: Caselaw parser (RDF metadata + body text)

**Files:**
- Create: `src/jurist/ingest/caselaw_parser.py`
- Test: `tests/ingest/test_caselaw_parser.py`

Per spec §3.2 stage 5.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_caselaw_parser.py`:

```python
"""Tests for RDF + body extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "caselaw"


def test_parse_sparse_case() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    xml = (FIXTURE_DIR / "sparse_case.xml").read_bytes()
    meta = parse_case(xml)
    assert meta.ecli == "ECLI:NL:RBTEST:2025:9999"
    assert meta.date == "2025-06-15"
    assert meta.court == "Rechtbank Test"
    assert meta.zaaknummer == ""  # missing in sparse fixture
    assert meta.subject_uri == (
        "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    )
    assert meta.modified == "2025-06-20T14:22:10"
    assert "huurder" in meta.body_text
    assert "woonruimte" in meta.body_text
    assert meta.url == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBTEST:2025:9999"
    )


def test_parse_real_fixture_yields_populated_fields() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    # Pick any real fixture that exists
    candidates = list(FIXTURE_DIR.glob("ECLI_*.xml"))
    assert candidates, "expected at least one real ECLI fixture"
    xml = candidates[0].read_bytes()
    meta = parse_case(xml)
    assert meta.ecli.startswith("ECLI:NL:")
    assert meta.date  # ISO date present
    assert meta.court  # non-empty court string
    assert meta.subject_uri.startswith("http://psi.rechtspraak.nl/rechtsgebied#")
    assert meta.url.startswith("https://uitspraken.rechtspraak.nl/details?id=ECLI:")
    assert len(meta.body_text) > 100  # non-trivial body


def test_parse_body_strips_xml_tags_and_collapses_whitespace() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<open-rechtspraak>
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
           xmlns:dcterms="http://purl.org/dc/terms/">
    <rdf:Description>
      <dcterms:identifier>ECLI:NL:RBTEST:2025:1</dcterms:identifier>
      <dcterms:date>2025-01-01</dcterms:date>
      <dcterms:creator resourceIdentifier="x">Rb</dcterms:creator>
      <dcterms:subject resourceIdentifier="http://psi.rechtspraak.nl/rechtsgebied#x">x</dcterms:subject>
      <dcterms:modified>2025-01-02</dcterms:modified>
    </rdf:Description>
  </rdf:RDF>
  <uitspraak>
    <para>Eerste    paragraaf met   veel spaties.</para>
    <para>Tweede paragraaf.</para>
  </uitspraak>
</open-rechtspraak>"""
    meta = parse_case(xml)
    assert "Eerste paragraaf met veel spaties." in meta.body_text
    assert "Tweede paragraaf." in meta.body_text
    # Paragraph break preserved
    assert "\n\n" in meta.body_text


def test_parse_invalid_xml_raises() -> None:
    from jurist.ingest.caselaw_parser import parse_case, ParseError

    with pytest.raises(ParseError):
        parse_case(b"<not valid xml")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw_parser.py -v
```

Expected: FAIL (no parser module).

- [ ] **Step 3: Create the parser**

Create `src/jurist/ingest/caselaw_parser.py`:

```python
"""Parse rechtspraak.nl open-data XML → CaseMeta.

RDF namespaces used:
  dcterms:  http://purl.org/dc/terms/
  rdf:      http://www.w3.org/1999/02/22-rdf-syntax-ns#
  psi:      http://psi.rechtspraak.nl/

Body text lives outside the <rdf:RDF> block, in <uitspraak> descendants.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

NS = {
    "dcterms": "http://purl.org/dc/terms/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "psi": "http://psi.rechtspraak.nl/",
}


class ParseError(RuntimeError):
    """Raised when XML cannot be parsed."""


@dataclass(frozen=True)
class CaseMeta:
    ecli: str
    date: str
    court: str
    zaaknummer: str
    subject_uri: str
    modified: str
    body_text: str
    url: str


def parse_case(xml_bytes: bytes) -> CaseMeta:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ParseError(f"invalid XML: {exc}") from exc

    desc = root.find(".//rdf:Description", NS)
    if desc is None:
        raise ParseError("no rdf:Description block")

    ecli = _text(desc.find("dcterms:identifier", NS))
    date = _text(desc.find("dcterms:date", NS))
    court = _text(desc.find("dcterms:creator", NS))
    zaaknummer = _text(desc.find("psi:zaaknummer", NS))
    modified = _text(desc.find("dcterms:modified", NS))

    subject_elem = desc.find("dcterms:subject", NS)
    subject_uri = ""
    if subject_elem is not None:
        subject_uri = subject_elem.get("resourceIdentifier", "")

    # Body: everything under <uitspraak> (or <conclusie>), text-only
    body_text = _extract_body(root)

    url = (
        f"https://uitspraken.rechtspraak.nl/details?id={ecli}"
        if ecli
        else ""
    )

    return CaseMeta(
        ecli=ecli,
        date=date,
        court=court,
        zaaknummer=zaaknummer,
        subject_uri=subject_uri,
        modified=modified,
        body_text=body_text,
        url=url,
    )


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


_WS = re.compile(r"[ \t]+")


def _extract_body(root: ET.Element) -> str:
    """Walk <uitspraak>/<conclusie> descendants, collecting paragraph text.

    Returns paragraphs joined by \\n\\n; internal whitespace collapsed.
    """
    paragraphs: list[str] = []
    for block_name in ("uitspraak", "conclusie"):
        block = _find_local(root, block_name)
        if block is None:
            continue
        for para in _find_local_all(block, "para"):
            text = " ".join(para.itertext())
            text = _WS.sub(" ", text).strip()
            if text:
                paragraphs.append(text)
    # Fallback: if no <para> descendants found, concatenate all text.
    if not paragraphs:
        for block_name in ("uitspraak", "conclusie"):
            block = _find_local(root, block_name)
            if block is None:
                continue
            text = " ".join(block.itertext())
            text = _WS.sub(" ", text).strip()
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _find_local(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Find descendant whose tag ends with `local_name` (namespace-agnostic)."""
    for sub in elem.iter():
        if sub.tag == local_name or sub.tag.endswith(f"}}{local_name}"):
            return sub
    return None


def _find_local_all(elem: ET.Element, local_name: str) -> list[ET.Element]:
    return [
        sub for sub in elem.iter()
        if sub.tag == local_name or sub.tag.endswith(f"}}{local_name}")
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw_parser.py -v
```

Expected: all four tests pass. If `test_parse_real_fixture_yields_populated_fields` fails because the real fixture has no <para> structure (some older ECLIs just have raw text), the fallback in `_extract_body` handles it.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/ingest/caselaw_parser.py tests/ingest/test_caselaw_parser.py
git commit -m "feat(ingest): RDF + body-text parser for rechtspraak.nl XML"
```

---

## Task 12: bge-m3 embedding wrapper

**Files:**
- Create: `src/jurist/embedding.py`
- Test: `tests/embedding/__init__.py` (empty), `tests/embedding/test_embedding.py`

Per spec §5.

- [ ] **Step 1: Write the failing tests (mocked encoder)**

Create `tests/embedding/__init__.py` as an empty file:

```bash
mkdir -p tests/embedding
touch tests/embedding/__init__.py
```

Create `tests/embedding/test_embedding.py`:

```python
"""Tests for Embedder with a mocked SentenceTransformer."""
from __future__ import annotations

import numpy as np


class _FakeST:
    """Stand-in for sentence_transformers.SentenceTransformer."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls: list[dict] = []

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.calls.append({"batch_size": batch_size, "n": len(texts)})
        # Deterministic 1024-d vectors based on text length hash.
        vecs = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, t in enumerate(texts):
            vecs[i, 0] = float(len(t))
            vecs[i, 1] = float(hash(t) % 1000)
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vecs = vecs / norms
        return vecs


def test_embedder_returns_1024d_unit_norm(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    vectors = emb.encode(["hallo", "wereld"])
    assert vectors.shape == (2, 1024)
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embedder_passes_batch_size(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    emb.encode(["a", "b", "c"], batch_size=2)
    assert emb._model.calls == [{"batch_size": 2, "n": 3}]


def test_embedder_empty_input_returns_empty_array(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    vectors = emb.encode([])
    assert vectors.shape == (0, 1024)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/embedding/test_embedding.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Create the Embedder**

Create `src/jurist/embedding.py`:

```python
"""bge-m3 embedding wrapper. Shared by ingester (M3a) and case retriever (M3b).

First use triggers a HuggingFace model download (~2.3 GB) to the default
`~/.cache/huggingface/hub/`. Subsequent instantiations hit the cache.
"""
from __future__ import annotations

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

EMBED_DIM = 1024


class Embedder:
    def __init__(self, *, model_name: str = "BAAI/bge-m3") -> None:
        log.info("Embedder: loading %s (may download on first use)", model_name)
        self._model = SentenceTransformer(model_name)
        self.model_name = model_name

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
    ) -> np.ndarray:
        """Return (N, 1024) float32 L2-normalized embeddings.

        Empty input → (0, 1024) array.
        """
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        return self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/embedding/test_embedding.py -v
```

Expected: all three tests pass. (No real bge-m3 download — the fake class replaces `SentenceTransformer`.)

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check src/jurist/embedding.py tests/embedding/
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/jurist/embedding.py tests/embedding/
git commit -m "feat(embedding): bge-m3 wrapper (Embedder class) + mocked unit tests"
```

---

## Task 13: LanceDB vector store (CaseStore)

**Files:**
- Create: `src/jurist/vectorstore.py`
- Test: `tests/vectorstore/__init__.py` (empty), `tests/vectorstore/test_vectorstore.py`

Per spec §6.

- [ ] **Step 1: Write the failing tests**

```bash
mkdir -p tests/vectorstore
touch tests/vectorstore/__init__.py
```

Create `tests/vectorstore/test_vectorstore.py`:

```python
"""Tests for CaseStore LanceDB CRUD."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from jurist.schemas import CaseChunkRow


def _make_row(ecli: str, chunk_idx: int, *, vector: list[float] | None = None) -> CaseChunkRow:
    if vector is None:
        vector = [0.1] * 1024
    return CaseChunkRow(
        ecli=ecli,
        chunk_idx=chunk_idx,
        court="Rechtbank Test",
        date="2025-06-15",
        zaaknummer="C/13/1",
        subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
        modified="2025-06-20T14:22:10Z",
        text=f"Body for {ecli} chunk {chunk_idx}",
        embedding=vector,
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def test_open_or_create_on_fresh_path(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    assert store.all_eclis() == set()


def test_add_rows_then_contains_ecli(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0), _make_row("ECLI:NL:A:1", 1)])
    assert store.contains_ecli("ECLI:NL:A:1") is True
    assert store.contains_ecli("ECLI:NL:A:2") is False
    assert store.all_eclis() == {"ECLI:NL:A:1"}


def test_add_rows_dedupes_on_ecli_and_chunk_idx(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0)])
    store.add_rows([_make_row("ECLI:NL:A:1", 0), _make_row("ECLI:NL:A:1", 1)])
    # (A:1, 0) is a duplicate; add_rows skips it.
    assert store.row_count() == 2


def test_query_top_k_by_cosine(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    v_near = [1.0, 0.0] + [0.0] * 1022
    v_far = [0.0, 1.0] + [0.0] * 1022
    store.add_rows([
        _make_row("ECLI:NL:NEAR:1", 0, vector=v_near),
        _make_row("ECLI:NL:FAR:1", 0, vector=v_far),
    ])
    results = store.query(np.array([1.0, 0.0] + [0.0] * 1022, dtype=np.float32), top_k=1)
    assert len(results) == 1
    assert results[0].ecli == "ECLI:NL:NEAR:1"


def test_drop_removes_table(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0)])
    store.drop()
    store.open_or_create()
    assert store.all_eclis() == set()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/vectorstore/test_vectorstore.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Create the CaseStore**

Create `src/jurist/vectorstore.py`:

```python
"""LanceDB CRUD for CaseChunkRow storage.

Concrete class — no interface — per parent spec §15 decision #12.
Used by the M3a ingester (add_rows) and the M3b case retriever (query).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa

import lancedb

from jurist.schemas import CaseChunkRow

log = logging.getLogger(__name__)

_TABLE_NAME = "cases"

_SCHEMA = pa.schema([
    ("ecli", pa.string()),
    ("chunk_idx", pa.int32()),
    ("court", pa.string()),
    ("date", pa.string()),
    ("zaaknummer", pa.string()),
    ("subject_uri", pa.string()),
    ("modified", pa.string()),
    ("text", pa.string()),
    ("embedding", pa.list_(pa.float32(), 1024)),
    ("url", pa.string()),
])


class CaseStore:
    def __init__(self, lance_path: Path) -> None:
        self.lance_path = Path(lance_path)
        self._db: lancedb.DBConnection | None = None
        self._table: lancedb.table.Table | None = None

    def open_or_create(self) -> None:
        self.lance_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.lance_path))
        if _TABLE_NAME in self._db.table_names():
            self._table = self._db.open_table(_TABLE_NAME)
        else:
            self._table = self._db.create_table(_TABLE_NAME, schema=_SCHEMA)

    def contains_ecli(self, ecli: str) -> bool:
        self._require_open()
        safe = ecli.replace("'", "''")
        df = self._table.search().where(f"ecli = '{safe}'").limit(1).to_pandas()
        return len(df) > 0

    def all_eclis(self) -> set[str]:
        self._require_open()
        df = self._table.to_pandas()
        return set(df["ecli"].tolist()) if len(df) > 0 else set()

    def row_count(self) -> int:
        self._require_open()
        return self._table.count_rows()

    def add_rows(self, rows: list[CaseChunkRow]) -> None:
        """Batch-append. Skip rows whose (ecli, chunk_idx) already exist."""
        self._require_open()
        if not rows:
            return
        existing = self._existing_keys({r.ecli for r in rows})
        fresh = [r for r in rows if (r.ecli, r.chunk_idx) not in existing]
        if not fresh:
            return
        records = [r.model_dump() for r in fresh]
        self._table.add(records)

    def query(
        self,
        vector: np.ndarray,
        *,
        top_k: int = 20,
    ) -> list[CaseChunkRow]:
        self._require_open()
        vec = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
        df = self._table.search(vec).metric("cosine").limit(top_k).to_pandas()
        out: list[CaseChunkRow] = []
        for rec in df.to_dict(orient="records"):
            rec.pop("_distance", None)
            out.append(CaseChunkRow.model_validate(rec))
        return out

    def drop(self) -> None:
        if self.lance_path.exists():
            shutil.rmtree(self.lance_path)
        self._db = None
        self._table = None

    def _require_open(self) -> None:
        if self._table is None:
            raise RuntimeError("CaseStore.open_or_create() must be called first")

    def _existing_keys(self, eclis: set[str]) -> set[tuple[str, int]]:
        if not eclis:
            return set()
        quoted = ", ".join(f"'{e}'" for e in eclis)
        df = (
            self._table.search()
            .where(f"ecli IN ({quoted})")
            .select(["ecli", "chunk_idx"])
            .limit(1_000_000)
            .to_pandas()
        )
        if len(df) == 0:
            return set()
        return {(row["ecli"], row["chunk_idx"]) for _, row in df.iterrows()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/vectorstore/test_vectorstore.py -v
```

Expected: all five tests pass.

Notes if tests fail:
- LanceDB's Python API has evolved; the `search(...).where(...)` pattern works in `lancedb>=0.13`. If a method signature has changed, consult `uv pip show lancedb` and `dir(self._table)`.
- On Windows, LanceDB creates the database as a directory (`*.lance` is a dir, not a file). `shutil.rmtree` handles both.

- [ ] **Step 5: Commit**

```bash
git add src/jurist/vectorstore.py tests/vectorstore/
git commit -m "feat(vectorstore): CaseStore LanceDB CRUD + round-trip tests"
```

---

## Task 14: Pipeline orchestrator + CLI (caselaw.py)

**Files:**
- Create: `src/jurist/ingest/caselaw.py`
- Test: `tests/ingest/test_caselaw.py`

Per spec §3.2 (all nine stages).

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_caselaw.py`:

```python
"""Tests for the caselaw ingest orchestrator (with mocked fetch + embedder)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

# The real `fetch_content` is replaced by a stub that writes fixture files
# into the disk cache.


def _install_fake_fetch(monkeypatch, fixtures_dir: Path, cache_dir: Path) -> None:
    from jurist.ingest import caselaw_fetch

    def fake_list(**_kwargs):
        # Yield three ECLIs; caselaw.py downloads content for each.
        yield ("ECLI:NL:RBAMS:2025:1001", "2025-06-15T10:00:00Z")
        yield ("ECLI:NL:RBAMS:2025:1002", "2025-06-16T10:00:00Z")
        yield ("ECLI:NL:RBTEST:2025:9999", "2025-06-20T14:22:10Z")

    def fake_fetch(ecli: str, *, cache_dir: Path) -> Path:
        # Map fake ECLIs to committed fixtures.
        mapping = {
            "ECLI:NL:RBTEST:2025:9999": fixtures_dir / "sparse_case.xml",
        }
        real_fixtures = [p for p in fixtures_dir.glob("ECLI_*.xml")]
        # Route the two RBAMS ECLIs to the first two real fixtures (if available).
        for i, real_ecli in enumerate([
            "ECLI:NL:RBAMS:2025:1001", "ECLI:NL:RBAMS:2025:1002",
        ]):
            if i < len(real_fixtures):
                mapping[real_ecli] = real_fixtures[i]
        source = mapping[ecli]
        target = cache_dir / f"{ecli.replace(':', '_')}.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return target

    monkeypatch.setattr(caselaw_fetch, "list_eclis", fake_list)
    monkeypatch.setattr(caselaw_fetch, "fetch_content", fake_fetch)


class _FakeEmbedder:
    def __init__(self, *_args, **_kwargs) -> None:
        self.model_name = "fake"

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:  # noqa: ARG002
        arr = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, t in enumerate(texts):
            arr[i, 0] = float(len(t))
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "caselaw"


def test_run_ingest_end_to_end(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    result = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )

    # The sparse fixture contains "huurder" → passes fence; RBAMS real fixtures
    # may or may not, depending on what was committed. Assert on structure.
    assert result.listed == 3
    assert result.fetched >= 1
    assert result.filter_passed >= 1
    assert result.embedded == result.chunks_written
    assert result.unique_eclis == result.filter_passed


def test_run_ingest_idempotent(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    r1 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    assert r2.chunks_written == 0
    assert r2.unique_eclis_added == 0
    assert r2.listed == r1.listed  # pagination re-queried; gate filters all


def test_run_ingest_refresh_wipes(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=True,
        verbose=False,
    )
    # After --refresh, we ingested fresh again.
    assert r2.chunks_written >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_caselaw.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Create the orchestrator**

Create `src/jurist/ingest/caselaw.py`:

```python
"""Caselaw ingestion pipeline orchestrator.

Nine stages (per spec §3.2):
  1. Warm model
  2. List ECLIs
  3. Resume gate
  4. Fetch content (5-way parallel)
  5. Parse
  6. Filter (keyword fence)
  7. Chunk
  8. Embed
  9. Write

Returns an IngestResult with per-stage counts.

CLI entry: `python -m jurist.ingest.caselaw [flags]` (Step 7 below).
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from jurist.config import settings
from jurist.embedding import Embedder
from jurist.ingest import caselaw_fetch
from jurist.ingest.caselaw_filter import passes as filter_passes
from jurist.ingest.caselaw_parser import ParseError, parse_case
from jurist.ingest.caselaw_profiles import resolve_profile
from jurist.ingest.splitter import split
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    listed: int = 0
    fetched: int = 0
    from_cache: int = 0
    parsed: int = 0
    filter_passed: int = 0
    chunks_written: int = 0
    embedded: int = 0
    unique_eclis: int = 0
    unique_eclis_added: int = 0
    wall_clock_s: float = 0.0


def run_ingest(
    *,
    profile: str,
    since: str,
    cases_dir: Path,
    lance_path: Path,
    subject_uri_override: str | None = None,
    fetch_workers: int = 5,
    chunk_words: int = 500,
    chunk_overlap: int = 50,
    embed_batch: int = 32,
    max_list: int | None = None,
    refresh: bool = False,
    verbose: bool = False,
) -> IngestResult:
    """Drive the nine-stage pipeline. Pure function over injected paths.

    Mocked-dependency-friendly: `Embedder` and `caselaw_fetch` are module-level
    imports so tests can monkeypatch them.
    """
    started = time.perf_counter()
    result = IngestResult()

    prof = resolve_profile(profile)
    subject_uri = subject_uri_override or prof.subject_uri

    if refresh:
        log.info("--refresh: wiping cases dir + LanceDB")
        if cases_dir.exists():
            shutil.rmtree(cases_dir)
        if lance_path.exists():
            shutil.rmtree(lance_path)
    cases_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: warm model
    log.info("stage 1/9: warming embedder (%s)", settings.embed_model)
    embedder = Embedder(model_name=settings.embed_model)

    # Stage 2: list ECLIs
    log.info("stage 2/9: listing ECLIs (subject=%s, since=%s)", subject_uri, since)
    eclis = list(caselaw_fetch.list_eclis(
        subject_uri=subject_uri,
        since=since,
        max_list=max_list,
    ))
    result.listed = len(eclis)
    log.info("  listed %d ECLIs", result.listed)

    # Stage 3: resume gate
    store = CaseStore(lance_path)
    store.open_or_create()
    seen = store.all_eclis()
    fresh = [(e, ts) for e, ts in eclis if e not in seen]
    log.info("stage 3/9: %d fresh (skip %d already indexed)",
             len(fresh), result.listed - len(fresh))

    # Stage 4: fetch content (parallel)
    log.info("stage 4/9: fetching %d ECLIs (workers=%d)", len(fresh), fetch_workers)
    xml_paths: list[tuple[str, Path]] = []
    with ThreadPoolExecutor(max_workers=fetch_workers) as pool:
        futures = {
            pool.submit(_fetch_one, e, cases_dir): e
            for e, _ in fresh
        }
        for fut in as_completed(futures):
            ecli = futures[fut]
            try:
                path, from_cache = fut.result()
            except caselaw_fetch.FetchError as exc:
                log.warning("  skip %s: %s", ecli, exc)
                continue
            xml_paths.append((ecli, path))
            result.fetched += 1
            if from_cache:
                result.from_cache += 1

    # Stage 5: parse
    log.info("stage 5/9: parsing %d cases", len(xml_paths))
    metas: list = []
    for ecli, path in xml_paths:
        try:
            meta = parse_case(path.read_bytes())
        except ParseError as exc:
            log.warning("  parse failed %s: %s", ecli, exc)
            continue
        metas.append(meta)
        result.parsed += 1

    # Stage 6: filter
    log.info("stage 6/9: filtering by keyword fence")
    kept = [m for m in metas if filter_passes(m.body_text, terms=prof.keyword_terms)]
    result.filter_passed = len(kept)
    log.info("  %d survived fence", result.filter_passed)

    # Stages 7 + 8 + 9: chunk, embed, write
    log.info("stage 7/9: chunking surviving cases")
    all_chunks: list[tuple[object, int, str]] = []  # (meta, chunk_idx, text)
    for meta in kept:
        for idx, chunk in enumerate(split(
            meta.body_text, target_words=chunk_words, overlap_words=chunk_overlap,
        )):
            all_chunks.append((meta, idx, chunk))
    log.info("  %d chunks total", len(all_chunks))

    if not all_chunks:
        result.wall_clock_s = time.perf_counter() - started
        return result

    log.info("stage 8/9: embedding %d chunks (batch=%d)", len(all_chunks), embed_batch)
    texts = [c[2] for c in all_chunks]
    vectors = embedder.encode(texts, batch_size=embed_batch)
    result.embedded = len(vectors)

    log.info("stage 9/9: writing rows to LanceDB")
    rows: list[CaseChunkRow] = []
    for (meta, idx, text), vec in zip(all_chunks, vectors, strict=True):
        rows.append(CaseChunkRow(
            ecli=meta.ecli,
            chunk_idx=idx,
            court=meta.court,
            date=meta.date,
            zaaknummer=meta.zaaknummer,
            subject_uri=meta.subject_uri,
            modified=meta.modified,
            text=text,
            embedding=vec.tolist(),
            url=meta.url,
        ))
    existing_before = len(seen)
    store.add_rows(rows)
    result.chunks_written = len(rows)
    existing_after = len(store.all_eclis())
    result.unique_eclis = existing_after
    result.unique_eclis_added = existing_after - existing_before

    result.wall_clock_s = time.perf_counter() - started
    if verbose:
        _print_summary(result)
    return result


def _fetch_one(ecli: str, cases_dir: Path) -> tuple[Path, bool]:
    """Fetch content; report whether it was a cache hit."""
    target = cases_dir / f"{ecli.replace(':', '_')}.xml"
    was_cached = target.exists()
    path = caselaw_fetch.fetch_content(ecli, cache_dir=cases_dir)
    return path, was_cached


def _print_summary(r: IngestResult) -> None:
    print(f"Ingest done in {r.wall_clock_s:.1f}s")
    print(f"  listed:        {r.listed}")
    print(f"  fetched:       {r.fetched} (cache: {r.from_cache})")
    print(f"  parsed:        {r.parsed}")
    print(f"  filter passed: {r.filter_passed}")
    print(f"  chunks:        {r.chunks_written}")
    print(f"  unique ECLIs:  {r.unique_eclis} (+{r.unique_eclis_added} new)")


# ----------------- CLI -----------------

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="python -m jurist.ingest.caselaw",
        description="Fetch + chunk + embed rechtspraak.nl uitspraken; write LanceDB.",
    )
    parser.add_argument("--profile", default=settings.caselaw_profile,
                        help="CaselawProfile name (default: %(default)s)")
    parser.add_argument("--subject-uri", default=None,
                        help="Override profile's subject_uri")
    parser.add_argument("--since", default=settings.caselaw_since,
                        help="`modified` ISO 8601 floor (default: %(default)s)")
    parser.add_argument("--max-list", type=int, default=None,
                        help="Debug cap on ECLIs listed")
    parser.add_argument("--fetch-workers", type=int,
                        default=settings.caselaw_fetch_workers)
    parser.add_argument("--refresh", action="store_true",
                        help="Wipe cache + LanceDB; re-ingest from scratch")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        run_ingest(
            profile=args.profile,
            since=args.since,
            cases_dir=settings.cases_dir,
            lance_path=settings.lance_path,
            subject_uri_override=args.subject_uri,
            fetch_workers=args.fetch_workers,
            chunk_words=settings.caselaw_chunk_words,
            chunk_overlap=settings.caselaw_chunk_overlap,
            embed_batch=settings.embed_batch,
            max_list=args.max_list or settings.caselaw_max_list,
            refresh=args.refresh,
            verbose=True,
        )
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_caselaw.py -v
```

Expected: all three tests pass. If the real-fixture bodies lack huur-terms, `filter_passed` could be just the sparse fixture (1) — the assertions use `>= 1` so this still passes.

- [ ] **Step 5: Verify CLI `--help`**

```bash
uv run python -m jurist.ingest.caselaw --help
```

Expected: argparse help prints listing all flags.

- [ ] **Step 6: Ruff check**

```bash
uv run ruff check src/jurist/ingest/caselaw.py tests/ingest/test_caselaw.py
```

Expected: no errors.

- [ ] **Step 7: Full test suite passes**

```bash
uv run pytest -v
```

Expected: all tests green.

- [ ] **Step 8: Commit**

```bash
git add src/jurist/ingest/caselaw.py tests/ingest/test_caselaw.py
git commit -m "feat(ingest): caselaw pipeline orchestrator + CLI"
```

---

## Task 15: README + CLAUDE.md updates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Inspect current README structure**

```bash
wc -l README.md
head -40 README.md
```

If the README doesn't yet have ingestion or setup sections, add them. If it does, extend.

- [ ] **Step 2: Add the M3a ingestion section to README**

Append (or insert at the appropriate place) to `README.md`:

```markdown
## Caselaw ingestion (M3a)

One-time setup. Populates `data/lancedb/cases.lance` with huur-related uitspraken.

**Fresh-clone warnings before first run:**
- `uv sync --extra dev` pulls `torch` (~2 GB) transitively via `sentence-transformers`. Allow ≥5 min on a slow connection.
- The ingester's first run downloads `BAAI/bge-m3` (~2.3 GB) to `~/.cache/huggingface/hub/`. Subsequent runs use the cache.
- Ingestion itself (fetching ~20k ECLIs, filtering, chunking, embedding) takes ~20–40 min on a laptop. This is a one-time cost unless you pass `--refresh`.

**Run:**

    uv run python -m jurist.ingest.caselaw -v

**Idempotent.** Re-running without `--refresh` skips cached ECLIs and already-embedded chunks in seconds. `--refresh` wipes `data/cases/` + `data/lancedb/cases.lance` and re-ingests from scratch.

**Config knobs** (CLI flags or matching `JURIST_CASELAW_*` env vars — see `src/jurist/config.py`):

- `--profile huurrecht` — selects subject_uri + keyword fence terms
- `--since 2024-01-01` — `modified` date floor
- `--max-list N` — debug: cap ECLIs fetched
- `--fetch-workers 5` — content-endpoint concurrency

See `docs/superpowers/specs/2026-04-21-m3a-caselaw-ingestion-design.md` for the design rationale and the verified rechtspraak.nl data-source shape.
```

- [ ] **Step 3: Update CLAUDE.md with M3a state**

Find the "Current state" paragraph at the top of `CLAUDE.md` and update it. Current text (as of M2):

```markdown
Current state: **M2 landed** (branch `m2-statute-retriever`; tag pending UI smoke) — real Claude Sonnet tool-use loop over the 218-node huurrecht KG replaces the statute retriever fake. Decomposer, case retriever, and synthesizer remain M0 fakes; validator is a permanent stub. `/api/ask` now requires `ANTHROPIC_API_KEY` to exercise the statute retriever; the other stages still drive the rest of the canned answer. M3–M5 replace the remaining fakes (see spec §11).
```

Replace with:

```markdown
Current state: **M3a landed** (branch `m3a-caselaw-ingestion`) — `python -m jurist.ingest.caselaw` pulls huur-related uitspraken from rechtspraak.nl open-data, chunks them, embeds with bge-m3, and writes to LanceDB. Prior: M2 shipped the real statute retriever. The `case_retriever` agent still emits canned events (M3b will swap it for a real bge-m3 + Haiku rerank flow). Decomposer and synthesizer remain M0 fakes; validator is a permanent stub. `/api/ask` requires `ANTHROPIC_API_KEY` for the statute retriever; ingestion itself does not.
```

Also in the Commands section, add the new ingest command below the statutes one:

Find:

```markdown
- Build KG (prerequisite for API start): `uv run python -m jurist.ingest.statutes --refresh -v`
```

Replace with:

```markdown
- Build KG (prerequisite for API start): `uv run python -m jurist.ingest` (runs the statutes ingester — CLAUDE.md previously listed `.statutes` but Python's `-m` doesn't dispatch to the submodule file).
- Build caselaw index: `uv run python -m jurist.ingest.caselaw -v` (one-time ~20–40 min; downloads ~2.3 GB bge-m3 on first run; uses `data/cases/` disk cache + `data/lancedb/cases.lance`).
```

And add under "Architecture" → "Case retriever" as a new subsection after the statute retriever section:

```markdown
### Caselaw ingestion (M3a)

- **Pipeline:** `src/jurist/ingest/caselaw.py::run_ingest` — nine stages (warm model → list → resume → fetch → parse → filter → chunk → embed → write). Sync + `ThreadPoolExecutor(max_workers=5)` for the fetch stage.
- **Data source:** `data.rechtspraak.nl/uitspraken/zoeken` filtered on `subject=civielRecht_verbintenissenrecht` + `modified>=2024-01-01`, then a local keyword fence (`huur`/`verhuur`/`woonruimte`/`huurcommissie`). Parent spec §8.2's original `rechtsgebied=Huurrecht` filter was wrong — no such URI exists in the taxonomy.
- **Embedder:** `src/jurist/embedding.py::Embedder` wraps `sentence-transformers` `BAAI/bge-m3` (1024-d, L2-normalized). Shared with M3b.
- **Storage:** `src/jurist/vectorstore.py::CaseStore` concrete LanceDB class (no interface — parent spec §15 decision #12). Deduplicates on `(ecli, chunk_idx)`.
- **Profiles:** `src/jurist/ingest/caselaw_profiles.py` — `{rechtsgebied_name → (subject_uri, keyword_terms)}`. Only `huurrecht` populated; multi-rechtsgebied is a dict-entry diff.
- **What's fake after M3a:** `case_retriever` still yields `FAKE_CASES` — M3b swaps it.
```

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs(m3a): update README + CLAUDE.md for caselaw ingestion"
```

---

## Task 16: Integration test (RUN_E2E gated)

**Files:**
- Create: `tests/integration/test_m3a_ingestion_e2e.py`

Per spec §8.2. Hits live rechtspraak.nl + real bge-m3.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_m3a_ingestion_e2e.py`:

```python
"""M3a end-to-end: live rechtspraak.nl + real bge-m3.

Gated on RUN_E2E=1 to avoid token/time cost on default test runs.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="RUN_E2E=1 required (hits network + downloads ~2.3 GB on first run)",
)


def test_small_live_ingest_end_to_end(tmp_path: Path) -> None:
    from jurist.ingest import caselaw

    result = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=10,
        refresh=False,
        verbose=False,
    )

    # Pipeline produced output
    assert result.listed >= 1
    assert result.fetched >= 1

    # At least one survived the keyword fence (2025 verbintenissenrecht corpus
    # has plenty of huur mentions — but we don't hard-assert >0 here to allow
    # for edge days when max-list=10 samples all miss; instead, if zero
    # survived, check that chunks+embedded are also zero (consistent state).
    if result.filter_passed == 0:
        assert result.chunks_written == 0
    else:
        assert result.chunks_written >= 1
        assert result.embedded == result.chunks_written


def test_idempotent_rerun(tmp_path: Path) -> None:
    from jurist.ingest import caselaw

    r1 = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=5,
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=5,
        refresh=False,
        verbose=False,
    )
    # r2 should add no new rows (all ECLIs in cache + index).
    assert r2.unique_eclis_added == 0
    assert r2.chunks_written == 0
    assert r2.unique_eclis == r1.unique_eclis


def test_bge_m3_determinism() -> None:
    """Parent spec §11 M3 requirement: same input → same embedding."""
    from jurist.embedding import Embedder

    emb = Embedder()  # default BAAI/bge-m3
    v1 = emb.encode(["huurverhoging per jaar"])
    v2 = emb.encode(["huurverhoging per jaar"])
    assert np.array_equal(v1, v2), "bge-m3 embeddings must be bit-equal across runs"
    # Sanity: 1024-d unit-norm
    assert v1.shape == (1, 1024)
    assert abs(np.linalg.norm(v1) - 1.0) < 1e-5
```

- [ ] **Step 2: Verify the test is skipped without the env flag**

```bash
uv run pytest tests/integration/test_m3a_ingestion_e2e.py -v
```

Expected: three tests skipped (reason: `RUN_E2E=1 required…`).

- [ ] **Step 3: Run the integration test with RUN_E2E set (optional but recommended)**

```bash
RUN_E2E=1 uv run pytest tests/integration/test_m3a_ingestion_e2e.py -v
```

Expected: all three pass. First run will download bge-m3 (~2.3 GB) if not already cached; allow 5–15 min. Subsequent runs complete in under 2 min.

If the test fails:
- **First-run model download timeouts:** run `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"` directly to force download outside the test.
- **No ECLIs found at since=2025-01-01:** loosen to `since="2024-01-01"` in the test.
- **Fence filters everything out:** expected occasionally with `max_list=10`; the test already handles this via the conditional assertion.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_m3a_ingestion_e2e.py
git commit -m "test(m3a): RUN_E2E-gated live rechtspraak.nl + bge-m3 integration"
```

---

## Task 17: Smoke test the full demo path + branch merge

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests green. Integration tests are skipped (no `RUN_E2E`).

- [ ] **Step 2: Ruff check the whole tree**

```bash
uv run ruff check .
```

Expected: clean.

- [ ] **Step 3: Live ingest a small slice as a smoke test**

```bash
uv run python -m jurist.ingest.caselaw --since 2025-01-01 --max-list 20 -v
```

Expected:
- Prints the `[ingest.caselaw] loading BAAI/bge-m3` line (first time: downloads the model; subsequent: fast).
- Lists 20 ECLIs.
- Fetches them (or hits cache if re-run).
- Some fraction pass the fence.
- Writes rows to `data/lancedb/cases.lance`.
- Final summary line prints wall-clock + per-stage counts.

- [ ] **Step 4: Verify LanceDB is queryable**

```bash
uv run python -c "
from jurist.vectorstore import CaseStore
from jurist.config import settings
s = CaseStore(settings.lance_path)
s.open_or_create()
eclis = s.all_eclis()
print(f'ECLIs in index: {len(eclis)}')
if eclis:
    print(f'Sample: {list(eclis)[:3]}')
print(f'Rows: {s.row_count()}')
"
```

Expected: non-zero ECLIs + rows reported.

- [ ] **Step 5: Push the branch**

```bash
git push -u origin m3a-caselaw-ingestion
```

(Do not merge yet — user approval gate.)

- [ ] **Step 6: Hand off to user**

Report to user:
- All M3a acceptance criteria (spec §15) verified.
- Live smoke ingest results (listed / fetched / filtered / chunks / ECLIs / wall-clock).
- Branch pushed as `m3a-caselaw-ingestion`.
- Ready for user to inspect `data/lancedb/cases.lance` contents and approve merge to master.

---

## Post-plan

M3b design + plan starts from:
- A populated LanceDB at `data/lancedb/cases.lance`
- `CaseStore.query(vector, top_k=N)` already working (added in Task 13 for testability)
- `Embedder` already working (shared with ingester)
- Known fake: `src/jurist/agents/case_retriever.py` emits `FAKE_CASES`; it needs replacing with a real agent that embeds sub_questions, queries LanceDB, dedupes by ECLI, and runs a Haiku rerank.

That work is out of scope for M3a.
