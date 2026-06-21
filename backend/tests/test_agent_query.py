from types import SimpleNamespace

from app.schemas.query import (
    AgentAnswer,
    AgentCitation,
    QueryRequest,
    QueryResponse,
    TraceEvent,
)
from app.services.agent_query import AgentQueryService


def _event(kind: str, tool_name: str | None = None, result: object = None) -> SimpleNamespace:
    tool = SimpleNamespace(tool_name=tool_name, result=result) if tool_name else None
    return SimpleNamespace(event=kind, tool=tool, content=None)


def test_falls_back_to_retrieval_when_agno_disabled() -> None:
    # conftest pins USE_AGNO=false, so the agent path must delegate to the
    # deterministic RetrievalService and still satisfy the query contract.
    response = AgentQueryService().answer(
        QueryRequest(query="ERR_01 怎麼處理？", top_k=5)
    )
    assert isinstance(response, QueryResponse)
    assert response.mode == "hybrid_agentic"
    assert response.answer
    assert response.trace


def test_text_to_answer_markers() -> None:
    svc = AgentQueryService
    plain = svc._text_to_answer("這是答案（第 2 頁）")
    assert plain.status == "answered" and plain.answer == "這是答案（第 2 頁）"

    clarify = svc._text_to_answer("【需要澄清】請問是哪一台機台？")
    assert clarify.status == "need_clarification"
    assert clarify.clarifying_question == "請問是哪一台機台？"

    insufficient = svc._text_to_answer("【資料不足】知識庫查無相關資料。")
    assert insufficient.status == "insufficient"
    assert "查無相關資料" in insufficient.answer

    assert svc._text_to_answer("") is None
    assert svc._text_to_answer(None) is None


def test_to_response_maps_citations_and_fills_file_name() -> None:
    answer = AgentAnswer(
        status="answered",
        answer="見第 2 頁。",
        citations=[AgentCitation(document_id="doc1", start_page=2, end_page=3)],
    )
    hits = [{"document_id": "doc1", "file_name": "A.pdf", "start_page": 2, "end_page": 3}]
    response = AgentQueryService()._to_response(answer, hits, [])
    assert response.status == "answered"
    assert len(response.citations) == 1
    # file_name backfilled from the retrieved hit when the agent omitted it.
    assert response.citations[0].file_name == "A.pdf"


def test_to_response_backstops_citation_from_top_hit() -> None:
    answer = AgentAnswer(status="answered", answer="有答案但沒附引用")
    hits = [{"document_id": "doc1", "file_name": "A.pdf", "start_page": 5, "end_page": 6}]
    response = AgentQueryService()._to_response(answer, hits, [])
    assert len(response.citations) == 1
    assert response.citations[0].start_page == 5


def test_to_response_clarification_has_no_backstop_citation() -> None:
    answer = AgentAnswer(
        status="need_clarification",
        answer="",
        clarifying_question="請問是哪一台機台？",
    )
    hits = [{"document_id": "doc1", "file_name": "A.pdf", "start_page": 1, "end_page": 1}]
    response = AgentQueryService()._to_response(answer, hits, [])
    assert response.status == "need_clarification"
    assert response.clarifying_question == "請問是哪一台機台？"
    assert response.citations == []


def test_map_event_tool_stages() -> None:
    svc = AgentQueryService()
    started_search = svc._map_event(_event("ToolCallStarted", "search_knowledge"))
    assert isinstance(started_search, TraceEvent)
    assert started_search.stage == "qdrant_hybrid"

    started_sql = svc._map_event(_event("ToolCallStarted", "run_query"))
    assert started_sql.stage == "page_fetch"

    result = (
        '[{"document_id":"doc1","file_name":"A.pdf",'
        '"heading":"真空","start_page":2,"end_page":2}]'
    )
    completed = svc._map_event(_event("ToolCallCompleted", "search_knowledge", result))
    assert completed.stage == "vector_node"
    assert completed.document_id == "doc1"
    assert completed.start_page == 2

    # Unrelated events produce no trace step.
    assert svc._map_event(_event("RunContent")) is None
