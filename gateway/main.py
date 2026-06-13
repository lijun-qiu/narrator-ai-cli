"""Narrator AI compatible gateway — zero-change proxy for narrator-ai-cli."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.config import settings
from gateway.response import err
from gateway.routers import files, tasks, ui, user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gateway")

app = FastAPI(title="Narrator AI Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user.router)
app.include_router(files.router)
app.include_router(tasks.router)
app.include_router(ui.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    app_key = request.headers.get("app-key", "")
    if request.url.path.startswith("/v2/") or request.url.path.startswith("/v1/users/balance"):
        logger.info("%s %s app-key=%s", request.method, request.url.path, app_key[:8] + "..." if app_key else "-")
    return await call_next(request)


@app.get("/health")
def health():
    from gateway.services.models import resolve_llm_model, resolve_tts_model

    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "models": {
            "flash": resolve_llm_model("flash"),
            "pro": resolve_llm_model("pro"),
            "tts": resolve_tts_model(),
            "tts_pro": resolve_tts_model("pro"),
        },
        "tts_provider": settings.tts_provider,
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content=err(50003, str(exc)))


def main():
    import uvicorn

    uvicorn.run("gateway.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
