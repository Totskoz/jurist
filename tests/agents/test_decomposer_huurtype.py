"""M5 — decomposer huurtype_hypothese classification."""
from __future__ import annotations

import pytest

from jurist.agents.decomposer import run as decomposer_run
from jurist.config import RunContext
from jurist.schemas import DecomposerIn, DecomposerOut
from tests.fixtures.mock_llm import MockAnthropicForRerank


def _ctx_with_huurtype(huurtype: str) -> RunContext:
    """RunContext scripted to return a decomposer tool output with the given huurtype."""
    return RunContext(
        llm=MockAnthropicForRerank([
            {
                "sub_questions": ["Mag een huurverhoging X?"],
                "concepts": ["huurprijs"],
                "intent": "legality_check",
                "huurtype_hypothese": huurtype,
            }
        ]),
        kg=None,            # type: ignore[arg-type]
        case_store=None,    # type: ignore[arg-type]
        embedder=None,      # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("question,expected", [
    ("Mijn sociale huurwoning kreeg een verhoging, mag dat?", "sociale"),
    ("Mijn middenhuurwoning kreeg een verhoging, mag dat?", "middeldure"),
    ("Ik huur in de vrije sector, mag de verhuurder verhogen?", "vrije"),
    ("Mijn verhuurder wil de huur verhogen, mag dat?", "onbekend"),
])
async def test_decomposer_emits_huurtype_hypothese(question, expected):
    ctx = _ctx_with_huurtype(expected)
    events = [ev async for ev in decomposer_run(DecomposerIn(question=question), ctx=ctx)]
    final = events[-1]
    assert final.type == "agent_finished"
    out = DecomposerOut.model_validate(final.data)
    assert out.huurtype_hypothese == expected


@pytest.mark.asyncio
async def test_decomposer_prompt_contains_huurtype_classification_rules():
    """Prompt stability: the Dutch classifier rules must be present."""
    from jurist.llm.prompts import render_decomposer_system
    prompt = render_decomposer_system()
    assert "huurtype_hypothese" in prompt
    assert "sociale" in prompt and "middeldure" in prompt and "vrije" in prompt
    assert "onbekend" in prompt


def test_decomposer_tool_schema_has_huurtype_enum():
    """Tool schema extends with the new enum property."""
    from jurist.agents.decomposer import _build_decomposer_tool_schema
    schema = _build_decomposer_tool_schema()
    props = schema["input_schema"]["properties"]
    assert "huurtype_hypothese" in props
    assert props["huurtype_hypothese"]["enum"] == ["sociale", "middeldure", "vrije", "onbekend"]
    assert "huurtype_hypothese" in schema["input_schema"]["required"]
