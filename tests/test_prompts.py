from jurist.llm.prompts import render_decomposer_system


def test_render_decomposer_system_is_dutch_and_forbids_free_text():
    s = render_decomposer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_decomposition" in s
    assert "vrije tekst" in s.lower() or "geen vrije tekst" in s.lower()


def test_render_synthesizer_system_is_dutch_and_encourages_thinking():
    from jurist.llm.prompts import render_synthesizer_system

    s = render_synthesizer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_answer" in s
    # Encourages pre-tool reasoning (agent_thinking events)
    assert "Denk" in s or "denk" in s
    # Forbids citation outside the candidate set
    assert "kandidaten" in s.lower() or "meegeleverd" in s.lower()
    # Explicit verbatim requirement
    assert "verbatim" in s.lower() or "letterlijk" in s.lower()
