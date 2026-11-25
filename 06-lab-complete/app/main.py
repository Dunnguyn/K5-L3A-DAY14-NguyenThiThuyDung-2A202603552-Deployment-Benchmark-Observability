"""Production mock agent with shared Redis guardrails."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from redis.exceptions import RedisError

from utils.mock_llm import ask as llm_ask

from .auth import verify_api_key
from .config import settings
from .cost_guard import check_budget, record_cost
from .rate_limiter import check_rate_limit
from .redis_client import create_redis_client, redis_healthy


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        })


logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        client = create_redis_client()
    except ValueError:
        logger.error("redis_configuration_invalid")
        client = None
    app.state.redis = client
    app.state.ready = True
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    try:
        yield
    finally:
        app.state.ready = False
        if client is not None:
            client.close()
        logger.info("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request body"})


@app.middleware("http")
async def log_request(request: Request, call_next):
    start = perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    logger.info("request", extra={"fields": {
        "route": getattr(route, "path", None),
        "status": response.status_code,
        "duration_ms": round(1000 * (perf_counter() - start), 3),
    }})
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(request: Request):
    client = request.app.state.redis
    if not request.app.state.ready or client is None or not redis_healthy(client):
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, request: Request, api_key: str = Depends(verify_api_key)):
    # FastAPI runs synchronous endpoints in its worker thread pool.
    client = request.app.state.redis
    if client is None:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    try:
        check_rate_limit(client, api_key)
        reservation = check_budget(client, body.question)
        try:
            answer = llm_ask(body.question)
        except Exception:
            logger.error("mock_failed")
            record_cost(client, reservation, None)
            raise HTTPException(status_code=502, detail="Agent response unavailable") from None
        record_cost(client, reservation, answer)
    except RedisError:
        logger.error("redis_unavailable")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None
    return {"question": body.question, "answer": answer}
