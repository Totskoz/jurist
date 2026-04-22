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
        keyword_terms=(
            # M4 baseline
            "huur", "verhuur", "woonruimte", "huurcommissie",
            # M5 additions — AQ3: EU-consumer-directive language without M4 huur-keywords
            "huurverhoging", "huurprijs", "indexering",
            "oneerlijk beding", "onredelijk beding",
        ),
    ),
}


def passes_fence(text: str, profile: CaselawProfile) -> bool:
    """Case-insensitive whole-substring match against any profile term.

    Multi-word terms (e.g. 'oneerlijk beding') are matched as a single
    contiguous substring; whole-token boundaries are not required.
    """
    body = text.lower()
    return any(term.lower() in body for term in profile.keyword_terms)


def resolve_profile(name: str) -> CaselawProfile:
    """Look up a profile by name. Raises KeyError for unknown names."""
    if name not in PROFILES:
        raise KeyError(f"Unknown caselaw profile: {name!r}. Available: {list(PROFILES)}")
    return PROFILES[name]
