"""Dry-run probe for `--refilter-cache`.

Simulates the refilter loop WITHOUT embedding or writing: scan all cached
XMLs → skip already-indexed → parse → apply current fence → count chunks
for cases that would pass. Prints a summary and projects embed runtime
from a configurable chunks/sec anchor.

Read-only; safe to run. CPU-only, no network, no model load.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from jurist.config import settings
from jurist.ingest.caselaw_filter import passes as filter_passes
from jurist.ingest.caselaw_parser import ParseError, parse_case
from jurist.ingest.caselaw_profiles import resolve_profile
from jurist.ingest.splitter import split
from jurist.vectorstore import CaseStore


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="python scripts/dryrun_refilter.py",
        description=(
            "Count how many cases --refilter-cache would embed without "
            "actually running the embedder."
        ),
    )
    parser.add_argument(
        "--profile",
        default=settings.caselaw_profile,
        help="CaselawProfile name (default: %(default)s)",
    )
    parser.add_argument(
        "--throughput",
        type=float,
        default=0.67,
        help="chunks/sec estimate for runtime projection (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    profile = resolve_profile(args.profile)
    cache_dir: Path = settings.cases_dir
    xml_paths = sorted(cache_dir.glob("*.xml"))
    if not xml_paths:
        print(f"no XMLs found in {cache_dir}", file=sys.stderr)
        return 1

    store = CaseStore(settings.lance_path)
    store.open_or_create()
    indexed = store.all_eclis()

    scanned = 0
    skipped_indexed = 0
    parsed = 0
    parse_failed = 0
    passed = 0
    total_chunks = 0

    bar = tqdm(xml_paths, desc="probing", unit="xml", mininterval=0.5)
    for xml_path in bar:
        scanned += 1
        ecli = xml_path.stem.replace("_", ":")
        if ecli in indexed:
            skipped_indexed += 1
            continue
        try:
            meta = parse_case(xml_path.read_bytes())
        except ParseError:
            parse_failed += 1
            continue
        parsed += 1
        if not filter_passes(meta.body_text, terms=profile.keyword_terms):
            continue
        passed += 1
        chunks = split(meta.body_text, target_words=500, overlap_words=50)
        total_chunks += len(chunks)
        bar.set_postfix(passed=passed, chunks=total_chunks)

    throughput = max(args.throughput, 1e-9)
    eta_seconds = total_chunks / throughput
    print()
    print(f"profile: {profile.name}")
    print(f"fence terms ({len(profile.keyword_terms)}):")
    for t in profile.keyword_terms:
        print(f"  - {t}")
    print()
    print(f"  scanned XMLs:         {scanned:>6}")
    print(f"  already indexed:      {skipped_indexed:>6}")
    print(f"  parse-failed:         {parse_failed:>6}")
    print(f"  parsed (unindexed):   {parsed:>6}")
    print(f"  would pass new fence: {passed:>6}")
    print(f"  chunks to embed:      {total_chunks:>6}")
    print(
        f"  est. embed runtime:   {eta_seconds / 60:>6.1f} min  "
        f"({eta_seconds / 3600:.2f} h at {throughput} chunks/sec)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
