from pathlib import Path

from jurist.ingest.allowlist import BWB_ALLOWLIST, BWBEntry
from jurist.ingest.parser import parse_bwb_xml


def _bw7_entry() -> BWBEntry:
    return BWB_ALLOWLIST["BWBR0005290"]


# ---------------------------------------------------------------------------
# Fixture-based tests (real BWB XML excerpt)
# ---------------------------------------------------------------------------

def test_parses_art_7_248_from_fixture():
    """art. 7:248 BW: article_id, label, body text, outgoing_refs all correct."""
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())

    a248 = next(
        (n for n in nodes
         if n.article_id == "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248"),
        None,
    )
    assert a248 is not None, "art. 7:248 BW not found"
    assert a248.label == "Boek 7, Artikel 248"
    assert "huurprijs" in a248.body_text.lower()
    assert any("Artikel252" in ref for ref in a248.outgoing_refs), (
        f"expected ref to Artikel252 in {a248.outgoing_refs}"
    )


def test_intref_edge_extracted_with_bwb_and_path():
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, edges = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())
    from_248 = [
        e for e in edges
        if e.from_id.endswith("/Artikel248") and "Artikel252" in e.to_id
    ]
    assert len(from_248) >= 1, "expected intref edge 248→252"
    assert from_248[0].kind == "explicit"
    assert from_248[0].to_id.startswith("BWBR0005290/")


def test_extref_edge_to_other_bwb():
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, edges = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())
    cross = [
        e for e in edges
        if e.from_id.endswith("/Artikel248") and e.to_id.startswith("BWBR0014315/")
    ]
    assert len(cross) >= 1, "expected extref edge 248→BWBR0014315/..."


def test_filter_titel_applies_only_matching_titeldeel():
    fake_entry = BWBEntry(name="test", label_prefix="X", filter_titel=("99",))
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", fake_entry)
    assert nodes == [], f"expected 0 nodes for filter_titel=('99',), got {len(nodes)}"


def test_uhw_parses_with_no_filter():
    fixture = Path(__file__).parent / "fixtures" / "BWBR0014315_excerpt.xml"
    nodes, _ = parse_bwb_xml(
        fixture.read_bytes(), "BWBR0014315", BWB_ALLOWLIST["BWBR0014315"]
    )
    assert len(nodes) >= 3, f"expected ≥3 Uhw articles, got {len(nodes)}"
    ids = {n.article_id for n in nodes}
    assert any(aid.endswith("/Artikel3") for aid in ids), f"Artikel3 not found in {ids}"


def test_article_title_inherits_nearest_container_titel():
    fixture = Path(__file__).parent / "fixtures" / "BWBR0005290_excerpt.xml"
    nodes, _ = parse_bwb_xml(fixture.read_bytes(), "BWBR0005290", _bw7_entry())
    a248 = next(
        (n for n in nodes if n.article_id.endswith("/Artikel248")), None
    )
    assert a248 is not None
    assert a248.title, "expected non-empty title for art. 248"
    assert a248.title == "Huurprijzen", f"expected 'Huurprijzen', got '{a248.title}'"
