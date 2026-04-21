"""HTTP clients for rechtspraak.nl open-data endpoints.

Two functions:
  - list_eclis: paginated ECLI discovery via the zoeken endpoint.
  - fetch_content: full uitspraak XML by ECLI, with disk cache.

Stdlib-only (urllib + xml.etree); 5-way parallelism for fetch_content
via ThreadPoolExecutor (Task 9).
"""
from __future__ import annotations

import logging
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
            updated = (
                updated_elem.text.strip()
                if updated_elem is not None and updated_elem.text
                else ""
            )
            yield (ecli, updated)
            emitted += 1
            if max_list is not None and emitted >= max_list:
                return
        offset += page_size


def fetch_content(ecli: str) -> bytes:  # pragma: no cover - placeholder for Task 9
    """Filled in Task 9."""
    raise NotImplementedError
