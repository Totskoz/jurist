"""Parse rechtspraak.nl open-data XML → CaseMeta.

RDF namespaces used:
  dcterms:  http://purl.org/dc/terms/
  rdf:      http://www.w3.org/1999/02/22-rdf-syntax-ns#
  psi:      http://psi.rechtspraak.nl/

Body text lives outside the <rdf:RDF> block, in <uitspraak> descendants.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

NS = {
    "dcterms": "http://purl.org/dc/terms/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "psi": "http://psi.rechtspraak.nl/",
}


class ParseError(RuntimeError):
    """Raised when XML cannot be parsed."""


@dataclass(frozen=True)
class CaseMeta:
    ecli: str
    date: str
    court: str
    zaaknummer: str
    subject_uri: str
    modified: str
    body_text: str
    url: str


def parse_case(xml_bytes: bytes) -> CaseMeta:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ParseError(f"invalid XML: {exc}") from exc

    desc = root.find(".//rdf:Description", NS)
    if desc is None:
        raise ParseError("no rdf:Description block")

    ecli = _text(desc.find("dcterms:identifier", NS))
    date = _text(desc.find("dcterms:date", NS))
    court = _text(desc.find("dcterms:creator", NS))
    zaaknummer = _text(desc.find("psi:zaaknummer", NS))
    modified = _text(desc.find("dcterms:modified", NS))

    subject_elem = desc.find("dcterms:subject", NS)
    subject_uri = ""
    if subject_elem is not None:
        subject_uri = subject_elem.get("resourceIdentifier", "")

    # Body: everything under <uitspraak> (or <conclusie>), text-only
    body_text = _extract_body(root)

    url = (
        f"https://uitspraken.rechtspraak.nl/details?id={ecli}"
        if ecli
        else ""
    )

    return CaseMeta(
        ecli=ecli,
        date=date,
        court=court,
        zaaknummer=zaaknummer,
        subject_uri=subject_uri,
        modified=modified,
        body_text=body_text,
        url=url,
    )


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


_WS = re.compile(r"[ \t]+")


def _extract_body(root: ET.Element) -> str:
    """Walk <uitspraak>/<conclusie> descendants, collecting paragraph text.

    Returns paragraphs joined by \\n\\n; internal whitespace collapsed.
    """
    paragraphs: list[str] = []
    for block_name in ("uitspraak", "conclusie"):
        block = _find_local(root, block_name)
        if block is None:
            continue
        for para in _find_local_all(block, "para"):
            text = " ".join(para.itertext())
            text = _WS.sub(" ", text).strip()
            if text:
                paragraphs.append(text)
    # Fallback: if no <para> descendants found, concatenate all text.
    if not paragraphs:
        for block_name in ("uitspraak", "conclusie"):
            block = _find_local(root, block_name)
            if block is None:
                continue
            text = " ".join(block.itertext())
            text = _WS.sub(" ", text).strip()
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _find_local(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Find descendant whose tag ends with `local_name` (namespace-agnostic)."""
    for sub in elem.iter():
        if sub.tag == local_name or sub.tag.endswith(f"}}{local_name}"):
            return sub
    return None


def _find_local_all(elem: ET.Element, local_name: str) -> list[ET.Element]:
    return [
        sub for sub in elem.iter()
        if sub.tag == local_name or sub.tag.endswith(f"}}{local_name}")
    ]
