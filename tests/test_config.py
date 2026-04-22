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
    ctx = RunContext(
        kg=object(), llm=object(),
        case_store=object(), embedder=object(),
    )
    assert ctx.kg is not None
    assert ctx.llm is not None
    assert ctx.case_store is not None
    assert ctx.embedder is not None
    with __import__("pytest").raises(Exception):  # FrozenInstanceError
        ctx.kg = object()  # type: ignore[misc]


def test_m3a_settings_defaults() -> None:
    from jurist.config import settings
    assert settings.caselaw_profile == "huurrecht"
    assert settings.caselaw_subject_uri is None  # profile default resolves later
    assert settings.caselaw_since == "2024-01-01"
    assert settings.caselaw_max_list is None
    assert settings.caselaw_fetch_workers == 5
    assert settings.caselaw_chunk_words == 500
    assert settings.caselaw_chunk_overlap == 50
    assert settings.embed_model == "BAAI/bge-m3"
    assert settings.embed_batch == 32


def test_m3a_settings_env_overrides(monkeypatch) -> None:
    import importlib

    import jurist.config
    monkeypatch.setenv("JURIST_CASELAW_SINCE", "2020-01-01")
    monkeypatch.setenv("JURIST_CASELAW_FETCH_WORKERS", "10")
    monkeypatch.setenv("JURIST_CASELAW_CHUNK_WORDS", "300")
    monkeypatch.setenv("JURIST_EMBED_BATCH", "16")
    importlib.reload(jurist.config)
    from jurist.config import settings as reloaded
    assert reloaded.caselaw_since == "2020-01-01"
    assert reloaded.caselaw_fetch_workers == 10
    assert reloaded.caselaw_chunk_words == 300
    assert reloaded.embed_batch == 16
    # Reset for other tests
    importlib.reload(jurist.config)


def test_caselaw_max_list_env_variants(monkeypatch) -> None:
    import importlib

    import jurist.config

    # empty string (from `.env` with bare assignment) -> None
    monkeypatch.setenv("JURIST_CASELAW_MAX_LIST", "")
    importlib.reload(jurist.config)
    assert jurist.config.settings.caselaw_max_list is None

    # "0" -> None (explicit "no cap" override)
    monkeypatch.setenv("JURIST_CASELAW_MAX_LIST", "0")
    importlib.reload(jurist.config)
    assert jurist.config.settings.caselaw_max_list is None

    # positive int -> that int
    monkeypatch.setenv("JURIST_CASELAW_MAX_LIST", "100")
    importlib.reload(jurist.config)
    assert jurist.config.settings.caselaw_max_list == 100

    # Reset for later tests
    monkeypatch.delenv("JURIST_CASELAW_MAX_LIST", raising=False)
    importlib.reload(jurist.config)


def test_settings_defaults_m3b() -> None:
    from jurist.config import Settings
    s = Settings()
    assert s.model_rerank == "claude-haiku-4-5-20251001"
    assert s.caselaw_candidate_chunks == 150
    assert s.caselaw_candidate_eclis == 20
    assert s.caselaw_rerank_snippet_chars == 400


def test_settings_m3b_env_overrides(monkeypatch) -> None:
    import importlib

    import jurist.config
    monkeypatch.setenv("JURIST_MODEL_RERANK", "claude-sonnet-4-6")
    monkeypatch.setenv("JURIST_CASELAW_CANDIDATE_CHUNKS", "200")
    monkeypatch.setenv("JURIST_CASELAW_CANDIDATE_ECLIS", "25")
    monkeypatch.setenv("JURIST_CASELAW_RERANK_SNIPPET_CHARS", "500")
    importlib.reload(jurist.config)
    from jurist.config import settings as reloaded
    assert reloaded.model_rerank == "claude-sonnet-4-6"
    assert reloaded.caselaw_candidate_chunks == 200
    assert reloaded.caselaw_candidate_eclis == 25
    assert reloaded.caselaw_rerank_snippet_chars == 500
    # Reset for other tests
    importlib.reload(jurist.config)


def test_m4_settings_defaults():
    from jurist.config import settings

    assert settings.model_decomposer == "claude-haiku-4-5-20251001"
    assert settings.model_synthesizer == "claude-sonnet-4-6"
    assert settings.synthesizer_max_tokens == 8192
