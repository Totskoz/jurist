import pytest

from jurist.kg.networkx_kg import NetworkXKG
from jurist.llm.prompts import render_statute_retriever_system
from jurist.schemas import ArticleNode, KGSnapshot


@pytest.fixture
def tiny_kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="X1",
            bwb_id="BWBX",
            label="Art X1",
            title="Titel X1",
            body_text="Over huurverhoging.",
            outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    return NetworkXKG.from_snapshot(snap)


def test_render_contains_policies_and_catalog(tiny_kg):
    rendered = render_statute_retriever_system(tiny_kg, snippet_chars=200)
    assert "Dutch tenancy-law" in rendered
    assert "Target 3–6 cited articles" in rendered
    assert "{{ARTICLE_CATALOG}}" not in rendered  # substituted
    # Catalog line present
    assert '[X1] "Art X1" — Titel X1: Over huurverhoging.' in rendered


def test_render_is_deterministic(tiny_kg):
    a = render_statute_retriever_system(tiny_kg)
    b = render_statute_retriever_system(tiny_kg)
    assert a == b
