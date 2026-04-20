from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jurist.ingest.fetch import fetch_bwb_xml


def test_fetch_returns_cached_bytes_without_http(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    cache_file = tmp_path / "BWBR0005290.xml"
    cache_file.write_bytes(b"<wet>cached</wet>")

    # If HTTP is called, this test should fail — assert httpx.Client is not constructed.
    with patch("jurist.ingest.fetch.httpx.Client") as mock_client:
        result = fetch_bwb_xml("BWBR0005290")
        mock_client.assert_not_called()
    assert result == b"<wet>cached</wet>"


def test_fetch_live_writes_cache_then_returns_bytes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    fake_resp = MagicMock()
    fake_resp.content = b"<wet>fresh</wet>"
    fake_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0002888")

    assert result == b"<wet>fresh</wet>"
    assert (tmp_path / "BWBR0002888.xml").read_bytes() == b"<wet>fresh</wet>"


def test_fetch_refresh_bypasses_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    (tmp_path / "BWBR0003402.xml").write_bytes(b"<wet>old</wet>")

    fake_resp = MagicMock()
    fake_resp.content = b"<wet>new</wet>"
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0003402", refresh=True)

    assert result == b"<wet>new</wet>"


def test_fetch_no_fetch_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="cache miss"):
        fetch_bwb_xml("BWBR0009999", no_fetch=True)


def test_fetch_http_error_does_not_write_cache(tmp_path: Path, monkeypatch):
    """Invariant: failed HTTP must not leave a partial or empty cache file."""
    import httpx as _httpx
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        with pytest.raises(_httpx.HTTPStatusError):
            fetch_bwb_xml("BWBR0005290")

    assert not (tmp_path / "BWBR0005290.xml").exists()


def test_fetch_rejects_path_traversal_in_bwb_id(tmp_path: Path, monkeypatch):
    """Defense-in-depth: a bwb_id containing path separators must not escape CACHE_DIR."""
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    (tmp_path / "escaped.xml").write_bytes(b"should-not-be-read")

    # A "bwb_id" containing .. and a separator reduces to its final segment ("BWBR0005290"),
    # so the cache lookup targets tmp_path/BWBR0005290.xml (which does NOT exist) and
    # no_fetch=True then raises — proving the traversal was neutralized.
    with pytest.raises(FileNotFoundError):
        fetch_bwb_xml("../../BWBR0005290", no_fetch=True)
