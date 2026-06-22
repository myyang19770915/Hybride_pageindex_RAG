import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.agent_query import _get_conversation_db

logger = logging.getLogger(__name__)


class SessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: int | None = None


class ChatMessageOut(BaseModel):
    role: str
    content: str


router = APIRouter()


def _session_type():
    from agno.db.base import SessionType

    return SessionType.AGENT


def _messages(session) -> list[ChatMessageOut]:
    """User/assistant turns from an Agno session, dropping system/tool/empty rows."""
    out: list[ChatMessageOut] = []
    for message in session.get_messages():
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append(ChatMessageOut(role=role, content=content))
    return out


def _title(session) -> str:
    for message in session.get_messages():
        if getattr(message, "role", None) == "user":
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip().replace("\n", " ")[:40]
    return ""


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    """Past conversations for the sidebar, newest first."""
    db = _get_conversation_db()
    try:
        sessions = db.get_sessions(
            session_type=_session_type(),
            limit=100,
            sort_by="updated_at",
            sort_order="desc",
        )
    except Exception:
        # The session store can be transiently unreadable: during an Agno schema
        # migration the SQLAlchemy MetaData cache holds a pre-migration Table, so
        # reads raise AttributeError on the newly added column until the process
        # restarts. The sidebar loads on every page view, so degrade to "no
        # history" rather than 500. Agno already returns [] when the table is
        # absent; this aligns the read-failure path with that contract.
        logger.warning("Could not read chat sessions; returning empty list", exc_info=True)
        return []
    summaries: list[SessionSummary] = []
    for session in sessions:
        title = _title(session)
        if not title:  # skip empty sessions with no user turn yet
            continue
        summaries.append(
            SessionSummary(
                session_id=session.session_id,
                title=title,
                updated_at=getattr(session, "updated_at", None),
            )
        )
    return summaries


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_session_messages(session_id: str) -> list[ChatMessageOut]:
    db = _get_conversation_db()
    try:
        session = db.get_session(session_id=session_id, session_type=_session_type())
    except Exception:
        # Same transient-unreadable store as list_sessions (e.g. Agno schema
        # migration window). Surface a clean 503 instead of an unhandled 500.
        logger.warning("Could not read chat session %s", session_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation store temporarily unavailable.",
        ) from None
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return _messages(session)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    db = _get_conversation_db()
    db.delete_session(session_id)
    return {"deleted": session_id}
