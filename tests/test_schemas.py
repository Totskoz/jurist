from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    CitedCase,
    DecomposerIn,
    DecomposerOut,
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
