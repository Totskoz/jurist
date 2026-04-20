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


def test_short_circuit_fires_when_scope_equal(tmp_path: Path, monkeypatch):
    """Same scope + matching versions = short-circuit."""
    data_dir = _isolate(tmp_path, monkeypatch)
    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    before_mtime = out.stat().st_mtime

    import time
    time.sleep(0.05)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    # Short-circuit: file not rewritten
    assert out.stat().st_mtime == before_mtime


def test_short_circuit_skips_when_scope_narrows(tmp_path: Path, monkeypatch):
    """If caller passes a narrower bwb_ids than existing snapshot, do not short-circuit."""
    # Set allowlist to two BWBs
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings", Settings(data_dir=data_dir))
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data_dir / "cache" / "bwb")
    from jurist.ingest.allowlist import BWBEntry
    monkeypatch.setattr(
        "jurist.ingest.statutes.BWB_ALLOWLIST",
        {
            "BWBR0005290": BWBEntry(name="BW7", label_prefix="BW7"),
            "BWBR0014315": BWBEntry(name="Uhw", label_prefix="Uhw"),
        },
    )

    # First run: ingest both
    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    out = data_dir / "kg" / "huurrecht.json"
    import json as _json
    snap_both = _json.loads(out.read_text(encoding="utf-8"))
    assert set(snap_both["source_versions"].keys()) == {"BWBR0005290", "BWBR0014315"}

    # Second run: just one BWB — should NOT short-circuit (scope narrowed)
    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        run_ingest(refresh=False, no_fetch=False, bwb_ids=["BWBR0014315"], limit=None)

    snap_narrow = _json.loads(out.read_text(encoding="utf-8"))
    # After narrow run the snapshot reflects only the narrowed scope
    assert set(snap_narrow["source_versions"].keys()) == {"BWBR0014315"}


def test_dangling_edges_dropped_before_write(tmp_path: Path, monkeypatch):
    """Edges whose to_id doesn't match any parsed node must not survive to the snapshot."""
    # Construct a minimal XML with an <artikel> that intrefs a target NOT in the node set.
    # Easiest: use a fake parse to force dangling edges directly via monkeypatch.
    _isolate(tmp_path, monkeypatch)

    from jurist.schemas import ArticleEdge, ArticleNode

    def fake_parse(xml_bytes, bwb_id, entry):
        nodes = [
            ArticleNode(
                article_id="BWBR0014315/Real/Artikel3",
                bwb_id="BWBR0014315",
                label="Test, Artikel 3",
                title="",
                body_text="body",
                outgoing_refs=[],
            )
        ]
        edges = [
            ArticleEdge(from_id="BWBR0014315/Real/Artikel3",
                        to_id="BWBR0014315/Phantom/Artikel99",  # not in nodes
                        kind="explicit"),
        ]
        return nodes, edges

    monkeypatch.setattr("jurist.ingest.statutes.parse_bwb_xml", fake_parse)

    with patch("jurist.ingest.statutes.fetch_bwb_xml", return_value=MINI_XML_V1):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    assert snap.nodes, "expected at least one node"
    # The dangling edge must have been dropped
    assert snap.edges == [], f"expected 0 edges after dangle guard, got {snap.edges}"
    # And outgoing_refs on the surviving node should also be empty
    assert snap.nodes[0].outgoing_refs == []
