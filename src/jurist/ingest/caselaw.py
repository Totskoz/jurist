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
from jurist.ingest.caselaw_profiles import CaselawProfile, resolve_profile
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
            except Exception as exc:
                # Belt-and-braces: a long ingest shouldn't abort on an
                # unexpected per-ECLI error. Log + skip, keep the rest going.
                log.exception("  skip %s (unexpected): %s", ecli, exc)
                continue
            xml_paths.append((ecli, path))
            result.fetched += 1
            if from_cache:
                result.from_cache += 1

    # Stage 5: parse
    log.info("stage 5/9: parsing %d cases", len(xml_paths))
    metas: list = []
    for listing_ecli, path in xml_paths:
        try:
            meta = parse_case(path.read_bytes())
        except ParseError as exc:
            log.warning("  parse failed %s: %s", listing_ecli, exc)
            continue
        # Prefer the listing ECLI (from the search index) as canonical identity.
        # In production these match; in tests fixtures may embed a different
        # identifier, so we override with the listing ECLI to keep the resume
        # gate coherent. Also fix the url so it reflects the canonical ECLI.
        if meta.ecli != listing_ecli:
            from dataclasses import replace as _dc_replace
            canonical_url = (
                f"https://uitspraken.rechtspraak.nl/details?id={listing_ecli}"
            )
            meta = _dc_replace(meta, ecli=listing_ecli, url=canonical_url)
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


def run_refilter_cache(
    *,
    cache_dir: Path,
    lance_path: Path,
    profile: CaselawProfile,
    embedder: Embedder,
    target_words: int = 500,
    overlap_words: int = 50,
) -> dict:
    """M5 — re-run fence/chunk/embed/write over already-cached XMLs.

    Skips list + fetch entirely. Emits stats dict. Expected runtime:
    ~2-4h on a 16 GB host depending on delta size.
    """
    store = CaseStore(lance_path)
    store.open_or_create()
    counts = {
        "scanned": 0, "parsed": 0, "passed_fence": 0,
        "chunked": 0, "embedded": 0, "written": 0,
    }
    for xml_path in sorted(cache_dir.glob("*.xml")):
        counts["scanned"] += 1
        ecli = xml_path.stem.replace("_", ":")
        if store.contains_ecli(ecli):
            continue
        try:
            meta = parse_case(xml_path.read_bytes())
        except ParseError:
            log.warning("parse failed for %s", ecli, exc_info=True)
            continue
        counts["parsed"] += 1

        if not filter_passes(meta.body_text, terms=profile.keyword_terms):
            continue
        counts["passed_fence"] += 1

        chunks = split(meta.body_text, target_words=target_words, overlap_words=overlap_words)
        counts["chunked"] += len(chunks)
        if not chunks:
            continue

        vectors = embedder.encode(chunks)
        counts["embedded"] += len(vectors)

        rows = [
            CaseChunkRow(
                ecli=ecli,
                chunk_idx=i,
                court=meta.court,
                date=meta.date,
                zaaknummer=meta.zaaknummer,
                subject_uri=meta.subject_uri,
                modified=meta.modified,
                text=chunk,
                embedding=list(vec),
                url=meta.url,
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
        ]
        store.add_rows(rows)
        counts["written"] += len(rows)
    return counts


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
    parser.add_argument(
        "--priority-eclis",
        type=Path,
        default=None,
        help="Path to a text file of ECLIs to fetch + ingest bypassing list/fence stages. "
             "Idempotent. Reuses the fetch cache.",
    )
    parser.add_argument(
        "--refilter-cache",
        action="store_true",
        help="Skip list + fetch; re-run fence/chunk/embed/write over "
             "previously-parsed XMLs in data/cases/. Adds only delta chunks.",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.priority_eclis is not None:
        if not args.priority_eclis.exists():
            parser.error(f"--priority-eclis path does not exist: {args.priority_eclis}")
        from jurist.ingest.priority_eclis import run_priority_ingest
        result = run_priority_ingest(
            args.priority_eclis,
            lance_path=settings.lance_path,
            cache_dir=settings.cases_dir,
            embedder=Embedder(model_name=settings.embed_model),
        )
        log.info("priority ingest complete: %s", result)
        return 0

    if args.refilter_cache:
        result = run_refilter_cache(
            cache_dir=settings.cases_dir,
            lance_path=settings.lance_path,
            profile=resolve_profile(args.profile),
            embedder=Embedder(model_name=settings.embed_model),
        )
        log.info("refilter-cache complete: %s", result)
        return 0

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
