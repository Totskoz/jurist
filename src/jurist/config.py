"""Settings object + per-run context. Expands as milestones land."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from jurist.embedding import Embedder
    from jurist.kg.interface import KnowledgeGraph
    from jurist.vectorstore import CaseStore

load_dotenv()


@dataclass(frozen=True)
class Settings:
    max_history_per_run: int = int(os.getenv("JURIST_MAX_HISTORY_PER_RUN", "2000"))
    cors_allow_origin: str = os.getenv("JURIST_CORS_ORIGIN", "http://localhost:5173")
    data_dir: Path = Path(os.getenv("JURIST_DATA_DIR", "./data"))

    # M2 — statute retriever
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_max_retries: int = int(os.getenv("JURIST_ANTHROPIC_MAX_RETRIES", "8"))
    model_retriever: str = os.getenv("JURIST_MODEL_RETRIEVER", "claude-sonnet-4-6")
    max_retriever_iters: int = int(os.getenv("JURIST_MAX_RETRIEVER_ITERS", "15"))
    retriever_wall_clock_cap_s: float = float(
        os.getenv("JURIST_RETRIEVER_WALL_CLOCK_CAP_S", "90")
    )
    statute_catalog_snippet_chars: int = int(
        os.getenv("JURIST_STATUTE_CATALOG_SNIPPET_CHARS", "200")
    )

    # M3a — caselaw ingestion
    caselaw_profile: str = os.getenv("JURIST_CASELAW_PROFILE", "huurrecht")
    caselaw_subject_uri: str | None = os.getenv("JURIST_CASELAW_SUBJECT_URI")
    caselaw_since: str = os.getenv("JURIST_CASELAW_SINCE", "2024-01-01")
    caselaw_max_list: int | None = (
        int(v) or None
        if (v := os.getenv("JURIST_CASELAW_MAX_LIST", "").strip())
        else None
    )
    caselaw_fetch_workers: int = int(os.getenv("JURIST_CASELAW_FETCH_WORKERS", "5"))
    caselaw_chunk_words: int = int(os.getenv("JURIST_CASELAW_CHUNK_WORDS", "500"))
    caselaw_chunk_overlap: int = int(os.getenv("JURIST_CASELAW_CHUNK_OVERLAP", "50"))
    embed_model: str = os.getenv("JURIST_EMBED_MODEL", "BAAI/bge-m3")
    embed_batch: int = int(os.getenv("JURIST_EMBED_BATCH", "32"))

    # M3b — case retriever
    model_rerank: str = os.getenv(
        "JURIST_MODEL_RERANK", "claude-haiku-4-5-20251001"
    )
    caselaw_candidate_chunks: int = int(
        os.getenv("JURIST_CASELAW_CANDIDATE_CHUNKS", "150")
    )
    caselaw_candidate_eclis: int = int(
        os.getenv("JURIST_CASELAW_CANDIDATE_ECLIS", "20")
    )
    caselaw_rerank_snippet_chars: int = int(
        os.getenv("JURIST_CASELAW_RERANK_SNIPPET_CHARS", "400")
    )

    # M4 — decomposer + synthesizer
    model_decomposer: str = os.getenv(
        "JURIST_MODEL_DECOMPOSER", "claude-haiku-4-5-20251001"
    )
    model_synthesizer: str = os.getenv(
        "JURIST_MODEL_SYNTHESIZER", "claude-sonnet-4-6"
    )
    synthesizer_max_tokens: int = int(
        os.getenv("JURIST_SYNTHESIZER_MAX_TOKENS", "8192")
    )

    # M5 — case retriever low-confidence threshold
    case_similarity_floor: float = float(
        os.getenv("JURIST_CASE_SIMILARITY_FLOOR", "0.55")
    )

    @property
    def kg_path(self) -> Path:
        return self.data_dir / "kg" / "huurrecht.json"

    @property
    def lance_path(self) -> Path:
        return self.data_dir / "lancedb" / "cases.lance"

    @property
    def cases_dir(self) -> Path:
        return self.data_dir / "cases"


settings = Settings()


@dataclass(frozen=True)
class RunContext:
    """Per-run injected state. Threaded through the orchestrator to agents
    that need external resources (KG, LLM client, CaseStore, Embedder)."""

    kg: KnowledgeGraph
    llm: Any  # AsyncAnthropic — kept untyped at runtime to avoid importing
              # the Anthropic SDK in contexts that don't need it (tests
              # pass mock objects).
    case_store: CaseStore   # M3b — opened at lifespan
    embedder: Embedder      # M3b — cold-loaded at lifespan (~5-10s one-time)
