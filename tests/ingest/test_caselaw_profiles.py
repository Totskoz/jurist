"""Tests for CaselawProfile registry."""
from __future__ import annotations

import pytest


def test_huurrecht_profile_has_expected_terms() -> None:
    from jurist.ingest.caselaw_profiles import PROFILES
    prof = PROFILES["huurrecht"]
    assert prof.name == "huurrecht"
    assert prof.subject_uri == (
        "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
    )
    # Check M4 baseline terms are present (subset check — M5 expanded the tuple)
    terms = set(prof.keyword_terms)
    assert "huur" in terms
    assert "verhuur" in terms
    assert "woonruimte" in terms
    assert "huurcommissie" in terms


def test_unknown_profile_raises() -> None:
    from jurist.ingest.caselaw_profiles import resolve_profile
    with pytest.raises(KeyError):
        resolve_profile("nonexistent")


def test_resolve_returns_correct_profile() -> None:
    from jurist.ingest.caselaw_profiles import PROFILES, resolve_profile
    prof = resolve_profile("huurrecht")
    assert prof is PROFILES["huurrecht"]


# ---------------------------------------------------------------------------
# M5 — fence expansion (Task 14)
# ---------------------------------------------------------------------------

def test_huurrecht_fence_contains_m5_additions():
    from jurist.ingest.caselaw_profiles import PROFILES
    profile = PROFILES["huurrecht"]
    terms = set(t.lower() for t in profile.keyword_terms)
    # M4 baseline
    assert "huur" in terms
    assert "verhuur" in terms
    assert "woonruimte" in terms
    assert "huurcommissie" in terms
    # M5 additions
    assert "huurverhoging" in terms
    assert "huurprijs" in terms
    assert "indexering" in terms
    assert "oneerlijk beding" in terms
    assert "onredelijk beding" in terms


def test_fence_accepts_sample_m5_text():
    """A chunk mentioning 'oneerlijk beding' but not 'huur' should now pass."""
    from jurist.ingest.caselaw_profiles import PROFILES, passes_fence
    text = "Het oneerlijk beding wordt vernietigd op grond van Richtlijn 93/13/EEG."
    assert passes_fence(text, PROFILES["huurrecht"]) is True


def test_fence_rejects_clearly_off_topic():
    """Sanity — car-insurance text should not pass the huurrecht fence."""
    from jurist.ingest.caselaw_profiles import PROFILES, passes_fence
    text = "De verzekerde auto was bij een aanrijding betrokken en de WAM-verzekeraar wees dekking af."  # noqa: E501
    assert passes_fence(text, PROFILES["huurrecht"]) is False
