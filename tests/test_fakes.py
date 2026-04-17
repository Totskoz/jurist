from jurist.fakes import FAKE_ANSWER, FAKE_CASES, FAKE_KG, FAKE_VISIT_PATH
from jurist.schemas import ArticleEdge, ArticleNode, CitedCase, StructuredAnswer


def test_fake_kg_has_minimum_nodes_and_edges():
    nodes, edges = FAKE_KG
    assert len(nodes) >= 8
    assert len(edges) >= 10
    assert all(isinstance(n, ArticleNode) for n in nodes)
    assert all(isinstance(e, ArticleEdge) for e in edges)


def test_fake_kg_contains_artikel_248():
    nodes, _ = FAKE_KG
    ids = [n.article_id for n in nodes]
    assert any("Artikel248" in i for i in ids)


def test_fake_kg_edges_reference_existing_nodes():
    nodes, edges = FAKE_KG
    ids = {n.article_id for n in nodes}
    for e in edges:
        assert e.from_id in ids, f"edge from {e.from_id} not in node set"
        assert e.to_id in ids, f"edge to {e.to_id} not in node set"


def test_fake_visit_path_is_subset_of_kg():
    nodes, edges = FAKE_KG
    ids = {n.article_id for n in nodes}
    edge_set = {(e.from_id, e.to_id) for e in edges}
    assert len(FAKE_VISIT_PATH) >= 3
    for aid in FAKE_VISIT_PATH:
        assert aid in ids
    for a, b in zip(FAKE_VISIT_PATH, FAKE_VISIT_PATH[1:]):
        assert (a, b) in edge_set, f"no edge {a} -> {b} in KG"


def test_fake_cases_three_entries_with_real_looking_ecli():
    assert len(FAKE_CASES) == 3
    assert all(isinstance(c, CitedCase) for c in FAKE_CASES)
    assert all(c.ecli.startswith("ECLI:NL:") for c in FAKE_CASES)


def test_fake_answer_has_citations_matching_fake_kg():
    assert isinstance(FAKE_ANSWER, StructuredAnswer)
    nodes, _ = FAKE_KG
    bwb_ids = {n.bwb_id for n in nodes}
    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        assert cit.bwb_id in bwb_ids
    ecli_set = {c.ecli for c in FAKE_CASES}
    for cit in FAKE_ANSWER.vergelijkbare_uitspraken:
        assert cit.ecli in ecli_set
