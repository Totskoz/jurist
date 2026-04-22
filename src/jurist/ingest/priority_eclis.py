"""M5 — priority-ECLI curated-list ingest (AQ3).

Bypasses the list/fence stages of the regular caselaw ingest. Fetches
ECLIs by name, parses, chunks, embeds, and writes to LanceDB. Idempotent
via existing (ecli, chunk_idx) dedupe.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from jurist.embedding import Embedder
from jurist.ingest.caselaw_fetch import fetch_content
from jurist.ingest.caselaw_parser import ParseError, parse_case
from jurist.ingest.splitter import split
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore

_log = logging.getLogger(__name__)
_ECLI_RE = re.compile(r"^ECLI:NL:[A-Z]+:\d{4}:\d+$")


@dataclass(frozen=True)
class PriorityIngestResult:
    fetched: int
    parsed: int
    chunked: int
    embedded: int
    written: int


def load_eclis(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _ECLI_RE.match(line):
            raise ValueError(f"invalid ECLI on line {raw!r}")
        out.append(line)
    return out


def run_priority_ingest(
    eclis_path: Path,
    *,
    lance_path: Path,
    cache_dir: Path,
    embedder: Embedder,
    target_words: int = 500,
    overlap_words: int = 50,
) -> PriorityIngestResult:
    """Fetch → parse → chunk → embed → write for each ECLI in the list.

    No fence — priority list is curated. No subject filter either. Each
    ECLI's XML is cached to {cache_dir}/{ecli}.xml for resume/audit.
    Synchronous (sequential): priority lists are small (~20-30 ECLIs).
    """
    eclis = load_eclis(eclis_path)
    cache_dir.mkdir(parents=True, exist_ok=True)

    store = CaseStore(lance_path)
    store.open_or_create()

    fetched = parsed = chunked = embedded = written = 0
    indexed = store.all_eclis()
    bar = tqdm(eclis, desc="priority", unit="ecli", mininterval=0.5)
    for ecli in bar:
        if ecli in indexed:
            continue
        try:
            xml_path = fetch_content(ecli, cache_dir=cache_dir)
        except Exception:
            _log.warning("fetch failed for %s", ecli, exc_info=True)
            continue
        fetched += 1

        try:
            meta = parse_case(xml_path.read_bytes())
        except ParseError:
            _log.warning("parse failed for %s", ecli, exc_info=True)
            continue
        parsed += 1

        chunks = split(meta.body_text, target_words=target_words, overlap_words=overlap_words)
        chunked += len(chunks)
        if not chunks:
            continue

        vectors = embedder.encode(chunks)
        embedded += len(vectors)

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
        written += len(rows)
        bar.set_postfix(fetched=fetched, written=written)

    return PriorityIngestResult(
        fetched=fetched, parsed=parsed, chunked=chunked,
        embedded=embedded, written=written,
    )
