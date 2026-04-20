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
