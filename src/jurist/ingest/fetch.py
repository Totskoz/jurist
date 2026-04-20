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
    # Defense-in-depth: strip any directory components that could escape CACHE_DIR.
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

    # Atomic write: write to a .tmp sibling, then rename. Prevents torn reads on crash.
    tmp_path = cache_path.with_suffix(".tmp")
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(cache_path)
    finally:
        # If replace succeeded, tmp_path no longer exists; missing_ok covers that.
        tmp_path.unlink(missing_ok=True)
    return data


_LATEST_ITEM_RE = re.compile(r'_latestItem="([^"]+)"')


def _parse_latest_item(manifest_xml: str) -> str:
    """Extract the _latestItem attribute from a BWB manifest root element."""
    m = _LATEST_ITEM_RE.search(manifest_xml)
    if not m:
        raise ValueError("BWB manifest missing _latestItem attribute")
    return m.group(1)
