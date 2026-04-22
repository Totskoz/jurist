"""Unit tests for the M4 synthesizer agent."""
from __future__ import annotations

import pytest

from jurist.agents import synthesizer
from jurist.agents.synthesizer import CitationGroundingFailedError
from jurist.config import RunContext
from jurist.schemas import (
    CitedArticle,
    CitedCase,
    SynthesizerIn,
    SynthesizerOut,
)
from tests.fixtures.mock_llm import MockStreamingClient, StreamScript


def _articles():
    return [
        CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text=(
                "De verhuurder kan tot aan het tijdstip waarop drie jaren zijn verstreken "
                "een voorstel tot huurverhoging binnen de wettelijke kaders doen."
            ),
            reason="Regelt bevoegdheid huurverhoging.",
        ),
        CitedArticle(
            bwb_id="BWBR0014315",
            article_id="BWBR0014315/HoofdstukIII/Paragraaf1/Artikel10",
            article_label="Uhw, Artikel 10",
            body_text=(
                "Het puntenstelsel bepaalt de maximale huurprijs voor gereguleerde woonruimte."
            ),
            reason="Stelt maximum huurverhoging vast.",
        ),
    ]


def _cases():
    return [
        CitedCase(
            ecli="ECLI:NL:RBAMS:2022:5678",
            court="Rechtbank Amsterdam",
            date="2022-03-14",
            snippet="Huurverhoging van 15% acht de rechtbank ...",
            similarity=0.81,
            reason="Rechtbank wijst 15% af.",
            chunk_text=(
                "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig. "
                "De verhuurder heeft onvoldoende onderbouwd waarom een verhoging "
                "van deze omvang gerechtvaardigd is."
            ),
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
        ),
    ]


def _valid_tool_input():
    return {
        "korte_conclusie": "Een huurverhoging van 15% is in de meeste gevallen niet toegestaan.",
        "relevante_wetsartikelen": [{
            "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
            "bwb_id": "BWBR0005290",
            "article_label": "Boek 7, Artikel 248",
            "quote": (
                "De verhuurder kan tot aan het tijdstip waarop drie jaren zijn "
                "verstreken een voorstel tot huurverhoging binnen de wettelijke "
                "kaders doen."
            ),
            "explanation": (
                "Regelt de bevoegdheid van de verhuurder om een jaarlijkse "
                "huurverhoging voor te stellen binnen wettelijke kaders."
            ),
        }],
        "vergelijkbare_uitspraken": [{
            "ecli": "ECLI:NL:RBAMS:2022:5678",
            "quote": "Huurverhoging van 15% acht de rechtbank in dit geval buitensporig.",
            "explanation": "Rechtbank wijst 15% af als buitensporig; feitelijk vergelijkbaar.",
        }],
        "aanbeveling": (
            "Maak binnen zes weken bezwaar bij de verhuurder en leg "
            "anders voor aan de Huurcommissie."
        ),
    }


def _ctx(client):
    return RunContext(kg=None, llm=client, case_store=None, embedder=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_synthesizer_happy_path():
    script = StreamScript(
        text_deltas=[
            "Ik ga artikel 7:248 ",
            "citeren en de ",
            "Amsterdam-uitspraak.",
        ],
        tool_input=_valid_tool_input(),
    )
    ctx = _ctx(MockStreamingClient([script]))

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="Mag de huur met 15% omhoog?",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    types = [ev.type for ev in events]
    # agent_started is first; agent_finished is last; thinking comes before
    # citation_resolved and answer_delta.
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert types.count("agent_thinking") == 3                       # one per text_delta
    # two citations total → two citation_resolved events
    assert types.count("citation_resolved") == 2
    assert types.count("answer_delta") >= 5                         # at least several tokens

    out = SynthesizerOut.model_validate(events[-1].data)
    assert "15%" in out.answer.korte_conclusie
    assert out.answer.relevante_wetsartikelen[0].article_id.endswith("/Artikel248")


def _invalid_tool_input_quote_not_in_source():
    ti = _valid_tool_input()
    ti["relevante_wetsartikelen"][0]["quote"] = (
        "Deze zin komt echt niet letterlijk voor in de brontekst maar is lang genoeg."
    )
    return ti


@pytest.mark.asyncio
async def test_synthesizer_regens_on_quote_failure_then_succeeds():
    script_1 = StreamScript(
        text_deltas=["denk 1"],
        tool_input=_invalid_tool_input_quote_not_in_source(),
    )
    script_2 = StreamScript(
        text_deltas=["denk 2"],
        tool_input=_valid_tool_input(),
    )
    client = MockStreamingClient([script_1, script_2])
    ctx = _ctx(client)

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="Mag 15%?",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(client.calls) == 2
    # Advisory appears in second call's user message
    second_user = client.calls[1]["messages"][0]["content"]
    assert "ongeldige citaten" in second_user.lower()
    assert "not_in_source" in second_user


@pytest.mark.asyncio
async def test_synthesizer_hard_fails_after_two_quote_failures():
    bad = _invalid_tool_input_quote_not_in_source()
    client = MockStreamingClient([
        StreamScript(text_deltas=["."], tool_input=bad),
        StreamScript(text_deltas=["."], tool_input=bad),
    ])
    ctx = _ctx(client)

    with pytest.raises(CitationGroundingFailedError, match="after retry"):
        async for _ in synthesizer.run(
            SynthesizerIn(
                question="q",
                cited_articles=_articles(),
                cited_cases=_cases(),
            ),
            ctx=ctx,
        ):
            pass
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_synthesizer_regens_on_missing_tool_use_then_succeeds():
    # First script has no tool_input → tool_use block missing from final message.
    client = MockStreamingClient([
        StreamScript(text_deltas=["I forgot the tool."], tool_input=None),
        StreamScript(text_deltas=["ok now"], tool_input=_valid_tool_input()),
    ])
    ctx = _ctx(client)

    events = []
    async for ev in synthesizer.run(
        SynthesizerIn(
            question="q",
            cited_articles=_articles(),
            cited_cases=_cases(),
        ),
        ctx=ctx,
    ):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(client.calls) == 2
    # Generic advisory (not the specific failure list)
    second_user = client.calls[1]["messages"][0]["content"]
    assert "emit_answer" in second_user
