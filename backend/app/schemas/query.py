from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class QueryMode(StrEnum):
    auto = "auto"
    vector = "vector"
    hybrid_agentic = "hybrid_agentic"


AnswerStatus = Literal["answered", "need_clarification", "insufficient"]


class RetrievalStrategy(StrEnum):
    dense = "dense"
    bm25 = "bm25"
    hybrid = "hybrid"


class TraceEvent(BaseModel):
    stage: str
    message: str
    document_id: str | None = None
    document_name: str | None = None
    start_page: int | None = None
    end_page: int | None = None


class Citation(BaseModel):
    document_id: str
    file_name: str
    start_page: int
    end_page: int


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: QueryMode = QueryMode.auto
    top_k: int = Field(default=5, ge=1, le=20)
    strategy: RetrievalStrategy | None = None
    # Conversation id so the agent can recall prior turns via Agno's PostgresDb.
    session_id: str | None = None


class TokenEvent(BaseModel):
    """A streamed answer delta (token chunk) for live, ChatGPT-style output."""

    delta: str


class ReasoningEvent(BaseModel):
    """A streamed reasoning delta (the model's thinking) shown in 思考過程."""

    delta: str


class QueryResponse(BaseModel):
    answer: str
    mode: QueryMode
    status: AnswerStatus = "answered"
    clarifying_question: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)


class AgentCitation(BaseModel):
    """A page-range citation the agent attaches to its answer."""

    document_id: str
    file_name: str | None = None
    start_page: int
    end_page: int


class AgentAnswer(BaseModel):
    """Structured output the Agno agent must return.

    ``status`` lets the frontend distinguish a real answer from a request for more
    information, so the agent can ask the user to clarify instead of fabricating.
    """

    status: AnswerStatus = "answered"
    answer: str = ""
    clarifying_question: str | None = None
    citations: list[AgentCitation] = Field(default_factory=list)
