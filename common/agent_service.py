"""Application factory; clients are created and closed in FastAPI lifespan."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


def agent_app(name: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = LLMClient()
        try:
            yield
        finally:
            await app.state.llm.close()

    app = FastAPI(title=f"MAS {name}", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": name}

    return app


async def generate(app: FastAPI, prompt: str, payload: BaseModel, model: type[BaseModel]):
    try:
        return await app.state.llm.generate_structured(prompt, payload.model_dump_json(), model)
    except Exception as exc:
        logger.warning("Agent generation failed: %s", type(exc).__name__)
        raise HTTPException(502, "LLM generation failed; check provider configuration and response schema") from exc
