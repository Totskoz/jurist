# Jurist

Grounded Dutch huurrecht Q&A — multi-agent demo.

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
