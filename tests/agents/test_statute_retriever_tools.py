from jurist.agents.statute_retriever_tools import make_snippet


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
