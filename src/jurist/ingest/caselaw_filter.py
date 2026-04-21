"""Lenient keyword fence for post-download filtering."""
from __future__ import annotations

from jurist.ingest.caselaw_profiles import PROFILES

HUURRECHT_TERMS = PROFILES["huurrecht"].keyword_terms


def passes(body_text: str, *, terms: tuple[str, ...] = HUURRECHT_TERMS) -> bool:
    """True iff `body_text` contains any `terms` (case-folded substring).

    Empty body → False. No word-boundary requirement — substring match
    catches inflections (huurder, huurders, huurprijs, verhuurder, etc.)
    without a morphology list.
    """
    if not body_text:
        return False
    lower = body_text.casefold()
    return any(term.casefold() in lower for term in terms)
