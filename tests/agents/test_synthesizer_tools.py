"""Unit tests for M4 synthesizer pure helpers."""
from __future__ import annotations

from jurist.agents.synthesizer_tools import build_synthesis_tool_schema

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
