from jurist.llm.prompts import render_decomposer_system


def test_render_decomposer_system_is_dutch_and_forbids_free_text():
    s = render_decomposer_system()
    assert "Nederlandse" in s or "huurrecht" in s
    assert "emit_decomposition" in s
    assert "vrije tekst" in s.lower() or "geen vrije tekst" in s.lower()
