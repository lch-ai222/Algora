"""FastAPI entrypoint for the CodeAgent Eval console.

Read-only view over the artifacts the runner produces. Run:
    PYTHONPATH=src uvicorn backend.app.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the codeagent_eval package importable without installing.
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend.app.routers import experiments  # noqa: E402

# Vite dev server origins (frontend). Single-user local dev.
ALLOWED_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 5174, 5175, 5176)
]


def create_app() -> FastAPI:
    app = FastAPI(title="CodeAgent Eval Console", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(experiments.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
