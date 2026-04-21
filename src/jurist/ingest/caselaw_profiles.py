"""Per-rechtsgebied profiles: subject URI + keyword fence terms.

Only `huurrecht` populated in M3a. Adding a second profile is a dict-entry
diff — no pipeline changes required.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaselawProfile:
    name: str
    subject_uri: str
    keyword_terms: tuple[str, ...]


PROFILES: dict[str, CaselawProfile] = {
    "huurrecht": CaselawProfile(
        name="huurrecht",
        subject_uri=(
            "http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht"
        ),
        keyword_terms=("huur", "verhuur", "woonruimte", "huurcommissie"),
    ),
}


def resolve_profile(name: str) -> CaselawProfile:
    """Look up a profile by name. Raises KeyError for unknown names."""
    if name not in PROFILES:
        raise KeyError(f"Unknown caselaw profile: {name!r}. Available: {list(PROFILES)}")
    return PROFILES[name]
