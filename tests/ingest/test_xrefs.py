from jurist.schemas import ArticleEdge, ArticleNode
from jurist.ingest.xrefs import extract_regex_edges, merge_edges


def _node(article_id: str, bwb: str, body: str = "") -> ArticleNode:
    return ArticleNode(
        article_id=article_id,
        bwb_id=bwb,
        label=article_id.rsplit("/", 1)[-1],
        title="",
        body_text=body,
        outgoing_refs=[],
    )


def test_regex_finds_same_bwb_reference():
    n248 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",
        "BWBR0005290",
        "zie artikel 249",
    )
    n249 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel249",
        "BWBR0005290",
    )
    edges = extract_regex_edges([n248, n249])
    assert len(edges) == 1
    assert edges[0].from_id == n248.article_id
    assert edges[0].to_id == n249.article_id
    assert edges[0].kind == "regex"


def test_regex_ignores_cross_bwb_mentions():
    n248 = _node(
        "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",
        "BWBR0005290",
        "artikel 10 van de Uitvoeringswet huurprijzen woonruimte",
    )
    edges = extract_regex_edges([n248])
    assert edges == [], "cross-BWB text mention must not produce a regex edge"


def test_merge_dedupe_explicit_wins():
    a = "BWBR0005290/.../Artikel248"
    b = "BWBR0005290/.../Artikel252"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex    = [ArticleEdge(from_id=a, to_id=b, kind="regex")]
    merged = merge_edges(explicit, regex)
    assert len(merged) == 1
    assert merged[0].kind == "explicit"


def test_merge_keeps_distinct_pairs():
    a = "BWBR0005290/.../Artikel248"
    b = "BWBR0005290/.../Artikel252"
    c = "BWBR0005290/.../Artikel253"
    explicit = [ArticleEdge(from_id=a, to_id=b, kind="explicit")]
    regex    = [
        ArticleEdge(from_id=a, to_id=c, kind="regex"),
        ArticleEdge(from_id=a, to_id=b, kind="regex"),  # duplicate of explicit pair
    ]
    merged = merge_edges(explicit, regex)
    assert len(merged) == 2
    by_target = {e.to_id: e.kind for e in merged}
    assert by_target[b] == "explicit"
    assert by_target[c] == "regex"
