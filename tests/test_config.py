from pathlib import Path

from jurist.config import RunContext, Settings, settings


def test_kg_path_defaults_under_data_dir():
    assert settings.kg_path.parts[-2:] == ("kg", "huurrecht.json")
    assert isinstance(settings.kg_path, Path)


def test_settings_exposes_m2_fields():
    s = Settings()
    assert s.model_retriever == "claude-sonnet-4-6"
    assert s.max_retriever_iters == 15
    assert s.retriever_wall_clock_cap_s == 90.0
    assert s.statute_catalog_snippet_chars == 200


def test_runcontext_is_frozen_dataclass():
    ctx = RunContext(kg=object(), llm=object())
    assert ctx.kg is not None
    assert ctx.llm is not None
    with __import__("pytest").raises(Exception):  # FrozenInstanceError
        ctx.kg = object()  # type: ignore[misc]
