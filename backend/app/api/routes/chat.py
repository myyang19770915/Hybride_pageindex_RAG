from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.agent_query import _get_conversation_db


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
    sessions = db.get_sessions(
        session_type=_session_type(),
        limit=100,
        sort_by="updated_at",
        sort_order="desc",
    )
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
    session = db.get_session(session_id=session_id, session_type=_session_type())
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return _messages(session)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    db = _get_conversation_db()
    db.delete_session(session_id)
    return {"deleted": session_id}
