from fastapi import APIRouter

from app.api.routes import auth, chat, documents, eval, health, mineru, query

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(query.router, prefix="/query", tags=["query"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(mineru.router, prefix="/mineru", tags=["mineru"])
api_router.include_router(eval.router, prefix="/eval", tags=["eval"])
