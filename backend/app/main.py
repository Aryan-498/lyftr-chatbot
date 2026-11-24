import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from . import db, llm

logging.basicConfig(level=logging.INFO)
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    llm.setup_cache()
    yield


app = FastAPI(title="LLM Chatbot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(_, __):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] = None


@app.get("/health")
def health():
    ok = db.ping()
    n = len(llm.keys())
    body = {"status": "ok" if ok and n else "degraded", "keys_configured": n, "cache_enabled": llm.cache_enabled()}
    return JSONResponse(status_code=200 if ok and n else 503, content=body)


@app.post("/chat")
async def chat(req: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    start = time.perf_counter()
    simulate = {}
    if os.getenv("ENABLE_FAILURE_SIMULATION", "").lower() == "true":
        simulate = llm.parse_simulation(x_simulate_failure)

    history = db.get_history(req.session_id)
    system_prompt = req.system_prompt or db.get_system_prompt(req.session_id) or DEFAULT_SYSTEM_PROMPT
    messages = (
        [{"role": "system", "content": system_prompt}]
        + [{"role": h["role"], "content": h["content"]} for h in history]
        + [{"role": "user", "content": req.message}]
    )

    try:
        result = await llm.generate(messages, simulate)
    except llm.AllProvidersFailed:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    reply = result.pop("reply")
    metadata = {**result, "latency_ms": int((time.perf_counter() - start) * 1000)}
    db.save_turn(req.session_id, req.message, reply, metadata, req.system_prompt)
    return {"session_id": req.session_id, "reply": reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    history = db.get_history(session_id)
    if not history:
        return JSONResponse(status_code=404, content={"detail": "session not found"})
    msgs = []
    for h in history:
        m = {"role": h["role"], "content": h["content"]}
        if h["role"] == "assistant" and h["metadata"]:
            m["metadata"] = h["metadata"]
        msgs.append(m)
    return {"session_id": session_id, "messages": msgs}
