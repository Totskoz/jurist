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
    assert prof.keyword_terms == ("huur", "verhuur", "woonruimte", "huurcommissie")


def test_unknown_profile_raises() -> None:
    from jurist.ingest.caselaw_profiles import resolve_profile
    with pytest.raises(KeyError):
        resolve_profile("nonexistent")


def test_resolve_returns_correct_profile() -> None:
    from jurist.ingest.caselaw_profiles import PROFILES, resolve_profile
    prof = resolve_profile("huurrecht")
    assert prof is PROFILES["huurrecht"]
