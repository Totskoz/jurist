"""Unit tests for M4 synthesizer pure helpers."""
from __future__ import annotations

from jurist.agents.synthesizer_tools import (
    build_synthesis_tool_schema,
    build_synthesis_user_message,
)
from jurist.schemas import CitedArticle, CitedCase

_ARTICLE_IDS = ["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "BWBR0014315/HoofdstukIII/Paragraaf1/Artikel10"]
_BWB_IDS    = ["BWBR0005290", "BWBR0014315"]
_ECLIS      = ["ECLI:NL:HR:2020:1234", "ECLI:NL:RBAMS:2022:5678"]


def test_tool_schema_top_level_shape():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    assert schema["name"] == "emit_answer"
    top = schema["input_schema"]
    assert top["type"] == "object"
    assert sorted(top["required"]) == sorted([
        "korte_conclusie", "relevante_wetsartikelen",
        "vergelijkbare_uitspraken", "aanbeveling",
    ])


def test_tool_schema_wetsartikel_enum_equals_candidate_set():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    item = schema["input_schema"]["properties"]["relevante_wetsartikelen"]["items"]
    assert item["properties"]["article_id"]["enum"] == _ARTICLE_IDS
    assert item["properties"]["bwb_id"]["enum"] == _BWB_IDS
    assert item["properties"]["quote"]["minLength"] == 40
    assert item["properties"]["quote"]["maxLength"] == 500
    assert sorted(item["required"]) == sorted([
        "article_id", "bwb_id", "article_label", "quote", "explanation",
    ])


def test_tool_schema_uitspraak_enum_equals_candidate_set():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    item = schema["input_schema"]["properties"]["vergelijkbare_uitspraken"]["items"]
    assert item["properties"]["ecli"]["enum"] == _ECLIS
    assert item["properties"]["quote"]["minLength"] == 40
    assert item["properties"]["quote"]["maxLength"] == 500
    assert sorted(item["required"]) == sorted(["ecli", "quote", "explanation"])


def test_tool_schema_both_arrays_have_minitems_1():
    schema = build_synthesis_tool_schema(_ARTICLE_IDS, _BWB_IDS, _ECLIS)
    props = schema["input_schema"]["properties"]
    assert props["relevante_wetsartikelen"]["minItems"] == 1
    assert props["vergelijkbare_uitspraken"]["minItems"] == 1


def _sample_article(article_id="A1", bwb_id="BWB1"):
    return CitedArticle(
        bwb_id=bwb_id, article_id=article_id,
        article_label="Art 1", body_text="body text of article 1",
        reason="Cited because relevant.",
    )


def _sample_case(ecli="ECLI:NL:T:1"):
    return CitedCase(
        ecli=ecli, court="Hof", date="2024-05-01",
        snippet="snippet ...", similarity=0.8,
        reason="Vergelijkbare casuïstiek.",
        chunk_text="full chunk text of case 1 ...",
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def test_user_message_contains_question():
    msg = build_synthesis_user_message(
        question="Mag 15% omhoog?",
        cited_articles=[_sample_article()],
        cited_cases=[_sample_case()],
    )
    assert "Mag 15% omhoog?" in msg


def test_user_message_renders_article_body_and_chunk_text():
    art = _sample_article()
    case = _sample_case()
    msg = build_synthesis_user_message(
        question="q", cited_articles=[art], cited_cases=[case],
    )
    # Full body_text must be in the prompt (quote-verification surface)
    assert art.body_text in msg
    assert case.chunk_text in msg


def test_user_message_includes_article_ids_and_eclis_literally():
    art = _sample_article(article_id="BWB/A/B/Artikel1", bwb_id="BWB")
    case = _sample_case(ecli="ECLI:NL:TEST:42")
    msg = build_synthesis_user_message(
        question="q", cited_articles=[art], cited_cases=[case],
    )
    assert "BWB/A/B/Artikel1" in msg
    assert "ECLI:NL:TEST:42" in msg
    # Instruction band about verbatim + length bounds
    assert "verbatim" in msg.lower() or "letterlijk" in msg.lower()
    assert "40" in msg and "500" in msg
