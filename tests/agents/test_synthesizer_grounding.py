"""Spec-mandated grounding guard test (M4 design §6.4)."""
from __future__ import annotations

import pytest

from jurist.agents import synthesizer
from jurist.agents.synthesizer import CitationGroundingFailedError
from jurist.agents.synthesizer_tools import (
    FailedCitation,
    build_synthesis_tool_schema,
    verify_citations,
)
from jurist.config import RunContext
from jurist.schemas import (
    CitedArticle,
    CitedCase,
    StructuredAnswer,
    SynthesizerIn,
    UitspraakCitation,
    WetArtikelCitation,
)
from tests.fixtures.mock_llm import MockStreamingClient, StreamScript

_CANDIDATE_ARTICLE_IDS = ["BWBR0005290/Boek7/A1", "BWBR0005290/Boek7/A2", "BWBR0014315/A10"]
_CANDIDATE_BWB_IDS = ["BWBR0005290", "BWBR0014315"]
_CANDIDATE_ECLIS = ["ECLI:NL:HR:2020:1", "ECLI:NL:RB:2022:2"]


def test_layer_1_schema_enum_equals_candidate_set():
    """Assertion (a): tool schema's `enum` equals the candidate set exactly."""
    schema = build_synthesis_tool_schema(
        _CANDIDATE_ARTICLE_IDS, _CANDIDATE_BWB_IDS, _CANDIDATE_ECLIS,
    )
    wa_item = schema["input_schema"]["properties"]["relevante_wetsartikelen"]["items"]
    uc_item = schema["input_schema"]["properties"]["vergelijkbare_uitspraken"]["items"]
    assert wa_item["properties"]["article_id"]["enum"] == _CANDIDATE_ARTICLE_IDS
    assert wa_item["properties"]["bwb_id"]["enum"] == _CANDIDATE_BWB_IDS
    assert uc_item["properties"]["ecli"]["enum"] == _CANDIDATE_ECLIS


def test_layer_2_verify_returns_unknown_id_not_keyerror():
    """Assertion (b): post-hoc resolver returns a FailedCitation(reason='unknown_id')
    on out-of-set IDs instead of raising KeyError."""
    cited_articles = [CitedArticle(
        bwb_id="BWBR0005290",
        article_id=_CANDIDATE_ARTICLE_IDS[0],
        article_label="Art 1",
        body_text="een voldoende lange brontekst voor het artikel hier aanwezig",
        reason="r",
    )]
    cited_cases = [CitedCase(
        ecli=_CANDIDATE_ECLIS[0],
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.8, reason="r",
        chunk_text="een voldoende lange brontekst voor de uitspraak hier aanwezig",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1",
    )]

    # Tampered: article_id + ecli out of set
    tampered = StructuredAnswer(
        korte_conclusie="conclusie " * 5,
        relevante_wetsartikelen=[
            WetArtikelCitation(
                article_id="IMAGINED/XYZ", bwb_id="BWBR0005290",
                article_label="Gefantaseerd artikel",
                quote="een gefantaseerde passage die we niet kunnen verifiëren omdat imagined",
                explanation="uitleg " * 8,
            ),
        ],
        vergelijkbare_uitspraken=[
            UitspraakCitation(
                ecli="ECLI:NL:FANTASY:9999",
                quote="een gefantaseerde rechtspraakpassage die niet bestaat in ons corpus",
                explanation="uitleg " * 8,
            ),
        ],
        aanbeveling="aanbeveling " * 5,
    )

    # Does NOT raise.
    failures = verify_citations(tampered, cited_articles, cited_cases)

    # Both tampered citations produce unknown_id failures.
    assert FailedCitation(
        kind="wetsartikel", id="IMAGINED/XYZ",
        quote=tampered.relevante_wetsartikelen[0].quote,
        reason="unknown_id",
    ) in failures
    assert any(
        f.kind == "uitspraak" and f.id == "ECLI:NL:FANTASY:9999" and f.reason == "unknown_id"
        for f in failures
    )


@pytest.mark.asyncio
async def test_layer_3_agent_hard_fails_on_imagined_id_twice():
    """Assertion (c): agent end-to-end with a mock producing imagined-ID
    tool_inputs twice in a row raises CitationGroundingFailedError (which
    the orchestrator turns into run_failed{reason:'citation_grounding'})."""
    cited_articles = [CitedArticle(
        bwb_id="BWBR0005290",
        article_id=_CANDIDATE_ARTICLE_IDS[0],
        article_label="Art 1",
        body_text="een voldoende lange brontekst voor het artikel hier aanwezig",
        reason="r",
    )]
    cited_cases = [CitedCase(
        ecli=_CANDIDATE_ECLIS[0],
        court="Rb", date="2024-01-01",
        snippet="s", similarity=0.8, reason="r",
        chunk_text="een voldoende lange brontekst voor de uitspraak hier aanwezig",
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2020:1",
    )]

    imagined = {
        "korte_conclusie": "conclusie " * 5,
        "relevante_wetsartikelen": [{
            "article_id": "IMAGINED/XYZ",                # out of set
            "bwb_id": "BWBR0005290",
            "article_label": "Gefantaseerd artikel",
            "quote": "een gefantaseerde passage die we niet kunnen verifiëren omdat imagined",
            "explanation": "uitleg " * 8,
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:FANTASY:9999",              # out of set
            "quote": "een gefantaseerde rechtspraakpassage die niet bestaat in ons corpus",
            "explanation": "uitleg " * 8,
        }],
        "aanbeveling": "aanbeveling " * 5,
    }

    client = MockStreamingClient([
        StreamScript(text_deltas=["."], tool_input=imagined),
        StreamScript(text_deltas=["."], tool_input=imagined),
    ])
    ctx = RunContext(kg=None, llm=client, case_store=None, embedder=None)  # type: ignore[arg-type]

    with pytest.raises(CitationGroundingFailedError):
        async for _ in synthesizer.run(
            SynthesizerIn(
                question="q",
                cited_articles=cited_articles,
                cited_cases=cited_cases,
            ),
            ctx=ctx,
        ):
            pass
