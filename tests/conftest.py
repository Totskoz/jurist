"""Shared pytest configuration."""
import pytest

from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import MockAnthropicClient


@pytest.fixture
def minimal_ctx_factory():
    """Returns a callable that builds a RunContext with a tiny KG and the
    supplied script. Use `ctx = factory(script)` in tests."""

    def _make(script):
        nodes = [
            ArticleNode(
                article_id="A", bwb_id="BWBX", label="Art A", title="T",
                body_text="body", outgoing_refs=[],
            ),
        ]
        snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
        kg = NetworkXKG.from_snapshot(snap)
        mock = MockAnthropicClient(script)
        return RunContext(kg=kg, llm=mock)

    return _make
