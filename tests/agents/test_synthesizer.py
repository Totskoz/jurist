"""Unit tests for the M4 synthesizer agent."""
from __future__ import annotations

import pytest

from jurist.agents import synthesizer
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
