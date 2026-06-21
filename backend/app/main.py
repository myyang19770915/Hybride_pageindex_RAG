from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.tracing import configure_tracing


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Take over any orphaned MinerU sidecar so the next parse spawns a fresh one
    # with the current environment (avoids reusing a stale long-running sidecar).
    try:
        from app.services.mineru_api import MineruApiClient

        MineruApiClient().reset_managed()
    except Exception:  # never block startup on sidecar cleanup
        pass
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_tracing()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
