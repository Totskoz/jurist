from jurist.llm.prompts import render_decomposer_system


def test_render_decomposer_system_is_dutch_and_forbids_free_text():
    s = render_decomposer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_decomposition" in s
    assert "vrije tekst" in s.lower() or "geen vrije tekst" in s.lower()


def test_render_synthesizer_system_is_dutch_and_forbids_free_text():
    from jurist.llm.prompts import render_synthesizer_system

    s = render_synthesizer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_answer" in s
    # Instructs the model to go straight to the tool (Sonnet with forced
    # tool_choice skips pre-tool text anyway; the prompt stops asking for
    # it so the trace panel no longer advertises thinking that never arrives).
    assert "vrije tekst" in s.lower() or "geen vrije tekst" in s.lower() \
        or "direct" in s.lower()
    # Forbids citation outside the candidate set
    assert "kandidaten" in s.lower() or "meegeleverd" in s.lower()
    # Explicit verbatim requirement
    assert "verbatim" in s.lower() or "letterlijk" in s.lower()
