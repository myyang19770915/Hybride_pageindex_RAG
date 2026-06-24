import json
import logging
import queue
import threading
from collections.abc import Iterator

from app.core.config import get_settings
from app.core.security import Principal
from app.core.tracing import span
from app.schemas.documents import IngestionStatus
from app.schemas.query import (
    AgentAnswer,
    Citation,
    QueryMode,
    QueryRequest,
    QueryResponse,
    ReasoningEvent,
    TokenEvent,
    TraceEvent,
)
from app.services.documents import DocumentService
from app.services.retrieval import RetrievalService
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

# A single PostgresDb (and its SQLAlchemy engine) is reused across requests so the
# conversation-history store is not rebuilt on every query.
_conversation_db = None


# Dedicated session table so this app's conversations are isolated from other
# Agno apps that share the same database/schema.
CHAT_SESSION_TABLE = "hybride_chat_sessions"

# Per-node content snippet length handed to the agent in search_knowledge results.
# Enough to convey the section; full page text is fetched via SQL when needed.
_NODE_SNIPPET_CHARS = 600


def _get_conversation_db():
    global _conversation_db
    if _conversation_db is None:
        from agno.db.postgres import PostgresDb

        _conversation_db = PostgresDb(
            db_url=get_settings().database_url, session_table=CHAT_SESSION_TABLE
        )
    return _conversation_db

# Postgres toolkit methods that read document/page rows. A tool call to any of
# these maps to a "fetching page text" trace step in the UI.
_PG_TOOL_NAMES = frozenset(
    {"run_query", "summarize_table", "describe_table", "show_tables", "inspect_query"}
)

_SYSTEM_PROMPT = (
    "你是企業知識庫問答助理，採用 PageIndex 風格的代理式檢索。"
    "你的工作流程必須是：\n"
    "1. 先呼叫 `search_knowledge` 工具，對知識庫做混合檢索（向量 + BM25），"
    "取得最相關的章節節點。每個節點含 document_id、file_name、heading、snippet"
    "（章節原文摘錄）、start_page、end_page。\n"
    "2. 針對最相關的節點，使用 Postgres 工具的 `run_query` 取回該節點頁碼範圍的原文。"
    "資料表結構如下：\n"
    "   - km_document_pages(document_id TEXT, page_number INT, page_content TEXT)\n"
    "   - km_documents(document_id TEXT, file_name TEXT, version TEXT, total_pages INT)\n"
    "   你『必須』使用以下固定 SQL 語法（只替換三個值，不要改寫其他部分）：\n"
    "   SELECT page_number, page_content\n"
    "   FROM km_document_pages\n"
    "   WHERE document_id = '<document_id>'\n"
    "     AND page_number BETWEEN <start_page> AND <end_page>\n"
    "   ORDER BY page_number;\n"
    "3. 只根據取回的頁面原文回答，使用繁體中文，並在引用時標註頁碼，例如「（第 16 頁）」。\n"
    "可答性判斷與輸出格式（重要）：\n"
    "- 一般情況：直接輸出給使用者看的繁體中文答案，並標註頁碼。\n"
    "- 若問題太模糊、缺少關鍵條件、或無法確定答案：回覆的『第一行』必須是 "
    "「【需要澄清】」，接著寫出你需要使用者補充的具體問題，不要杜撰答案。\n"
    "- 若知識庫確實查不到相關資料：回覆的『第一行』必須是「【資料不足】」，"
    "接著說明目前查無相關資料。\n"
    "請直接輸出文字，不要輸出 JSON 或程式碼區塊。"
)

_CLARIFY_MARK = "【需要澄清】"
_INSUFFICIENT_MARK = "【資料不足】"


