from collections.abc import Iterator

from app.core.config import get_settings
from app.core.security import Principal
from app.core.tracing import span
from app.schemas.documents import DocumentDetail, DocumentPage, IngestionStatus, TocNode
from app.schemas.query import (
    Citation,
    QueryMode,
    QueryRequest,
    QueryResponse,
    RetrievalStrategy,
    TraceEvent,
)
from app.services.documents import DocumentService
from app.services.ranking import BM25Index, tokenize
from app.services.synthesis import AnswerSynthesisService
from app.services.vector_store import VectorStoreService

_MAX_RERANKED_PAGES = 5


class RetrievalService:
    def __init__(
        self,
        document_service: DocumentService | None = None,
        synthesis_service: AnswerSynthesisService | None = None,
    ) -> None:
        self.document_service = document_service or DocumentService()
        self.synthesis_service = synthesis_service or AnswerSynthesisService()

    def answer(self, request: QueryRequest, principal: Principal | None = None) -> QueryResponse:
        events = list(self.answer_events(request, principal))
        return events[-1]

    def answer_events(
        self, request: QueryRequest, principal: Principal | None = None
    ) -> Iterator[TraceEvent | QueryResponse]:
        with span(
            "retrieval.pipeline",
            {"query": request.query, "mode": request.mode, "top_k": request.top_k},
        ) as pipeline_span:
            for event in self._pipeline_events(request, principal):
                if isinstance(event, TraceEvent) and pipeline_span is not None:
                    pipeline_span.add_event(event.stage, {"message": event.message})
                yield event

    def _pipeline_events(
        self, request: QueryRequest, principal: Principal | None = None
    ) -> Iterator[TraceEvent | QueryResponse]:
        mode = QueryMode.hybrid_agentic if request.mode == QueryMode.auto else request.mode
        trace = [TraceEvent(stage="router", message=f"Selected retrieval mode: {mode}")]
        yield trace[-1]

        candidate_ids = self._candidate_document_ids(request, trace, principal)
        yield from trace[1:]

        if not candidate_ids:
            yield QueryResponse(
                answer="目前沒有已完成 ingestion 的文件可供檢索。",
                mode=mode,
                trace=trace,
            )
            return

        document = self._select_document(request.query, candidate_ids, trace)
        yield trace[-1]
        pages = self.document_service.list_pages(document.document_id)
        node = self._select_toc_node(request.query, document, pages)
        selected_pages = self._select_pages(node, pages)
        vector_pages = self._vector_node_pages(request, document, pages, trace)
        if vector_pages is not None:
            selected_pages = vector_pages
            yield trace[-1]
        ranked_pages = self._rerank_pages(request, selected_pages, trace)
        if ranked_pages is not None:
            yield trace[-1]

        if node:
            trace.append(
                TraceEvent(
                    stage="navigation",
                    message=f"Selected TOC node {node.node_id}: {node.heading}",
                    document_id=document.document_id,
                    document_name=document.file_name,
                    start_page=node.start_page,
                    end_page=node.end_page,
                )
            )
            yield trace[-1]
        trace.append(
            TraceEvent(
                stage="page_fetch",
                message=f"Fetched {len(selected_pages)} page(s) from {document.file_name}.",
                document_id=document.document_id,
                document_name=document.file_name,
                start_page=selected_pages[0].page_number if selected_pages else None,
                end_page=selected_pages[-1].page_number if selected_pages else None,
            )
        )
        yield trace[-1]

        synthesis_pages = ranked_pages if ranked_pages is not None else selected_pages
        synthesis = self.synthesis_service.synthesize(request.query, document, synthesis_pages)
        trace.append(
            TraceEvent(
                stage="synthesis",
                message=f"Generated answer via {synthesis.method} synthesis.",
                document_id=document.document_id,
                document_name=document.file_name,
            )
        )
        yield trace[-1]
        answer = synthesis.answer
        citations = []
        if selected_pages:
            page_numbers = [page.page_number for page in selected_pages]
            citations.append(
                Citation(
                    document_id=document.document_id,
                    file_name=document.file_name,
                    start_page=min(page_numbers),
                    end_page=max(page_numbers),
                )
            )

        yield QueryResponse(answer=answer, mode=mode, citations=citations, trace=trace)

    def _resolve_strategy(self, request: QueryRequest) -> RetrievalStrategy:
        if request.strategy is not None:
            return request.strategy
        try:
            return RetrievalStrategy(get_settings().retrieval_strategy)
        except ValueError:
            return RetrievalStrategy.hybrid

    def _document_corpus(self, document_ids: list[str]) -> dict[str, str]:
        corpus: dict[str, str] = {}
        for document_id in document_ids:
            document = self.document_service.get_document(document_id)
            pages = self.document_service.list_pages(document_id)
            corpus[document_id] = " ".join(
                [
                    document.file_name,
                    *[f"{node.heading} {node.summary}" for node in document.toc],
                    *[page.page_content for page in pages],
                ]
            )
        return corpus

    def _candidate_document_ids(
        self,
        request: QueryRequest,
        trace: list[TraceEvent],
        principal: Principal | None = None,
    ) -> list[str]:
        settings = get_settings()
        strategy = self._resolve_strategy(request)
        completed = [
            document
            for document in self.document_service.list_documents(principal)
            if document.status == IngestionStatus.completed
        ]
        accessible_ids = {document.document_id for document in completed}

        # Preferred path: Qdrant native hybrid (dense + BM25 sparse, server-side RRF).
        if settings.use_qdrant:
            try:
                ids = [
                    document_id
                    for document_id in VectorStoreService().search(
                        request.query, request.top_k, strategy.value
                    )
                    if document_id in accessible_ids
                ]
                trace.append(
                    TraceEvent(
                        stage="qdrant_hybrid",
                        message=f"Qdrant {strategy.value} search returned {len(ids)} document(s).",
                    )
                )
                if ids:
                    return ids
            except Exception as exc:
                trace.append(
                    TraceEvent(stage="qdrant_hybrid", message=f"Qdrant search failed: {exc}")
                )

        # Fallback (no Qdrant): in-process BM25 over the candidate corpus.
        corpus = self._document_corpus([document.document_id for document in completed])
        index = BM25Index(k1=settings.bm25_k1, b=settings.bm25_b).fit(corpus)
        fused = index.rank(request.query)[: request.top_k]
        trace.append(
            TraceEvent(
                stage="sparse_search",
                message=f"Local BM25 ranked {len(fused)} candidate(s).",
            )
        )
        if not fused:
            fused = [document.document_id for document in completed]
            trace.append(
                TraceEvent(
                    stage="coarse_search",
                    message=f"Fell back to {len(fused)} completed document(s).",
                )
            )
        return fused[: request.top_k]

    def _select_document(
        self, query: str, candidate_ids: list[str], trace: list[TraceEvent]
    ) -> DocumentDetail:
        query_tokens = self._tokens(query)
        best_document: DocumentDetail | None = None
        best_score = -1
        for document_id in candidate_ids:
            document = self.document_service.get_document(document_id)
            pages = self.document_service.list_pages(document.document_id)
            text = " ".join(
                [
                    document.file_name,
                    *[node.heading + " " + node.summary for node in document.toc],
                    *[page.page_content for page in pages],
                ]
            )
            score = self._overlap_score(query_tokens, text)
            if score > best_score:
                best_score = score
                best_document = document

        if best_document is None:
            raise RuntimeError("No candidate document could be loaded.")

        trace.append(
            TraceEvent(
                stage="document_select",
                message=f"Selected {best_document.file_name} with score {best_score}.",
                document_id=best_document.document_id,
                document_name=best_document.file_name,
            )
        )
        return best_document

    def _select_toc_node(
        self, query: str, document: DocumentDetail, pages: list[DocumentPage]
    ) -> TocNode | None:
        if not document.toc:
            return None
        query_tokens = self._tokens(query)
        page_text_by_number = {page.page_number: page.page_content for page in pages}
        return max(
            document.toc,
            key=lambda node: self._overlap_score(
                query_tokens,
                " ".join(
                    [
                        node.heading,
                        node.summary,
                        *[
                            page_text_by_number.get(page_number, "")
                            for page_number in range(node.start_page, node.end_page + 1)
                        ],
                    ]
                ),
            ),
        )

    def _vector_node_pages(
        self,
        request: QueryRequest,
        document: DocumentDetail,
        pages: list[DocumentPage],
        trace: list[TraceEvent],
    ) -> list[DocumentPage] | None:
        """Pick the best TOC node for this document via node-summary vector search.

        Returns the pages within that node's precise range, or ``None`` when Qdrant
        is disabled or yields no node hit for this document (then TOC selection stands).
        """
        if not get_settings().use_qdrant:
            return None
        try:
            hits = VectorStoreService().search_nodes(
                request.query, max(request.top_k * 3, 10), self._resolve_strategy(request).value
            )
        except Exception as exc:
            trace.append(
                TraceEvent(stage="vector_node", message=f"Node vector search failed: {exc}")
            )
            return None

        doc_hits = [
            hit
            for hit in hits
            if hit["document_id"] == document.document_id and hit.get("start_page") is not None
        ]
        if not doc_hits:
            return None
        best = doc_hits[0]  # query_points returns hits sorted by score, best first
        start = best["start_page"]
        end = best.get("end_page") or start
        by_number = {page.page_number: page for page in pages}
        selected = [by_number[number] for number in range(start, end + 1) if number in by_number]
        if not selected:
            return None
        trace.append(
            TraceEvent(
                stage="vector_node",
                message=f"Matched TOC node {best.get('node_id')}: {best.get('heading')}",
                document_id=document.document_id,
                document_name=document.file_name,
                start_page=start,
                end_page=end,
            )
        )
        return selected

    def _rerank_pages(
        self,
        request: QueryRequest,
        pages: list[DocumentPage],
        trace: list[TraceEvent],
    ) -> list[DocumentPage] | None:
        """BM25-rerank the candidate pages by relevance to the query.

        Returns the reordered (and capped) page list, or ``None`` when reranking
        is disabled or there is nothing to reorder.
        """
        if not get_settings().retrieval_rerank or len(pages) < 2:
            return None
        index = BM25Index(
            k1=get_settings().bm25_k1, b=get_settings().bm25_b
        ).fit({str(page.page_number): page.page_content for page in pages})
        by_number = {page.page_number: page for page in pages}
        ranked_numbers = index.rank(request.query)
        reranked = [by_number[int(number)] for number in ranked_numbers]
        # Pages with no lexical signal keep their original order at the tail.
        for page in pages:
            if page not in reranked:
                reranked.append(page)
        reranked = reranked[:_MAX_RERANKED_PAGES]
        trace.append(
            TraceEvent(
                stage="rerank",
                message=(
                    f"Reranked {len(pages)} page(s) with BM25; "
                    f"kept top {len(reranked)} for synthesis."
                ),
            )
        )
        return reranked

    def _select_pages(self, node: TocNode | None, pages: list[DocumentPage]) -> list[DocumentPage]:
        if not pages:
            return []
        if node is None:
            return pages[:3]
        selected = [
            page for page in pages if node.start_page <= page.page_number <= node.end_page
        ]
        return selected or pages[:3]

    def _tokens(self, text: str) -> set[str]:
        return set(tokenize(text))

    def _overlap_score(self, query_tokens: set[str], text: str) -> int:
        if not query_tokens:
            return 0
        text_tokens = self._tokens(text)
        return len(query_tokens & text_tokens)
