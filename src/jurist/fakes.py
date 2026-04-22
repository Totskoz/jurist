"""Hardcoded fake data used by M0 fake agents.

Every ID, article label, and ECLI here is illustrative. Real data comes in M1+.
"""
from __future__ import annotations

from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CitedArticle,
    CitedCase,
    DecomposerOut,
    StatuteRetrieverOut,
    StructuredAnswer,
    UitspraakCitation,
    WetArtikelCitation,
)

BWB_BW7 = "BWBR0005290"
BWB_UHW = "BWBR0014315"

_BW7_PREFIX = f"{BWB_BW7}/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2"
_UHW_PREFIX = BWB_UHW


def _node(aid: str, label: str, title: str, body: str, refs: list[str]) -> ArticleNode:
    return ArticleNode(
        article_id=aid,
        bwb_id=aid.split("/", 1)[0],
        label=label,
        title=title,
        body_text=body,
        outgoing_refs=refs,
    )


_A248 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel248"
_A249 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel249"
_A250 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel250"
_A252 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel252"
_A253 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel253"
_A254 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel254"
_A255 = f"{_BW7_PREFIX}/Sub-paragraaf1/Artikel255"
_UHW3 = f"{_UHW_PREFIX}/HoofdstukI/Paragraaf2/Artikel3"
_UHW10 = f"{_UHW_PREFIX}/HoofdstukIII/Paragraaf1/Artikel10"

_NODES: list[ArticleNode] = [
    _node(_A248, "Boek 7, Artikel 248",
          "Jaarlijkse huurverhoging — bevoegdheid verhuurder",
          "De verhuurder kan tot aan het tijdstip dat ... (fake body text)",
          [_A249, _A252, _UHW3]),
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
    _node(_UHW3, "Uhw, Artikel 3",
          "Huurverhogingspercentage",
          "Het maximale huurverhogingspercentage ... (fake body text)",
          [_UHW10]),
    _node(_UHW10, "Uhw, Artikel 10",
          "Puntenstelsel woonruimte",
          "Het puntenstelsel bepaalt ... (fake body text)",
          []),
]


def _edge(a: str, b: str) -> ArticleEdge:
    return ArticleEdge(from_id=a, to_id=b)


_EDGES: list[ArticleEdge] = [
    _edge(_A248, _A249),
    _edge(_A248, _A252),
    _edge(_A248, _UHW3),
    _edge(_A249, _A248),
    _edge(_A249, _A250),
    _edge(_A250, _A249),
    _edge(_A250, _A254),
    _edge(_A252, _A253),
    _edge(_A253, _UHW10),
    _edge(_A254, _A255),
    _edge(_UHW3, _UHW10),
]

FAKE_KG: tuple[list[ArticleNode], list[ArticleEdge]] = (_NODES, _EDGES)

FAKE_VISIT_PATH: list[str] = [_A248, _A249, _A250, _A254, _A255]

FAKE_DECOMPOSER_OUT = DecomposerOut(
    sub_questions=[
        "Welke wettelijke maxima gelden voor huurverhoging?",
        "Onder welke voorwaarden is een verhoging van 15% toegestaan?",
    ],
    concepts=[
        "huurprijs",
        "wettelijk maximum huurverhoging",
        "huurverhogingsbeding",
    ],
    intent="legality_check",
    huurtype_hypothese="onbekend",  # M5
)

FAKE_CITED_ARTICLES: list[CitedArticle] = [
    CitedArticle(
        bwb_id=BWB_BW7,
        article_id=_A248,
        article_label="Boek 7, Artikel 248",
        body_text="De verhuurder kan tot aan het tijdstip dat ... (fake body text)",
        reason="Kernbepaling huurverhoging — bevoegdheid verhuurder.",
    ),
    CitedArticle(
        bwb_id=BWB_UHW,
        article_id=_UHW3,
        article_label="Uhw, Artikel 3",
        body_text="Het maximale huurverhogingspercentage ... (fake body text)",
        reason="Stelt het maximale verhogingspercentage vast.",
    ),
]

