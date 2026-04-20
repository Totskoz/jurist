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
    """Run the full pipeline. Returns the written snapshot."""
    selected = bwb_ids or list(BWB_ALLOWLIST.keys())
    started = time.perf_counter()

    # Pass 1: fetch + version gating
    fetched: dict[str, tuple[bytes, str]] = {}
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
        and set(existing.source_versions.keys()) == set(fetched.keys())
    ):
        if verbose:
            print("Ingest: no changes; skipping parse.")
        return existing

    # Pass 2: parse each BWB
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

    # Pass 3: edges
    regex_edges = extract_regex_edges(all_nodes)
    merged = merge_edges(all_explicit, regex_edges)

    # Guard: drop edges that reference unknown nodes (e.g., short-form extrefs
    # whose target is in the KG but under a different article_id path, or
    # cross-BWB refs to un-ingested BWBs).
    known_ids = {n.article_id for n in all_nodes}
    dangling = [e for e in merged if e.to_id not in known_ids]
    if dangling and verbose:
        print(f"Ingest: dropping {len(dangling)} edges to unknown nodes.")
    merged = [e for e in merged if e.to_id in known_ids]

    # Repopulate ArticleNode.outgoing_refs from the merged edge list
    refs_by_source: dict[str, list[str]] = {}
    for e in merged:
        refs_by_source.setdefault(e.from_id, []).append(e.to_id)
    for n in all_nodes:
        n.outgoing_refs = refs_by_source.get(n.article_id, [])

    # Pass 4: serialize
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
        if "/" in n.article_id:
            flat = n.article_id.split("/", 1)[1].replace("/", "-")
        else:
            flat = n.article_id
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
