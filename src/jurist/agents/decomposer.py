"""M4 real decomposer: Haiku forced-tool call with one-regen-then-hard-fail."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from jurist.config import RunContext, settings
from jurist.llm.prompts import render_decomposer_system
from jurist.schemas import DecomposerIn, DecomposerOut, TraceEvent

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1000


class InvalidDecomposerOutput(Exception):
    """Raised by a single attempt when the Haiku response doesn't contain a
    valid `emit_decomposition` tool_use. Caught inside the regen helper;
    a second occurrence is wrapped in DecomposerFailedError."""


class DecomposerFailedError(Exception):
    """Propagates to the orchestrator as run_failed{reason:"decomposition"}."""


def _build_decomposer_tool_schema() -> dict[str, Any]:
    return {
        "name": "emit_decomposition",
        "description": (
            "Decomposeer een Nederlandse huurrecht-vraag in sub-vragen, "
            "concepten, intentie, en huurtype-hypothese."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_questions": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "items": {"type": "string", "minLength": 5},
                },
                "concepts": {
                    "type": "array", "minItems": 1, "maxItems": 10,
                    "items": {"type": "string", "minLength": 2},
                },
                "intent": {
                    "type": "string",
                    "enum": ["legality_check", "calculation", "procedure", "other"],
                },
                "huurtype_hypothese": {
                    "type": "string",
                    "enum": ["sociale", "middeldure", "vrije", "onbekend"],
                },
            },
            "required": ["sub_questions", "concepts", "intent", "huurtype_hypothese"],
        },
    }



def _extract_tool_use(response: Any, expected_name: str):
    for block in getattr(response, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == expected_name
        ):
            return block
    raise InvalidDecomposerOutput(
        f"no tool_use block named {expected_name!r} in response"
    )


async def _decompose_once(
    client: Any,
    system: str,
    user: str,
    schema: dict[str, Any],
) -> DecomposerOut:
    response = await client.messages.create(
        model=settings.model_decomposer,
        system=system,
        tools=[schema],
        tool_choice={"type": "tool", "name": "emit_decomposition"},
        messages=[{"role": "user", "content": user}],
        max_tokens=_MAX_TOKENS,
    )
    tool_use = _extract_tool_use(response, "emit_decomposition")
    try:
        return DecomposerOut.model_validate(tool_use.input)
    except ValidationError as e:
        raise InvalidDecomposerOutput(f"schema validation failed: {e}") from e


async def _decompose_with_retry(
    client: Any, system: str, user: str, schema: dict[str, Any],
) -> DecomposerOut:
    try:
        return await _decompose_once(client, system, user, schema)
    except InvalidDecomposerOutput as first_err:
        logger.warning(
            "decomposer attempt 1 invalid: %s — retrying once", first_err,
        )
        user_retry = (
            user + "\n\n"
            f"Je vorige antwoord was ongeldig ({first_err}). "
            "Roep `emit_decomposition` aan met geldige velden."
        )
        try:
            return await _decompose_once(client, system, user_retry, schema)
        except InvalidDecomposerOutput as second_err:
            raise DecomposerFailedError(
                f"decomposer invalid after retry: {second_err}"
            ) from second_err


async def run(
    input: DecomposerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_decomposer_system()
    user = (
        f"Vraag: {input.question}\n\n"
        "Decomposeer deze vraag via `emit_decomposition`."
    )
    schema = _build_decomposer_tool_schema()

    out = await _decompose_with_retry(ctx.llm, system, user, schema)
    yield TraceEvent(type="decomposition_done", data={
        "sub_questions": list(out.sub_questions),
        "concepts": list(out.concepts),
        "intent": out.intent,
        "huurtype_hypothese": out.huurtype_hypothese,
    })
    yield TraceEvent(type="agent_finished", data=out.model_dump())


__all__ = [
    "run",
    "_build_decomposer_tool_schema",
    "DecomposerFailedError",
    "InvalidDecomposerOutput",
]
