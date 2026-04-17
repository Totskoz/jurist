import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from jurist.api.app import app


@pytest.mark.asyncio
async def test_post_ask_returns_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "question_id" in body
        assert body["question_id"].startswith("run_")


@pytest.mark.asyncio
async def test_stream_yields_run_started_through_run_finished():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        qid = resp.json()["question_id"]

        events: list[dict] = []
        async with client.stream("GET", f"/api/stream?question_id={qid}") as s:
            assert s.status_code == 200
            async for line in s.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[len("data: "):])
                events.append(payload)
                if payload["type"] in {"run_finished", "run_failed"}:
                    break

    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert "answer_delta" in types


@pytest.mark.asyncio
async def test_stream_returns_404_for_unknown_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stream?question_id=run_does_not_exist")
        assert resp.status_code == 404
