"""GET + PUT /api/history — disk-persisted run archive."""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from jurist.config import settings

logger = logging.getLogger(__name__)

MAX_ENTRIES = 15
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


class HistoryEntry(BaseModel):
    id: str
    question: str
    timestamp: int
    status: Literal["finished", "failed"]
    # Opaque to the server — client is the source of truth for snapshot shape.
    snapshot: dict


class HistoryFile(BaseModel):
    version: Literal[1] = 1
    entries: list[HistoryEntry] = Field(default_factory=list)


router = APIRouter()


def _empty() -> dict:
    return {"version": 1, "entries": []}


def _read() -> dict:
    path = settings.history_path
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("history file unreadable, returning empty: %s", e)
        return _empty()
    if not isinstance(data, dict) or data.get("version") != 1:
        return _empty()
    return data


def _atomic_write(body: HistoryFile) -> None:
    """Write via tmp file + os.replace so a crash cannot leave partial JSON."""
    path = settings.history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(body.model_dump(), f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        # Clean up tmp on failure so next write starts fresh.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


@router.get("/history")
async def get_history() -> dict:
    return _read()


@router.put("/history")
async def put_history(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"payload exceeds {MAX_PAYLOAD_BYTES} bytes",
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {e}") from e

    try:
        body = HistoryFile.model_validate(parsed)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e

    if len(body.entries) > MAX_ENTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"entries count {len(body.entries)} exceeds cap of {MAX_ENTRIES}",
        )

    try:
        _atomic_write(body)
    except Exception as e:
        logger.exception("history write failed")
        raise HTTPException(status_code=500, detail=f"write failed: {e}") from e

    return {"ok": True}
