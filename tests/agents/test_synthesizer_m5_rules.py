"""M5 spec-guard tests — AQ1 procedure routing + AQ2 EU escalation + AQ8 refusal.

These are promptless unit tests: they assert that the system prompt text
contains the M5 rules. They do NOT assert that the live Sonnet model
obeys the rules (that's integration scope).
"""
import re

from jurist.llm.prompts import render_synthesizer_system


def test_synthesizer_system_prompt_contains_aq1_routing_rules():
    prompt = render_synthesizer_system()
    assert "huurtype_hypothese" in prompt
    for segment in ("sociale", "middeldure", "vrije", "onbekend"):
        assert segment in prompt, f"Missing huurtype segment: {segment}"
    assert re.search(r"Stapel NOOIT.*7:248.*7:253", prompt)


def test_synthesizer_system_prompt_contains_aq2_escalation_rule():
    prompt = render_synthesizer_system()
    assert "Richtlijn 93/13" in prompt
    assert "algehele vernietiging" in prompt
    assert "consumenten-route" in prompt or "consumentenroute" in prompt


def test_synthesizer_system_prompt_contains_aq8_refusal_rule():
    prompt = render_synthesizer_system()
    assert "insufficient_context" in prompt
    assert "insufficient_context_reason" in prompt
    # Closed-set domains (6 per parent spec)
    for d in ["arbeidsrecht", "verzekeringsrecht", "burenrecht",
              "consumentenrecht", "familierecht", "algemeen"]:
        assert d in prompt, f"Missing domain: {d}"
