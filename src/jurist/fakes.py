"""Hardcoded fake data used by M0 fake agents.

Every ID, article label, and ECLI here is illustrative. Real data comes in M1+.
"""
from __future__ import annotations

from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CitedCase,
    StructuredAnswer,
    UitspraakCitation,
    WetArtikelCitation,
)

BWB_BW7 = "BWBR0005290"
BWB_UHW = "BWBR0002888"


def _node(aid: str, label: str, title: str, body: str, refs: list[str]) -> ArticleNode:
    return ArticleNode(
        article_id=aid,
        bwb_id=aid.split("/", 1)[0],
        label=label,
        title=title,
        body_text=body,
        outgoing_refs=refs,
    )


_A248 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel248"
_A249 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel249"
_A250 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel250"
_A252 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel252"
_A253 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel253"
_A254 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel254"
_A255 = f"{BWB_BW7}/Boek7/Titel4/Afdeling5/Artikel255"
_UHW6 = f"{BWB_UHW}/Artikel6"
_UHW10 = f"{BWB_UHW}/Artikel10"

_NODES: list[ArticleNode] = [
    _node(_A248, "Boek 7, Artikel 248",
          "Jaarlijkse huurverhoging — bevoegdheid verhuurder",
          "De verhuurder kan tot aan het tijdstip dat ... (fake body text)",
          [_A249, _A252, _UHW6]),
    _node(_A249, "Boek 7, Artikel 249",
          "Huurverhoging — voorwaarden en kennisgeving",
          "Een voorstel tot huurverhoging ... (fake body text)",
          [_A248, _A250]),
    _node(_A250, "Boek 7, Artikel 250",
          "Bezwaar huurder tegen huurverhoging",
          "De huurder kan ... (fake body text)",
          [_A249, _A254]),
    _node(_A252, "Boek 7, Artikel 252",
          "Geliberaliseerde huurovereenkomst",
          "In geval van een geliberaliseerde ... (fake body text)",
          [_A253]),
    _node(_A253, "Boek 7, Artikel 253",
          "Maximale huurprijs",
          "De maximale huurprijs wordt bepaald ... (fake body text)",
          [_UHW10]),
    _node(_A254, "Boek 7, Artikel 254",
          "Huurcommissie — geschillen",
          "Een geschil over huurprijs kan ... (fake body text)",
          [_A255]),
    _node(_A255, "Boek 7, Artikel 255",
          "Beroep tegen uitspraak huurcommissie",
          "Beroep staat open bij de kantonrechter ... (fake body text)",
          []),
    _node(_UHW6, "Uhw, Artikel 6",
          "Huurverhogingspercentage",
          "Het maximale huurverhogingspercentage ... (fake body text)",
          [_UHW10]),
    _node(_UHW10, "Uhw, Artikel 10",
          "Puntenstelsel woonruimte",
          "Het puntenstelsel bepaalt ... (fake body text)",
          []),
]


def _edge(a: str, b: str, kind: str = "explicit") -> ArticleEdge:
    return ArticleEdge(from_id=a, to_id=b, kind=kind)  # type: ignore[arg-type]


_EDGES: list[ArticleEdge] = [
    _edge(_A248, _A249),
    _edge(_A248, _A252),
    _edge(_A248, _UHW6),
    _edge(_A249, _A248),
    _edge(_A249, _A250),
    _edge(_A250, _A249),
    _edge(_A250, _A254),
    _edge(_A252, _A253),
    _edge(_A253, _UHW10),
    _edge(_A254, _A255),
    _edge(_UHW6, _UHW10),
]

FAKE_KG: tuple[list[ArticleNode], list[ArticleEdge]] = (_NODES, _EDGES)

FAKE_VISIT_PATH: list[str] = [_A248, _A249, _A250, _UHW6, _A252]

FAKE_CASES: list[CitedCase] = [
    CitedCase(
        ecli="ECLI:NL:HR:2020:1234",
        court="Hoge Raad",
        date="2020-09-11",
        snippet="De verhuurder mag de huur niet eenzijdig met een hoger percentage ...",
        similarity=0.87,
        reason="Leidende uitspraak over maximale huurverhoging bij gereguleerde huur.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
    ),
    CitedCase(
        ecli="ECLI:NL:RBAMS:2022:5678",
        court="Rechtbank Amsterdam",
        date="2022-03-14",
        snippet="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
        similarity=0.81,
        reason="Feitelijk zeer vergelijkbaar — huurder bezwaart succesvol tegen 15% verhoging.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
    ),
    CitedCase(
        ecli="ECLI:NL:GHARL:2023:9012",
        court="Gerechtshof Arnhem-Leeuwarden",
        date="2023-06-22",
        snippet="Bij geliberaliseerde huur geldt een andere norm, maar de redelijkheid ...",
        similarity=0.74,
        reason="Relevant voor onderscheid gereguleerd / geliberaliseerd.",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:GHARL:2023:9012",
    ),
]

FAKE_ANSWER: StructuredAnswer = StructuredAnswer(
    korte_conclusie=(
        "Een huurverhoging van 15% is in de meeste gevallen niet toegestaan. "
        "Bij gereguleerde woonruimte geldt een jaarlijks maximum dat door de minister wordt vastgesteld; "
        "15% zal dit vrijwel zeker overschrijden. Bij geliberaliseerde woonruimte moet de verhoging redelijk zijn "
        "en aansluiten bij wat in de huurovereenkomst is afgesproken."
    ),
    relevante_wetsartikelen=[
        WetArtikelCitation(
            bwb_id=BWB_BW7,
            article_label="Boek 7, Artikel 248",
            quote="De verhuurder kan tot aan het tijdstip dat ...",
            explanation=(
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse huurverhoging voor te stellen "
                "binnen de wettelijke kaders."
            ),
        ),
        WetArtikelCitation(
            bwb_id=BWB_UHW,
            article_label="Uhw, Artikel 6",
            quote="Het maximale huurverhogingspercentage ...",
            explanation=(
                "Stelt het maximale percentage vast; 15% ligt daar ruim boven voor gereguleerde huur."
            ),
        ),
    ],
    vergelijkbare_uitspraken=[
        UitspraakCitation(
            ecli="ECLI:NL:RBAMS:2022:5678",
            quote="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
            explanation=(
                "Feitelijk zeer vergelijkbaar — rechtbank wijst het voorstel af als buitensporig."
            ),
        ),
    ],
    aanbeveling=(
        "Maak binnen zes weken na ontvangst van het voorstel bezwaar bij de verhuurder; "
        "kom je er niet uit, leg het geschil voor aan de Huurcommissie."
    ),
)
