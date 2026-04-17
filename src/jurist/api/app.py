"""FastAPI app: POST /api/ask + GET /api/stream (SSE)."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import settings
from jurist.fakes import FAKE_KG

app = FastAPI(title="Jurist", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question_id: str


# In-memory registry of active runs. One buffer per question_id.
_runs: dict[str, EventBuffer] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    question_id = f"run_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=settings.max_history_per_run)
    _runs[question_id] = buf
    task = asyncio.create_task(run_question(req.question, question_id, buf))
    _tasks[question_id] = task
    return AskResponse(question_id=question_id)


@app.get("/api/stream")
async def stream(question_id: str):
    buf = _runs.get(question_id)
    if buf is None:
        raise HTTPException(status_code=404, detail="unknown question_id")

    async def gen():
        async for ev in buf.subscribe():
            yield {"data": ev.model_dump_json()}

    return EventSourceResponse(gen())


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/kg")
async def kg() -> dict:
    nodes, edges = FAKE_KG
    return {
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }
