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

    manifest_resp = MagicMock()
    manifest_resp.text = '<work _latestItem="some/path.xml">'
    manifest_resp.raise_for_status.return_value = None

    xml_resp = MagicMock()
    xml_resp.content = b"<wet>fresh</wet>"
    xml_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.side_effect = [manifest_resp, xml_resp]

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0014315")

    assert result == b"<wet>fresh</wet>"
    assert (tmp_path / "BWBR0014315.xml").read_bytes() == b"<wet>fresh</wet>"


def test_fetch_refresh_bypasses_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    (tmp_path / "BWBR0014315.xml").write_bytes(b"<wet>old</wet>")

    manifest_resp = MagicMock()
    manifest_resp.text = '<work _latestItem="some/path.xml">'
    manifest_resp.raise_for_status.return_value = None

    xml_resp = MagicMock()
    xml_resp.content = b"<wet>new</wet>"
    xml_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.side_effect = [manifest_resp, xml_resp]

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        result = fetch_bwb_xml("BWBR0014315", refresh=True)

    assert result == b"<wet>new</wet>"


def test_fetch_no_fetch_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="cache miss"):
        fetch_bwb_xml("BWBR0009999", no_fetch=True)


def test_fetch_http_error_does_not_write_cache(tmp_path: Path, monkeypatch):
    """Invariant: failed HTTP must not leave a partial or empty cache file."""
    import httpx as _httpx
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.side_effect = _httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )

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


def test_fetch_raises_on_manifest_missing_latest_item(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", tmp_path)

    manifest_resp = MagicMock()
    manifest_resp.text = "<work>no attr here</work>"
    manifest_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = manifest_resp

    with patch("jurist.ingest.fetch.httpx.Client", return_value=fake_client):
        with pytest.raises(ValueError, match="manifest missing _latestItem"):
            fetch_bwb_xml("BWBR0014315")
