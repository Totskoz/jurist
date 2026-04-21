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
