"""Settings object + per-run context. Expands as milestones land."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from jurist.kg.interface import KnowledgeGraph

load_dotenv()


@dataclass(frozen=True)
class Settings:
    max_history_per_run: int = int(os.getenv("JURIST_MAX_HISTORY_PER_RUN", "500"))
    cors_allow_origin: str = os.getenv("JURIST_CORS_ORIGIN", "http://localhost:5173")
    data_dir: Path = Path(os.getenv("JURIST_DATA_DIR", "./data"))

    # M2 — statute retriever
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    model_retriever: str = os.getenv("JURIST_MODEL_RETRIEVER", "claude-sonnet-4-6")
    max_retriever_iters: int = int(os.getenv("JURIST_MAX_RETRIEVER_ITERS", "15"))
    retriever_wall_clock_cap_s: float = float(
        os.getenv("JURIST_RETRIEVER_WALL_CLOCK_CAP_S", "90")
    )
    statute_catalog_snippet_chars: int = int(
        os.getenv("JURIST_STATUTE_CATALOG_SNIPPET_CHARS", "200")
    )

    @property
    def kg_path(self) -> Path:
        return self.data_dir / "kg" / "huurrecht.json"


settings = Settings()


@dataclass(frozen=True)
class RunContext:
    """Per-run injected state. Threaded through the orchestrator to agents
    that need external resources (KG, LLM client, later: vector store)."""

    kg: KnowledgeGraph
    llm: Any  # AsyncAnthropic — kept untyped at runtime to avoid importing
              # the Anthropic SDK in contexts that don't need it (tests
              # pass mock objects).
