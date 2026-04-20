"""Minimal settings object; expands in M1+ (model IDs, data paths, etc.)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    max_history_per_run: int = int(os.getenv("JURIST_MAX_HISTORY_PER_RUN", "500"))
    cors_allow_origin: str = os.getenv("JURIST_CORS_ORIGIN", "http://localhost:5173")
    data_dir: Path = Path(os.getenv("JURIST_DATA_DIR", "./data"))

    @property
    def kg_path(self) -> Path:
        return self.data_dir / "kg" / "huurrecht.json"


settings = Settings()
