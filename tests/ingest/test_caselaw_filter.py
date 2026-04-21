"""Tests for lenient keyword fence."""
from __future__ import annotations


def test_empty_body_does_not_pass() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("") is False


def test_body_without_huur_terms_does_not_pass() -> None:
    from jurist.ingest.caselaw_filter import passes
    body = "De echtgenoot verzoekt een wijziging van de alimentatie."
    assert passes(body) is False


def test_body_with_huur_substring_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De huurder heeft de huurprijs betaald.") is True


def test_body_with_verhuur_substring_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De verhuurder heeft opgezegd.") is True


def test_body_with_woonruimte_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("Een zelfstandige woonruimte in Amsterdam.") is True


def test_body_with_huurcommissie_passes() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("De Huurcommissie heeft beslist.") is True


def test_case_folded_match() -> None:
    from jurist.ingest.caselaw_filter import passes
    assert passes("WOONRUIMTE") is True
    assert passes("Woonruimte") is True


def test_custom_terms_override_default() -> None:
    from jurist.ingest.caselaw_filter import passes
    # Default `huur` not in body; custom term `pacht` is.
    assert passes("De pachter heeft het land bewerkt.", terms=("pacht",)) is True
    assert passes("De pachter heeft het land bewerkt.") is False
