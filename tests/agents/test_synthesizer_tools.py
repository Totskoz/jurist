"""Unit tests for M4 synthesizer pure helpers."""
from __future__ import annotations

from jurist.agents.synthesizer_tools import (
    FailedCitation,  # noqa: F401  — re-exported helper; tests assert on returned instances
    _format_regen_advisory,
    _normalize,
    _validate_attempt,
    build_synthesis_tool_schema,
    build_synthesis_user_message,
    verify_citations,
)
from jurist.schemas import (
    CitedArticle,
    CitedCase,
    StructuredAnswer,
    UitspraakCitation,
    WetArtikelCitation,
)

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


_ARTICLE_BODY = (
    "Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan."
)
_CASE_CHUNK = (
    "De rechtbank oordeelt dat een verhoging van 15% buitensporig is."
)


def _answer_with(article_id, bwb_id, article_body_quote, ecli, case_chunk_quote):
    return StructuredAnswer(
        korte_conclusie="conclusie " * 5,
        relevante_wetsartikelen=[
            WetArtikelCitation(
                article_id=article_id, bwb_id=bwb_id,
                article_label="Art", quote=article_body_quote,
                explanation="uitleg " * 8,
            ),
        ],
        vergelijkbare_uitspraken=[
            UitspraakCitation(
                ecli=ecli, quote=case_chunk_quote,
                explanation="uitleg " * 8,
            ),
        ],
        aanbeveling="aanbeveling " * 5,
    )


def _articles():
    return [CitedArticle(
        bwb_id="BWB1",
        article_id="A1",
        article_label="Art 1",
        body_text=_ARTICLE_BODY,
        reason="r",
    )]


def _cases():
    return [CitedCase(
        ecli="ECLI:NL:TEST:1",
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.9,
        reason="r",
        chunk_text=_CASE_CHUNK,
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:TEST:1",
    )]


def test_normalize_is_idempotent():
    s = "Hallo  wereld\n\nmet\tspaties"
    assert _normalize(s) == _normalize(_normalize(s))


def test_normalize_collapses_whitespace_runs():
    assert _normalize("a\n\n b\t\tc") == "a b c"


def test_normalize_applies_nfc():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "café")
    nfc = unicodedata.normalize("NFC", "café")
    assert _normalize(nfd) == _normalize(nfc)


def test_verify_happy_path_returns_empty():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote=_ARTICLE_BODY,
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    assert verify_citations(answer, _articles(), _cases()) == []


def test_verify_quote_not_in_source():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote=(
            "Deze zin komt niet letterlijk voor in de brontekst "
            "maar is wel lang genoeg."
        ),
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert len(failures) == 1
    assert failures[0].kind == "wetsartikel"
    assert failures[0].reason == "not_in_source"


def test_verify_quote_passes_with_different_whitespace():
    # Source has single spaces; quote has doubled spaces — normalization rescues it.
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote=(
            "Een voorstel  tot\thuurverhoging binnen de wettelijke "
            "kaders is toegestaan."
        ),
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    assert verify_citations(answer, _articles(), _cases()) == []


def test_verify_unknown_article_id():
    answer = _answer_with(
        article_id="IMAGINED/XYZ", bwb_id="BWB1",
        article_body_quote=_ARTICLE_BODY,
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "unknown_id" and f.kind == "wetsartikel" for f in failures)


def test_verify_unknown_ecli():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote=_ARTICLE_BODY,
        ecli="ECLI:NL:GHOST:99",
        case_chunk_quote=_CASE_CHUNK,
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "unknown_id" and f.kind == "uitspraak" for f in failures)


def test_verify_quote_too_short():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="kort",
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "too_short" for f in failures)


def test_verify_quote_too_long():
    answer = _answer_with(
        article_id="A1", bwb_id="BWB1",
        article_body_quote="x" * 501,
        ecli="ECLI:NL:TEST:1",
        case_chunk_quote=_CASE_CHUNK,
    )
    failures = verify_citations(answer, _articles(), _cases())
    assert any(f.reason == "too_long" for f in failures)


def test_format_regen_advisory_lists_every_failure():
    failures = [
        FailedCitation("wetsartikel", "A1", "q1 quote", "not_in_source"),
        FailedCitation("uitspraak", "ECLI:NL:X:1", "q2 quote", "too_short"),
    ]
    msg = _format_regen_advisory(failures)
    assert "ongeldige citaten" in msg.lower()
    assert "A1" in msg and "ECLI:NL:X:1" in msg
    assert "not_in_source" in msg
    assert "too_short" in msg
    assert "40" in msg and "500" in msg
    assert "emit_answer" in msg


def test_validate_attempt_none_tool_input():
    # No tool_use block → (empty failures, schema_ok=False).
    failures, schema_ok = _validate_attempt(None, _articles(), _cases())
    assert failures == []
    assert schema_ok is False


def test_validate_attempt_pydantic_invalid():
    # Missing required field (aanbeveling) → schema_ok=False.
    bad = {
        "korte_conclusie": "c" * 40,
        "relevante_wetsartikelen": [],
        "vergelijkbare_uitspraken": [],
        # no aanbeveling
    }
    failures, schema_ok = _validate_attempt(bad, _articles(), _cases())
    assert schema_ok is False


def test_validate_attempt_verification_failures():
    tool_input = {
        "korte_conclusie": "c " * 25,
        "relevante_wetsartikelen": [{
            "article_id": "A1", "bwb_id": "BWB1",
            "article_label": "Art 1",
            "quote": "Deze zin komt niet letterlijk voor in de brontekst maar is wel lang genoeg.",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:TEST:1",
            "quote": "De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "a " * 25,
    }
    failures, schema_ok = _validate_attempt(tool_input, _articles(), _cases())
    assert schema_ok is True
    assert any(f.reason == "not_in_source" for f in failures)


def test_validate_attempt_happy():
    tool_input = {
        "korte_conclusie": "c " * 25,
        "relevante_wetsartikelen": [{
            "article_id": "A1", "bwb_id": "BWB1",
            "article_label": "Art 1",
            "quote": "Een voorstel tot huurverhoging binnen de wettelijke kaders is toegestaan.",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:TEST:1",
            "quote": "De rechtbank oordeelt dat een verhoging van 15% buitensporig is.",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "a " * 25,
    }
    failures, schema_ok = _validate_attempt(tool_input, _articles(), _cases())
    assert failures == []
    assert schema_ok is True
