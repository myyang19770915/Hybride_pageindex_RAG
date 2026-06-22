"""Regression tests for the read-only chat endpoints.

Root cause covered: during an Agno schema migration the SQLAlchemy MetaData
cache holds a pre-migration Table, so reads against the session store raise
``AttributeError`` on the newly added column (observed in production as
``AttributeError: session_type`` from ``agno/db/postgres/postgres.py``). The
sidebar's session list must degrade to "no history" instead of returning 500.
"""

from app.api.routes import chat
from app.main import app
from fastapi.testclient import TestClient


class _FakeDb:
    """Stand-in conversation db whose reads raise like a stale-cache Agno db."""

    def __init__(self, error: Exception | None = None, sessions: list | None = None):
        self._error = error
        self._sessions = sessions or []

    def get_sessions(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return self._sessions

    def get_session(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return None


def test_list_sessions_degrades_on_unreadable_store(monkeypatch) -> None:
    # Reproduces the production failure: get_sessions raises AttributeError on
    # the missing/stale 'session_type' column.
    monkeypatch.setattr(
        chat,
        "_get_conversation_db",
        lambda: _FakeDb(error=AttributeError("session_type")),
    )

    response = TestClient(app).get("/api/chat/sessions")

    assert response.status_code == 200  # was 500 before the fix
    assert response.json() == []


def test_get_session_messages_returns_503_on_unreadable_store(monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "_get_conversation_db",
        lambda: _FakeDb(error=AttributeError("session_type")),
    )

    response = TestClient(app).get("/api/chat/sessions/whatever/messages")

    assert response.status_code == 503  # was an unhandled 500 before the fix