class AgentQueryService:
    """Agno-agent-driven query path.

    The agent performs hybrid retrieval via a knowledge tool (wrapping the existing
    Qdrant hybrid search), reads page text through Agno's PostgresTools, then judges
    answerability — answering with page citations or asking the user to clarify.

    Falls back to the deterministic :class:`RetrievalService` when the agent is
    disabled (``USE_AGNO=false``) or fails, so the endpoint always responds and the
    hermetic unit suite (which pins ``USE_AGNO=false``) is unaffected.
    """

    def __init__(
        self,
        document_service: DocumentService | None = None,
        fallback: RetrievalService | None = None,
    ) -> None:
        self.document_service = document_service or DocumentService()
        self.fallback = fallback or RetrievalService(document_service=self.document_service)

    def answer(self, request: QueryRequest, principal: Principal | None = None) -> QueryResponse:
        last: QueryResponse | None = None
        for event in self.answer_events(request, principal):
            if isinstance(event, QueryResponse):
                last = event
        if last is None:  # pragma: no cover - answer_events always yields a response
            raise RuntimeError("Query produced no response.")
        return last

    def answer_events(
        self, request: QueryRequest, principal: Principal | None = None
    ) -> Iterator[TraceEvent | TokenEvent | ReasoningEvent | QueryResponse]:
        if not get_settings().use_agno:
            yield from self.fallback.answer_events(request, principal)
            return

        with span(
            "agent.query",
            {"query": request.query, "top_k": request.top_k},
        ) as agent_span:
            try:
                for event in self._agent_events(request, principal):
                    if isinstance(event, TraceEvent) and agent_span is not None:
                        agent_span.add_event(event.stage, {"message": event.message})
                    yield event
            except Exception as exc:
                logger.exception("Agno agent query failed; falling back to deterministic pipeline")
                yield TraceEvent(
                    stage="router",
                    message=f"Agent 發生錯誤，改用決定式檢索：{exc}",
                )
                yield from self.fallback.answer_events(request, principal)

    # -- agent path ---------------------------------------------------------

    def _agent_events(
        self, request: QueryRequest, principal: Principal | None
    ) -> Iterator[TraceEvent | TokenEvent | ReasoningEvent | QueryResponse]:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike
        from agno.tools.postgres import PostgresTools

        settings = get_settings()
        trace: list[TraceEvent] = []
        collected_hits: list[dict] = []

        def emit(event: TraceEvent) -> TraceEvent:
            trace.append(event)
            return event

        def search_knowledge(query: str, top_k: int = 5) -> str:
            """對企業知識庫做混合檢索（向量 + BM25），回傳最相關的章節節點。

            Args:
                query: 使用者問題或檢索關鍵詞（繁體中文即可）。
                top_k: 要取回的節點數量，預設 5。

            Returns:
                JSON 陣列字串；每筆含 document_id、file_name、heading、snippet
                （章節原文摘錄）、start_page、end_page、score。
            """
            accessible = {
                document.document_id
                for document in self.document_service.list_documents(principal)
                if document.status == IngestionStatus.completed
            }
            hits = VectorStoreService().search_nodes(
                query, top_k, settings.retrieval_strategy
            )
            filtered = [hit for hit in hits if hit["document_id"] in accessible]
            collected_hits.extend(filtered)
            # Feed the agent a real content snippet (what was embedded), not the
            # extractive summary which can be figure-OCR noise. Bounded to keep the
            # tool result small; the agent fetches full page text via SQL when needed.
            projected = [
                {
                    "document_id": hit["document_id"],
                    "file_name": hit.get("file_name"),
                    "heading": hit.get("heading"),
                    "snippet": (hit.get("content") or hit.get("summary") or "")[
                        :_NODE_SNIPPET_CHARS
                    ],
                    "start_page": hit.get("start_page"),
                    "end_page": hit.get("end_page"),
                    "score": hit.get("score"),
                }
                for hit in filtered
            ]
            return json.dumps(projected, ensure_ascii=False)

        model = OpenAILike(
            id=settings.model_id,
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key,
            temperature=0,
            max_tokens=settings.agent_max_tokens,
        )
        postgres_tools = PostgresTools(
            host=settings.db_host,
            port=settings.db_port,
            db_name=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            table_schema="public",
        )
        # No output_schema: LM Studio rejects structured-output + tools in one
        # request, and the qwen reasoning model strands JSON in reasoning_content
        # so a parser phase comes back empty. We run free-form and derive the
        # answer status from leading markers (see _text_to_answer).
        agent = Agent(
            model=model,
            tools=[search_knowledge, postgres_tools],
            instructions=[_SYSTEM_PROMPT],
            # Conversation memory: Agno injects the last N turns of this session.
            db=_get_conversation_db(),
            add_history_to_context=True,
            num_history_runs=settings.agent_num_history_runs,
            markdown=False,
            telemetry=False,
        )

        yield emit(
            TraceEvent(stage="router", message="啟動 Agno Agent（混合檢索 + 資料庫取頁原文）")
        )

        # Run the whole agent stream inside ONE worker thread, bridging events to
        # this generator through a queue. FastAPI consumes the SSE generator across
        # threadpool threads; iterating agent.run() directly there breaks Agno /
        # OpenInference contextvar (OTel) attach-detach with a "Token created in a
        # different Context" error. Keeping the run in a single thread fixes that.
        events: queue.Queue = queue.Queue()
        done = object()
        state: dict = {"final": None, "error": None}
        worker = threading.Thread(
            target=self._drain_agent_run,
            args=(agent, request, principal, events, done, state),
            name="agent-run",
            daemon=True,
        )
        worker.start()
        while True:
            item = events.get()
            if item is done:
                break
            channel, payload = item
            if channel == "token":
                yield TokenEvent(delta=payload)
            elif channel == "reasoning":
                yield ReasoningEvent(delta=payload)
            else:
                yield emit(payload)
        worker.join()

        if state["error"] is not None:
            raise state["error"]
        final: AgentAnswer | None = state["final"]

        if final is None:
            yield emit(
                TraceEvent(
                    stage="router",
                    message="Agent 未產生結構化結果，改用決定式檢索。",
                )
            )
            yield from self.fallback.answer_events(request, principal)
            return

        yield emit(
            TraceEvent(stage="synthesis", message=f"Agent 生成回答（status={final.status}）。")
        )
        yield self._to_response(final, collected_hits, trace)

    def _drain_agent_run(
        self,
        agent: object,
        request: QueryRequest,
        principal: Principal | None,
        events: queue.Queue,
        done: object,
        state: dict,
    ) -> None:
        """Run the agent to completion in one thread, pushing events to a queue.

        Stays on a single thread so Agno/OpenInference OTel context tokens attach
        and detach in the same context. Stores the parsed answer / any error in
        ``state`` and signals completion with ``done``.
        """
        answer_text = ""
        final_local: AgentAnswer | None = None
        try:
            for event in agent.run(
                request.query,
                stream=True,
                stream_events=True,
                session_id=request.session_id,
                user_id=principal.username if principal else None,
            ):
                kind = getattr(event, "event", None)
                if kind == "RunContent":
                    reasoning = getattr(event, "reasoning_content", None)
                    if isinstance(reasoning, str) and reasoning:
                        events.put(("reasoning", reasoning))
                    delta = getattr(event, "content", None)
                    if isinstance(delta, str) and delta:
                        answer_text += delta
                        events.put(("token", delta))
                    continue
                mapped = self._map_event(event)
                if mapped is not None:
                    events.put(("trace", mapped))
                if kind == "RunCompleted":
                    content = getattr(event, "content", None)
                    final_local = self._text_to_answer(
                        content if isinstance(content, str) and content.strip() else answer_text
                    )
        except Exception as exc:  # surfaced to the generator to trigger fallback
            state["error"] = exc
        finally:
            if final_local is None and answer_text.strip():
                final_local = self._text_to_answer(answer_text)
            state["final"] = final_local
            events.put(done)

    # -- helpers ------------------------------------------------------------

    def _map_event(self, event: object) -> TraceEvent | None:
        kind = getattr(event, "event", None)
        tool = getattr(event, "tool", None)
        tool_name = getattr(tool, "tool_name", None) if tool is not None else None

        if kind == "ToolCallStarted":
            if tool_name == "search_knowledge":
                return TraceEvent(
                    stage="qdrant_hybrid",
                    message="Agent 正在進行混合檢索（向量 + BM25）…",
                )
            if tool_name in _PG_TOOL_NAMES:
                return TraceEvent(stage="page_fetch", message="正在從資料庫取回頁面原文…")
            if tool_name:
                return TraceEvent(stage="navigation", message=f"呼叫工具 {tool_name}…")
            return None

        if kind == "ToolCallCompleted" and tool_name == "search_knowledge":
            hits = self._parse_hits(getattr(tool, "result", None))
            if not hits:
                return TraceEvent(stage="vector_node", message="混合檢索未找到相關節點。")
            best = hits[0]
            return TraceEvent(
                stage="vector_node",
                message=(
                    f"混合檢索命中 {len(hits)} 個節點，"
                    f"最相關：{best.get('heading') or best.get('node_id')}"
                ),
                document_id=best.get("document_id"),
                document_name=best.get("file_name"),
                start_page=best.get("start_page"),
                end_page=best.get("end_page"),
            )
        return None

    @staticmethod
    def _parse_hits(result: object) -> list[dict]:
        if isinstance(result, list):
            return [hit for hit in result if isinstance(hit, dict)]
        if isinstance(result, str) and result.strip():
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [hit for hit in parsed if isinstance(hit, dict)]
        return []

    @staticmethod
    def _text_to_answer(content: object) -> AgentAnswer | None:
        """Derive a structured answer from the agent's free-form final text.

        Leading markers let the model signal answerability without structured
        output (which this reasoning model + LM Studio can't reliably produce).
        """
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            return None
        if text.startswith(_CLARIFY_MARK):
            question = text[len(_CLARIFY_MARK):].strip()
            return AgentAnswer(
                status="need_clarification", answer="", clarifying_question=question or text
            )
        if text.startswith(_INSUFFICIENT_MARK):
            return AgentAnswer(
                status="insufficient", answer=text[len(_INSUFFICIENT_MARK):].strip() or text
            )
        return AgentAnswer(status="answered", answer=text)

    def _to_response(
        self, answer: AgentAnswer, collected_hits: list[dict], trace: list[TraceEvent]
    ) -> QueryResponse:
        names = {
            hit["document_id"]: hit.get("file_name")
            for hit in collected_hits
            if hit.get("document_id")
        }
        citations = [
            Citation(
                document_id=citation.document_id,
                file_name=citation.file_name or names.get(citation.document_id) or "",
                start_page=citation.start_page,
                end_page=citation.end_page,
            )
            for citation in answer.citations
        ]
        # Backstop: an answered response with no explicit citations still points at
        # the top retrieved node so the UI can open the evidence.
        if not citations and answer.status == "answered" and collected_hits:
            best = collected_hits[0]
            start = best.get("start_page")
            end = best.get("end_page") or start
            if start is not None:
                citations.append(
                    Citation(
                        document_id=best["document_id"],
                        file_name=best.get("file_name") or "",
                        start_page=start,
                        end_page=end,
                    )
                )
        return QueryResponse(
            answer=answer.answer,
            mode=QueryMode.hybrid_agentic,
            status=answer.status,
            clarifying_question=answer.clarifying_question,
            citations=citations,
            trace=trace,
        )
