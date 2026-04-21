import pytest
from pydantic import ValidationError

from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CaseChunkRow,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    CitedCase,
    DecomposerIn,
    DecomposerOut,
    KGSnapshot,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    StructuredAnswer,
    SynthesizerIn,
    SynthesizerOut,
    TraceEvent,
    UitspraakCitation,
    ValidatorIn,
    ValidatorOut,
    WetArtikelCitation,
)


def test_trace_event_defaults_empty():
    ev = TraceEvent(type="agent_started")
    assert ev.type == "agent_started"
    assert ev.agent == ""
    assert ev.run_id == ""
    assert ev.ts == ""
    assert ev.data == {}


def test_trace_event_roundtrip():
    ev = TraceEvent(
        type="node_visited",
        agent="statute_retriever",
        run_id="run_abc",
        ts="2026-04-18T10:00:00Z",
        data={"article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248"},
    )
    dumped = ev.model_dump()
    assert TraceEvent.model_validate(dumped) == ev


def test_decomposer_out_intent_literal():
    out = DecomposerOut(
        sub_questions=["Mag de huur omhoog?"],
        concepts=["huurverhoging"],
        intent="legality_check",
    )
    assert out.intent == "legality_check"


def test_cited_article_has_body_text():
    a = CitedArticle(
        bwb_id="BWBR0005290",
        article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
        article_label="Boek 7, Artikel 248",
        body_text="Een verhuurder kan tot aan het tijdstip...",
        reason="Primary statute on huurprijsaanpassing.",
    )
    assert a.body_text.startswith("Een verhuurder")


def test_article_node_outgoing_refs_default_empty():
    node = ArticleNode(
        article_id="x/1",
        bwb_id="x",
        label="l",
        title="t",
        body_text="b",
    )
    assert node.outgoing_refs == []


def test_article_edge_kind_literal():
    e = ArticleEdge(from_id="a", to_id="b", kind="regex")
    assert e.kind == "regex"


def test_structured_answer_can_be_empty_lists():
    ans = StructuredAnswer(
        korte_conclusie="Dat mag niet zomaar.",
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling="Raadpleeg de Huurcommissie.",
    )
    assert ans.aanbeveling.startswith("Raadpleeg")


def test_validator_out_defaults_empty_issues():
    v = ValidatorOut(valid=True)
    assert v.issues == []


# Reference imports to silence unused warnings and confirm all types load.
_ = (
    CaseChunkRow,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedCase,
    DecomposerIn,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    SynthesizerIn,
    SynthesizerOut,
    UitspraakCitation,
    ValidatorIn,
    WetArtikelCitation,
)


def test_kg_snapshot_roundtrip():
    snap = KGSnapshot(
        generated_at="2026-04-20T10:00:00Z",
        source_versions={"BWBR0005290": "2024-01-01"},
        nodes=[
            ArticleNode(
                article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                bwb_id="BWBR0005290",
                label="Boek 7, Artikel 248",
                title="Huurverhoging",
                body_text="De verhuurder kan ...",
                outgoing_refs=["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"],
            )
        ],
        edges=[
            ArticleEdge(
                from_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                to_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                kind="explicit",
                context=None,
            )
        ],
    )
    payload = snap.model_dump_json()
    restored = KGSnapshot.model_validate_json(payload)
    assert restored == snap


def test_kg_snapshot_rejects_missing_fields():
    with pytest.raises(ValidationError):
        KGSnapshot.model_validate({"nodes": [], "edges": []})  # missing required fields


def test_case_chunk_row_serializes_round_trip() -> None:
    row = CaseChunkRow(
        ecli="ECLI:NL:RBAMS:2025:1234",
        chunk_idx=0,
        court="Rechtbank Amsterdam",
        date="2025-06-15",
        zaaknummer="C/13/123456 / HA ZA 25-001",
        subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
        modified="2025-06-20T14:22:10Z",
        text="De huurder heeft...",
        embedding=[0.1] * 1024,
        url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2025:1234",
    )
    dumped = row.model_dump()
    restored = CaseChunkRow.model_validate(dumped)
    assert restored == row
    assert len(restored.embedding) == 1024


def test_case_chunk_row_rejects_missing_fields() -> None:
    with pytest.raises(ValidationError):
        CaseChunkRow(ecli="ECLI:NL:RBAMS:2025:1", chunk_idx=0)  # missing many


def test_case_retriever_in_has_question_field() -> None:
    inp = CaseRetrieverIn(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Q1", "Q2"],
        statute_context=[
            CitedArticle(
                bwb_id="BWBR0005290",
                article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                article_label="Boek 7, Artikel 248",
                body_text="body",
                reason="relevant",
            ),
        ],
    )
    assert inp.question == "Mag de huur 15% omhoog?"


def test_case_retriever_in_requires_question() -> None:
    with pytest.raises(ValidationError):
        CaseRetrieverIn(sub_questions=["Q"], statute_context=[])
