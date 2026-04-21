"""LanceDB CRUD for CaseChunkRow storage.

Concrete class — no interface — per parent spec §15 decision #12.
Used by the M3a ingester (add_rows) and the M3b case retriever (query).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from jurist.schemas import CaseChunkRow

log = logging.getLogger(__name__)

_TABLE_NAME = "cases"

_SCHEMA = pa.schema([
    ("ecli", pa.string()),
    ("chunk_idx", pa.int32()),
    ("court", pa.string()),
    ("date", pa.string()),
    ("zaaknummer", pa.string()),
    ("subject_uri", pa.string()),
    ("modified", pa.string()),
    ("text", pa.string()),
    ("embedding", pa.list_(pa.float32(), 1024)),
    ("url", pa.string()),
])


class CaseStore:
    def __init__(self, lance_path: Path) -> None:
        self.lance_path = Path(lance_path)
        self._db: lancedb.DBConnection | None = None
        self._table: lancedb.table.Table | None = None

    def open_or_create(self) -> None:
        self.lance_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.lance_path))
        if _TABLE_NAME in self._db.list_tables():
            self._table = self._db.open_table(_TABLE_NAME)
        else:
            self._table = self._db.create_table(_TABLE_NAME, schema=_SCHEMA)

    def contains_ecli(self, ecli: str) -> bool:
        self._require_open()
        safe = ecli.replace("'", "''")
        df = self._table.search().where(f"ecli = '{safe}'").limit(1).to_pandas()
        return len(df) > 0

    def all_eclis(self) -> set[str]:
        self._require_open()
        df = self._table.to_pandas()
        return set(df["ecli"].tolist()) if len(df) > 0 else set()

    def row_count(self) -> int:
        self._require_open()
        return self._table.count_rows()

    def add_rows(self, rows: list[CaseChunkRow]) -> None:
        """Batch-append. Skip rows whose (ecli, chunk_idx) already exist."""
        self._require_open()
        if not rows:
            return
        existing = self._existing_keys({r.ecli for r in rows})
        fresh = [r for r in rows if (r.ecli, r.chunk_idx) not in existing]
        if not fresh:
            return
        records = [r.model_dump() for r in fresh]
        self._table.add(records)

    def query(
        self,
        vector: np.ndarray,
        *,
        top_k: int = 20,
    ) -> list[CaseChunkRow]:
        self._require_open()
        vec = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
        df = self._table.search(vec).metric("cosine").limit(top_k).to_pandas()
        out: list[CaseChunkRow] = []
        for rec in df.to_dict(orient="records"):
            rec.pop("_distance", None)
            out.append(CaseChunkRow.model_validate(rec))
        return out

    def drop(self) -> None:
        if self.lance_path.exists():
            shutil.rmtree(self.lance_path)
        self._db = None
        self._table = None

    def _require_open(self) -> None:
        if self._table is None:
            raise RuntimeError("CaseStore.open_or_create() must be called first")

    def _existing_keys(self, eclis: set[str]) -> set[tuple[str, int]]:
        if not eclis:
            return set()
        quoted = ", ".join(f"'{e}'" for e in eclis)
        df = (
            self._table.search()
            .where(f"ecli IN ({quoted})")
            .select(["ecli", "chunk_idx"])
            .limit(1_000_000)
            .to_pandas()
        )
        if len(df) == 0:
            return set()
        return {(row["ecli"], row["chunk_idx"]) for _, row in df.iterrows()}
