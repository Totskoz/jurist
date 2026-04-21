def test_render_case_rerank_system_is_dutch_and_non_empty() -> None:
    from jurist.llm.prompts import render_case_rerank_system
    text = render_case_rerank_system()
    assert isinstance(text, str)
    assert len(text) > 100
    # Dutch-specific markers
    lower = text.casefold()
    assert "nederlandse" in lower or "nederlands" in lower
    # Mention the task shape
    assert "uitspra" in lower
    assert "select_cases" in text


def test_render_case_rerank_system_is_stable_across_calls() -> None:
    from jurist.llm.prompts import render_case_rerank_system
    assert render_case_rerank_system() == render_case_rerank_system()
