"""Tests for RDF + body extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "caselaw"


def test_parse_sparse_case() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    xml = (FIXTURE_DIR / "sparse_case.xml").read_bytes()
    meta = parse_case(xml)
    assert meta.ecli == "ECLI:NL:RBTEST:2025:9999"
    assert meta.date == "2025-06-15"
    assert meta.court == "Rechtbank Test"
    assert meta.zaaknummer == ""  # missing in sparse fixture
    assert meta.subject_uri == (
        "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    )
    assert meta.modified == "2025-06-20T14:22:10"
    assert "huurder" in meta.body_text
    assert "woonruimte" in meta.body_text
    assert meta.url == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBTEST:2025:9999"
    )


def test_parse_real_fixture_yields_populated_fields() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    # Pick any real fixture that exists
    candidates = list(FIXTURE_DIR.glob("ECLI_*.xml"))
    assert candidates, "expected at least one real ECLI fixture"
    xml = candidates[0].read_bytes()
    meta = parse_case(xml)
    assert meta.ecli.startswith("ECLI:NL:")
    assert meta.date  # ISO date present
    assert meta.court  # non-empty court string
    assert meta.subject_uri.startswith("http://psi.rechtspraak.nl/rechtsgebied#")
    assert meta.url.startswith("https://uitspraken.rechtspraak.nl/details?id=ECLI:")
    assert len(meta.body_text) > 100  # non-trivial body


def test_parse_body_strips_xml_tags_and_collapses_whitespace() -> None:
    from jurist.ingest.caselaw_parser import parse_case

    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<open-rechtspraak>
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
           xmlns:dcterms="http://purl.org/dc/terms/">
    <rdf:Description>
      <dcterms:identifier>ECLI:NL:RBTEST:2025:1</dcterms:identifier>
      <dcterms:date>2025-01-01</dcterms:date>
      <dcterms:creator resourceIdentifier="x">Rb</dcterms:creator>
      <dcterms:subject resourceIdentifier="http://psi.rechtspraak.nl/rechtsgebied#x">x</dcterms:subject>
      <dcterms:modified>2025-01-02</dcterms:modified>
    </rdf:Description>
  </rdf:RDF>
  <uitspraak>
    <para>Eerste    paragraaf met   veel spaties.</para>
    <para>Tweede paragraaf.</para>
  </uitspraak>
</open-rechtspraak>"""
    meta = parse_case(xml)
    assert "Eerste paragraaf met veel spaties." in meta.body_text
    assert "Tweede paragraaf." in meta.body_text
    # Paragraph break preserved
    assert "\n\n" in meta.body_text


def test_parse_invalid_xml_raises() -> None:
    from jurist.ingest.caselaw_parser import ParseError, parse_case

    with pytest.raises(ParseError):
        parse_case(b"<not valid xml")
