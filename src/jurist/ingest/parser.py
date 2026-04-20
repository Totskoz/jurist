"""BWB XML parser — real schema (bwb-ng-variabel-deel attribute edition).

Key schema facts confirmed from fixture XMLs:
- Article identity: `bwb-ng-variabel-deel` attribute on each <artikel> element.
  e.g. "/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248"
- Container elements: <boek>, <titeldeel>, <afdeling>, <paragraaf>, <sub-paragraaf>,
  <hoofdstuk> — NOT <titel>.
- Explicit refs: <intref> elements carry `bwb-id` + `bwb-ng-variabel-deel` giving the
  resolved target directly. <extref> elements carry `bwb-id` but often lack
  `bwb-ng-variabel-deel`; fall back to parsing the `doc` attribute in that case.
- Article title: inherit from nearest ancestor with <kop><titel> text; else use
  the `label` attribute value (e.g. "Artikel 248").
- filter_titel for BWBR0005290: check that the path contains "/Titeldeel{N}/" for N
  in the allowed set.
"""
from __future__ import annotations

import re

from lxml import etree

from jurist.ingest.allowlist import BWBEntry
from jurist.schemas import ArticleEdge, ArticleNode

# Matches the article number in a JCI doc reference, e.g.
# "jci1.3:c:BWBR0014315&artikel=10" → group(1) = "10"
_DOC_ARTIKEL_RE = re.compile(r"artikel=([A-Za-z0-9]+)", re.IGNORECASE)


def parse_bwb_xml(
    xml_bytes: bytes, bwb_id: str, entry: BWBEntry
) -> tuple[list[ArticleNode], list[ArticleEdge]]:
    """Return (nodes, explicit_edges) from a single BWB XML document."""
    root = etree.fromstring(xml_bytes)
    nodes: list[ArticleNode] = []
    edges: list[ArticleEdge] = []

    for art in root.iter("artikel"):
        path = art.get("bwb-ng-variabel-deel", "")
        if not path:
            continue
        if entry.filter_titel is not None:
            if not any(f"/Titeldeel{t}/" in path for t in entry.filter_titel):
                continue

        article_id = f"{bwb_id}{path}"
        raw_label = art.get("label", "")
        label = f"{entry.label_prefix}, {raw_label}" if raw_label else entry.label_prefix
        title = _nearest_container_title(art) or raw_label
        body_text = _extract_body_text(art)

        outgoing_ids: list[str] = []
        for ref in art.iter("intref"):
            tid = _ref_to_article_id(ref)
            if tid is not None:
                outgoing_ids.append(tid)
                edges.append(
                    ArticleEdge(from_id=article_id, to_id=tid, kind="explicit", context=None)
                )
        for ref in art.iter("extref"):
            tid = _ref_to_article_id(ref)
            if tid is not None:
                outgoing_ids.append(tid)
                edges.append(
                    ArticleEdge(from_id=article_id, to_id=tid, kind="explicit", context=None)
                )

        nodes.append(
            ArticleNode(
                article_id=article_id,
                bwb_id=bwb_id,
                label=label,
                title=title,
                body_text=body_text,
                outgoing_refs=outgoing_ids,
            )
        )
    return nodes, edges


def _ref_to_article_id(ref: etree._Element) -> str | None:
    """Resolve a reference element to a canonical article ID string.

    For <intref> elements, `bwb-ng-variabel-deel` is always present.
    For <extref> elements it is often absent; fall back to parsing the `doc`
    attribute which looks like "jci1.3:c:BWBR0014315&artikel=10".
    """
    bwb = ref.get("bwb-id")
    if not bwb:
        return None

    path = ref.get("bwb-ng-variabel-deel")
    if path:
        return f"{bwb}{path}"

    # Fallback: parse artikel number from doc attribute
    doc = ref.get("doc", "")
    m = _DOC_ARTIKEL_RE.search(doc)
    if m:
        return f"{bwb}/Artikel{m.group(1)}"

    return None


def _extract_body_text(art: etree._Element) -> str:
    parts: list[str] = []
    for al in art.iter("al"):
        text = "".join(al.itertext())
        text = " ".join(text.split())
        if text:
            parts.append(text)
    return " ".join(parts)


def _nearest_container_title(art: etree._Element) -> str:
    for anc in art.iterancestors():
        if anc.tag == "artikel":
            continue
        kop = anc.find("kop")
        if kop is not None:
            t = kop.find("titel")
            if t is not None and t.text and t.text.strip():
                return t.text.strip()
    return ""
