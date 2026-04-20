"""FastAPI app: POST /api/ask + GET /api/stream (SSE) + GET /api/kg."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from sse_starlette.sse import EventSourceResponse

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import RunContext, settings
from jurist.kg.interface import KnowledgeGraph
from jurist.kg.networkx_kg import NetworkXKG

# Ensure our jurist.* INFO logs surface when uvicorn's reload worker imports
# this module without running jurist.api.__main__.main(). basicConfig is a
# no-op if the root logger already has handlers, so the __main__ call still
# wins when the process is launched directly.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.kg = NetworkXKG.load_from_json(settings.kg_path)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"KG not found at {settings.kg_path}. "
            f"Run: uv run python -m jurist.ingest.statutes"
        ) from e
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(
            f"KG at {settings.kg_path} failed to load: {e}. "
            f"Re-run: uv run python -m jurist.ingest.statutes --refresh"
        ) from e
    logger.info(
        "Loaded KG: %d nodes, %d edges from %s",
        len(app.state.kg.all_nodes()),
        len(app.state.kg.all_edges()),
        settings.kg_path,
    )
    app.state.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    logger.info("Anthropic client ready (model: %s)", settings.model_retriever)
    yield


app = FastAPI(title="Jurist", version="0.1.0", lifespan=lifespan)

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


_runs: dict[str, EventBuffer] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    question_id = f"run_{uuid.uuid4().hex[:10]}"
    buf = EventBuffer(max_history=settings.max_history_per_run)
    _runs[question_id] = buf
    ctx = RunContext(kg=app.state.kg, llm=app.state.anthropic)
    task = asyncio.create_task(run_question(req.question, question_id, buf, ctx))
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
async def kg(request: Request) -> dict:
    g: KnowledgeGraph = request.app.state.kg
    return {
        "nodes": [n.model_dump() for n in g.all_nodes()],
        "edges": [e.model_dump() for e in g.all_edges()],
    }
