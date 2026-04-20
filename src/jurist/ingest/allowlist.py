"""Single scope knob for ingestion. M1 ships 2 core BWBs; M1.5 widens."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BWBEntry:
    name: str                                       # full legal title
    label_prefix: str                               # human-readable prefix for ArticleNode.label
    filter_titel: tuple[str, ...] | None = None     # None = no filter; e.g., ("4",) = only Titel 4


BWB_ALLOWLIST: dict[str, BWBEntry] = {
    "BWBR0005290": BWBEntry(
        name="Burgerlijk Wetboek Boek 7",
        label_prefix="Boek 7",
        filter_titel=("4",),   # Huur only
    ),
    "BWBR0014315": BWBEntry(
        name="Uitvoeringswet huurprijzen woonruimte",
        label_prefix="Uhw",
    ),
}
