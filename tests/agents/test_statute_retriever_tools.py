import pytest

from jurist.agents.statute_retriever_tools import ToolExecutor, ToolResult, make_snippet
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleEdge, ArticleNode, KGSnapshot


@pytest.fixture
def fixture_kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="A",
            bwb_id="BWBX",
            label="Art A",
            title="Title A",
            body_text="Body of A with refs to B.",
            outgoing_refs=["B"],
        ),
        ArticleNode(
            article_id="B",
            bwb_id="BWBX",
            label="Art B",
            title="Title B",
            body_text="Body of B, short.",
            outgoing_refs=[],
        ),
        ArticleNode(
            article_id="C",
            bwb_id="BWBX",
            label="Art C",
            title="Title C",
            body_text="About rent and rent again.",
            outgoing_refs=[],
        ),
    ]
    edges = [ArticleEdge(from_id="A", to_id="B", kind="explicit")]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=edges)
    return NetworkXKG.from_snapshot(snap)


def test_make_snippet_short_passes_through():
    assert make_snippet("kort") == "kort"


def test_make_snippet_collapses_whitespace():
    assert make_snippet("foo\n\nbar\tbaz") == "foo bar baz"


def test_make_snippet_truncates_at_word_boundary():
    # 300-char string of "word " repeated → truncated before the cutoff word
    body = "word " * 100
    result = make_snippet(body, max_chars=30)
    assert result.endswith("…")
    # No partial word before the ellipsis
    trimmed = result.rstrip("…").rstrip()
    assert not trimmed.endswith("wor")  # would mean we cut mid-word
    assert len(trimmed) <= 30


def test_make_snippet_no_ellipsis_when_exact_fit():
    body = "a" * 50
    assert make_snippet(body, max_chars=50) == body


@pytest.mark.asyncio
async def test_get_article_returns_body_and_outgoing_refs(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {"article_id": "A"})
    assert isinstance(r, ToolResult)
    assert not r.is_error
    assert r.extra["article_id"] == "A"
    assert r.extra["body_text"] == "Body of A with refs to B."
    assert r.extra["outgoing_refs"] == ["B"]
    assert r.kg_effect == {"node_visited": "A"}
    assert "Art A" in r.result_summary


@pytest.mark.asyncio
async def test_get_article_unknown_id_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {"article_id": "MISSING"})
    assert r.is_error
    assert "unknown" in r.result_summary.lower()
    assert r.kg_effect is None


@pytest.mark.asyncio
async def test_get_article_missing_arg_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("get_article", {})
    assert r.is_error
    assert r.kg_effect is None


@pytest.mark.asyncio
async def test_list_neighbors_returns_labels_and_titles(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "A"})
    assert not r.is_error
    neighbors = r.extra["neighbors"]
    assert neighbors == [{"article_id": "B", "label": "Art B", "title": "Title B"}]
    # neighbor_ids also surfaced for frontend chips
    assert r.extra["neighbor_ids"] == ["B"]
    assert r.kg_effect is None  # peek, no visit


@pytest.mark.asyncio
async def test_list_neighbors_empty_for_leaf(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "B"})
    assert not r.is_error
    assert r.extra["neighbors"] == []
    assert r.extra["neighbor_ids"] == []


@pytest.mark.asyncio
async def test_list_neighbors_unknown_id_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("list_neighbors", {"article_id": "MISSING"})
    assert r.is_error


@pytest.mark.asyncio
async def test_follow_cross_ref_returns_body_and_edge_effect(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "B"}
    )
    assert not r.is_error
    assert r.extra["body_text"] == "Body of B, short."
    assert r.kg_effect == {"edge_traversed": ("A", "B"), "node_visited": "B"}


@pytest.mark.asyncio
async def test_follow_cross_ref_missing_edge_errors_with_hint(fixture_kg):
    # Both nodes exist but no edge A→C in the fixture.
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "C"}
    )
    assert r.is_error
    assert "get_article" in r.result_summary
    assert r.kg_effect is None


@pytest.mark.asyncio
async def test_follow_cross_ref_unknown_from_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "MISSING", "to_id": "B"}
    )
    assert r.is_error


@pytest.mark.asyncio
async def test_follow_cross_ref_unknown_to_errors(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "follow_cross_ref", {"from_id": "A", "to_id": "MISSING"}
    )
    assert r.is_error


@pytest.mark.asyncio
async def test_search_articles_ranks_rent_over_unrelated(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    # "rent" appears twice in C ("rent and rent again"), zero times in A/B.
    r = await exec_.execute("search_articles", {"query": "rent", "top_k": 3})
    assert not r.is_error
    ids = [h["article_id"] for h in r.extra["hits"]]
    assert ids[0] == "C"
    # hit_ids surfaced for frontend chips
    assert r.extra["hit_ids"] == ids


@pytest.mark.asyncio
async def test_search_articles_respects_top_k(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "search_articles", {"query": "body", "top_k": 1}
    )
    assert len(r.extra["hits"]) == 1


@pytest.mark.asyncio
async def test_search_articles_empty_query_returns_empty(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("search_articles", {"query": "", "top_k": 5})
    assert not r.is_error
    assert r.extra["hits"] == []
    assert r.extra["hit_ids"] == []


@pytest.mark.asyncio
async def test_done_validates_known_ids(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [
            {"article_id": "A", "reason": "core rule"},
            {"article_id": "B", "reason": "procedure"},
        ]},
    )
    assert not r.is_error
    assert r.extra["selected_count"] == 2


@pytest.mark.asyncio
async def test_done_rejects_unknown_id(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [
            {"article_id": "A", "reason": "ok"},
            {"article_id": "NOPE", "reason": "bad"},
        ]},
    )
    assert r.is_error
    assert "NOPE" in r.result_summary


@pytest.mark.asyncio
async def test_done_empty_selected_is_allowed(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute("done", {"selected": []})
    assert not r.is_error
    assert r.extra["selected_count"] == 0


@pytest.mark.asyncio
async def test_done_rejects_missing_reason(fixture_kg):
    exec_ = ToolExecutor(fixture_kg)
    r = await exec_.execute(
        "done",
        {"selected": [{"article_id": "A"}]},  # no reason
    )
    assert r.is_error
