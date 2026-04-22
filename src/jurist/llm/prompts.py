"""Prompt template loading + rendering."""
from __future__ import annotations

from pathlib import Path

from jurist.agents.statute_retriever_tools import build_catalog
from jurist.kg.interface import KnowledgeGraph

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def render_statute_retriever_system(
    kg: KnowledgeGraph,
    *,
    snippet_chars: int = 200,
) -> str:
    """Load statute_retriever.system.md and substitute the article catalog."""
    template = (_PROMPTS_DIR / "statute_retriever.system.md").read_text(encoding="utf-8")
    catalog = build_catalog(kg, snippet_chars=snippet_chars)
    return template.replace("{{ARTICLE_CATALOG}}", catalog)


_CASE_RERANK_SYSTEM = """\
Je bent een Nederlandse juridische annotator. Je krijgt een huurrecht-vraag, \
relevante wetsartikelen uit de Nederlandse kennisgraaf, en een lijst \
kandidaat-uitspraken uit de rechtspraak. Kies exact 3 uitspraken die het \
meest relevant zijn voor de vraag en de juridische context van de \
wetsartikelen.

Schrijf voor elke keuze een korte Nederlandse reden (1–2 zinnen) die uitlegt \
waarom deze uitspraak relevant is — verwijs naar feitelijke gelijkenis met \
de vraag, juridische strekking, of toepassing van de genoemde artikelen. \
Gebruik uitsluitend de ECLI's die in de kandidaten-lijst staan.

Roep het hulpmiddel `select_cases` aan met precies 3 keuzes. Geen vrije \
tekst daarbuiten.
"""


def render_case_rerank_system() -> str:
    """Static Dutch system prompt for the Haiku rerank call (M3b).
    Marked cacheable by the agent via `cache_control: ephemeral`."""
    return _CASE_RERANK_SYSTEM


_DECOMPOSER_SYSTEM = """\
Je bent een Nederlandse juridische assistent gespecialiseerd in huurrecht.
Je decomposeert huurrecht-vragen in 1–5 sub-vragen, 1–10 juridische concepten
(Nederlandse termen, niet vertaald), en een intentie uit {legality_check,
calculation, procedure, other}.
Roep uitsluitend het hulpmiddel `emit_decomposition` aan. Geen vrije tekst.
"""


def render_decomposer_system() -> str:
    """Static Dutch system prompt for the M4 decomposer Haiku call."""
    return _DECOMPOSER_SYSTEM