FAKE_STATUTE_OUT = StatuteRetrieverOut(
    cited_articles=FAKE_CITED_ARTICLES,
    low_confidence=False,
)

FAKE_CASES: list[CitedCase] = [
    CitedCase(
        ecli="ECLI:NL:HR:2020:1234",
        court="Hoge Raad",
        date="2020-09-11",
        snippet="De verhuurder mag de huur niet eenzijdig met een hoger percentage ...",
        similarity=0.87,
        reason="Leidende uitspraak over maximale huurverhoging bij gereguleerde huur.",
        chunk_text=(
            "De verhuurder mag de huur niet eenzijdig met een hoger percentage "
            "verhogen dan het door de minister vastgestelde maximum. Een "
            "voorstel dat dit maximum overschrijdt, is in beginsel niet "
            "toegestaan bij gereguleerde huur. De huurder kan binnen zes weken "
            "bezwaar maken bij de verhuurder, en vervolgens het geschil "
            "voorleggen aan de Huurcommissie. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1234",
    ),
    CitedCase(
        ecli="ECLI:NL:RBAMS:2022:5678",
        court="Rechtbank Amsterdam",
        date="2022-03-14",
        snippet="Huurverhoging van 15% acht de rechtbank in dit geval buitensporig ...",
        similarity=0.81,
        reason="Feitelijk zeer vergelijkbaar — huurder bezwaart succesvol tegen 15% verhoging.",
        chunk_text=(
            "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig. "
            "De verhuurder heeft onvoldoende onderbouwd waarom een verhoging "
            "van deze omvang gerechtvaardigd is. De rechtbank wijst het "
            "voorstel af en oordeelt dat de huurder niet gehouden is de "
            "verhoogde huur te betalen. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
    ),
    CitedCase(
        ecli="ECLI:NL:GHARL:2023:9012",
        court="Gerechtshof Arnhem-Leeuwarden",
        date="2023-06-22",
        snippet="Bij geliberaliseerde huur geldt een andere norm, maar de redelijkheid ...",
        similarity=0.74,
        reason="Relevant voor onderscheid gereguleerd / geliberaliseerd.",
        chunk_text=(
            "Bij geliberaliseerde huur geldt een andere norm, maar de "
            "redelijkheid blijft leidend. Een percentage dat in gereguleerde "
            "huur ontoelaatbaar zou zijn, kan in geliberaliseerde huur "
            "verdedigbaar zijn mits de huurovereenkomst dit toelaat en de "
            "verhoging aansluit bij marktniveau. " * 3
        ),
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:GHARL:2023:9012",
    ),
]

FAKE_ANSWER: StructuredAnswer = StructuredAnswer(
    kind="answer",
    korte_conclusie=(
        "Een huurverhoging van 15% is in de meeste gevallen niet toegestaan. "
        "Bij gereguleerde woonruimte geldt een jaarlijks maximum dat door de minister wordt "
        "vastgesteld; 15% zal dit vrijwel zeker overschrijden. Bij geliberaliseerde woonruimte "
        "moet de verhoging redelijk zijn "
        "en aansluiten bij wat in de huurovereenkomst is afgesproken."
    ),
    relevante_wetsartikelen=[
        WetArtikelCitation(
            article_id=_A248,
            bwb_id=BWB_BW7,
            article_label="Boek 7, Artikel 248",
            quote="De verhuurder kan tot aan het tijdstip dat ...",
            explanation=(
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse huurverhoging "
                "voor te stellen binnen de wettelijke kaders."
            ),
        ),
        WetArtikelCitation(
            article_id=_UHW10,
            bwb_id=BWB_UHW,
            article_label="Uhw, Artikel 10",
            quote="Het puntenstelsel bepaalt ...",
            explanation=(
                "Stelt het maximale percentage vast via het puntenstelsel; "
                "15% ligt daar ruim boven voor gereguleerde huur."
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
    insufficient_context_reason=None,
)
