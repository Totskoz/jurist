"""M5 — pure helpers for the synthesizer's refusal branch."""
import pytest

from jurist.agents.synthesizer_refusal import (
    ALLOWED_FALLBACK_DOMAINS,
    should_refuse,
)
from jurist.fakes import FAKE_CASES, FAKE_STATUTE_OUT
from jurist.schemas import CaseRetrieverOut, StatuteRetrieverOut


def _stat(low: bool) -> StatuteRetrieverOut:
    return FAKE_STATUTE_OUT.model_copy(update={"low_confidence": low})


def _case(low: bool) -> CaseRetrieverOut:
    return CaseRetrieverOut(cited_cases=FAKE_CASES, low_confidence=low)


@pytest.mark.parametrize("stat_low,case_low,expected", [
    (True,  True,  True),
    (True,  False, False),
    (False, True,  False),
    (False, False, False),
])
def test_should_refuse_truth_table(stat_low, case_low, expected):
    assert should_refuse(_stat(stat_low), _case(case_low)) is expected


def test_allowed_fallback_domains_is_closed_set():
    assert set(ALLOWED_FALLBACK_DOMAINS) == {
        "arbeidsrecht",
        "verzekeringsrecht",
        "burenrecht",
        "consumentenrecht",
        "familierecht",
        "algemeen",
    }
