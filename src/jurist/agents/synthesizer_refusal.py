"""Pure helpers for the synthesizer's refusal branch (AQ8).

No LLM, no I/O. The agent module (`synthesizer.py`) calls `should_refuse`
to decide the early-branch and uses `ALLOWED_FALLBACK_DOMAINS` when
rendering the refusal prompt.
"""
from __future__ import annotations

from jurist.schemas import CaseRetrieverOut, StatuteRetrieverOut

ALLOWED_FALLBACK_DOMAINS: frozenset[str] = frozenset({
    "arbeidsrecht",
    "verzekeringsrecht",
    "burenrecht",
    "consumentenrecht",
    "familierecht",
    "algemeen",
})


def should_refuse(stat: StatuteRetrieverOut, case: CaseRetrieverOut) -> bool:
    """Early-branch refusal gate.

    Per M5 spec §6.2 / decision M5-2: both retrievers must flag low
    confidence for the pipeline to short-circuit a refusal. A strong
    match in either retriever keeps the synth on the normal path
    (where the synth itself can still self-judge a refusal).
    """
    return stat.low_confidence and case.low_confidence
