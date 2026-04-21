"""Tests for list-endpoint pagination."""
from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager

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


def test_list_eclis_encodes_fragment_in_subject_uri(monkeypatch) -> None:
    """Subject URIs contain '#' as a rechtsgebied fragment delimiter.
    This must be percent-encoded in the query string, else urllib treats
    it as a URL fragment and the subject param is silently truncated.
    """
    from jurist.ingest import caselaw_fetch

    captured_paths: list[str] = []

    class CapturingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            captured_paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/atom+xml")
            self.send_header("Content-Length", str(len(FEED_EMPTY)))
            self.end_headers()
            self.wfile.write(FEED_EMPTY)

        def log_message(self, *args) -> None:  # noqa: ARG002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), CapturingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(
            caselaw_fetch, "ZOEKEN_URL", f"http://127.0.0.1:{port}/zoeken"
        )
        list(caselaw_fetch.list_eclis(
            subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
            since="2024-01-01",
            page_size=10,
        ))
    finally:
        server.shutdown()
        server.server_close()

    # The '#' in the subject URI must be percent-encoded; otherwise urllib
    # splits it off as a URL fragment and the server sees a truncated query.
    assert any("%23civielRecht_verbintenissenrecht" in p for p in captured_paths), (
        f"Fragment not properly encoded. Captured paths: {captured_paths}"
    )
    # Negative check: raw '#' should not appear in any GET path's query.
    for path in captured_paths:
        # path is like "/zoeken?subject=...&modified=...". The '#' should be escaped.
        query_start = path.find("?")
        query = path[query_start + 1:] if query_start >= 0 else ""
        assert "#" not in query, f"Raw '#' in query: {path}"
