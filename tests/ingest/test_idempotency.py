import json
import time
from pathlib import Path
from unittest.mock import patch

from jurist.config import Settings
from jurist.ingest.statutes import run_ingest

MINI_XML_V1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet vigerend-sinds="2024-01-01">
  <artikel nr="1">
    <kop><titel>First</titel></kop>
    <lid><al>Body one.</al></lid>
  </artikel>
</wet>
"""

MINI_XML_V2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<wet vigerend-sinds="2025-06-01">
  <artikel nr="1">
    <kop><titel>First updated</titel></kop>
    <lid><al>Body updated.</al></lid>
  </artikel>
</wet>
"""


def _isolate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings", Settings(data_dir=data_dir))
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data_dir / "cache" / "bwb")
    from jurist.ingest.allowlist import BWBEntry
    monkeypatch.setattr(
        "jurist.ingest.statutes.BWB_ALLOWLIST",
        {"BWBR0014315": BWBEntry(name="Test", label_prefix="Test")},
    )
    return data_dir


def test_idempotent_short_circuits_when_versions_match(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1) as m:
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
        assert m.call_count == 1

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1) as m:
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
        assert m.call_count == 1

    out = data_dir / "kg" / "huurrecht.json"
    assert out.exists()


def test_refresh_forces_reparse_on_matching_versions(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)
    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    first_mtime = out.stat().st_mtime

    time.sleep(0.05)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=True, no_fetch=False, bwb_ids=None, limit=None)

    assert out.stat().st_mtime > first_mtime


def test_version_change_triggers_reparse(tmp_path: Path, monkeypatch):
    data_dir = _isolate(tmp_path, monkeypatch)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    snap_before = json.loads(out.read_text(encoding="utf-8"))
    assert snap_before["source_versions"]["BWBR0014315"] == "2024-01-01"

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V2):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    snap_after = json.loads(out.read_text(encoding="utf-8"))
    assert snap_after["source_versions"]["BWBR0014315"] == "2025-06-01"
