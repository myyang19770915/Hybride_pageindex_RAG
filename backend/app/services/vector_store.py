import hashlib
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import get_settings
from app.schemas.documents import DocumentDetail, DocumentPage, TocNode
from app.services.embeddings import EmbeddingService
from app.services.ranking import tokenize

_SUMMARY_TEXT_LIMIT = 1500
# Cap on the node text sent to the embedder (the model truncates by tokens anyway;
# this bounds payload size for multi-page nodes like a References section).
_NODE_EMBED_LIMIT = 6000
_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "bm25"


def _flatten_toc(nodes: list[TocNode]) -> list[TocNode]:
    flat: list[TocNode] = []
    for node in nodes:
        flat.append(node)
        if node.children:
            flat.extend(_flatten_toc(node.children))
    return flat


def _sparse_vector(text: str) -> SparseVector:
    """Build a term-frequency sparse vector; Qdrant applies IDF server-side.

    Uses the shared zh/en tokenizer (CJK split to characters) so Chinese queries
    match at the character level. Token ids are a stable 32-bit hash of the token.
    """
    counts = Counter(tokenize(text))
    indices: list[int] = []
    values: list[float] = []
    for token, freq in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        indices.append(int.from_bytes(digest, "big"))
        values.append(float(freq))
    return SparseVector(indices=indices, values=values)


class VectorStoreService:
    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.settings = get_settings()
        self.client = QdrantClient(url=self.settings.qdrant_url)
        self.embedding_service = embedding_service or EmbeddingService()
        self.collection = self.settings.qdrant_collection

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            try:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config={
                        _DENSE_VECTOR: VectorParams(
                            size=self.settings.qdrant_vector_size, distance=Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        # IDF modifier => Qdrant computes BM25-style IDF from collection stats.
                        _SPARSE_VECTOR: SparseVectorParams(modifier=Modifier.IDF)
                    },
                )
            except UnexpectedResponse as exc:
                # collection_exists() can misreport against a newer Qdrant server
                # (client/server version skew), so creation may race a collection
                # that already exists. A 409 Conflict means it's already there —
                # treat ensure_collection as idempotent and continue.
                if exc.status_code != 409:
                    raise
        index_fields = ("document_id", "file_name", "version", "content_hash", "status", "node_id")
        for field_name in index_fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

    def _node_point_id(self, document_id: str, node_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{document_id}:node:{node_id}"))

    def upsert_document(
        self, document: DocumentDetail, pages: list[DocumentPage] | None = None
    ) -> int:
        """Embed one point per TOC node with both a dense and a BM25 sparse vector.

        The embedded text is the node's heading + its full page content (capped),
        not the extractive summary. Summaries are lossy and sometimes capture a
        leading figure's OCR instead of the section body, which wrecks node recall
        for data/table queries. Embedding the real content aligns the vector with
        what users actually ask about. The payload ``summary`` stays for display.
        """
        self.ensure_collection()
        self.delete_document(document.document_id)

        page_text = {page.page_number: (page.page_content or "") for page in (pages or [])}
        points: list[PointStruct] = []
        for node in _flatten_toc(document.toc):
            summary = (node.summary or node.heading or "").strip()
            body = "\n".join(
                page_text.get(n, "") for n in range(node.start_page, node.end_page + 1)
            ).strip()
            full = f"{node.heading}\n{body}".strip() if body else summary
            embed_text = full[:_NODE_EMBED_LIMIT]
            if not embed_text:
                continue
            points.append(
                PointStruct(
                    id=self._node_point_id(document.document_id, node.node_id),
                    vector={
                        _DENSE_VECTOR: self.embedding_service.embed(embed_text),
                        _SPARSE_VECTOR: _sparse_vector(embed_text),
                    },
                    payload={
                        "document_id": document.document_id,
                        "file_name": document.file_name,
                        "version": document.version,
                        "content_hash": document.content_hash,
                        "status": document.status.value,
                        "node_id": node.node_id,
                        "heading": node.heading,
                        "start_page": node.start_page,
                        "end_page": node.end_page,
                        "summary": summary[:_SUMMARY_TEXT_LIMIT],
                        # The exact text that was embedded, so read-back matches the
                        # vector (the extractive summary above can be figure-OCR noise).
                        "content": embed_text,
                    },
                )
            )

        if not points:
            return 0
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def delete_document(self, document_id: str) -> None:
        self.ensure_collection()
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
                )
            ),
        )

    def search_nodes(self, query: str, top_k: int, mode: str = "hybrid") -> list[dict]:
        """Hybrid (dense + BM25 sparse) node search with Qdrant server-side RRF fusion.

        ``mode`` is one of ``hybrid`` | ``dense`` | ``bm25``.
        """
        self.ensure_collection()
        completed = Filter(
            must=[FieldCondition(key="status", match=MatchValue(value="completed"))]
        )
        sparse = _sparse_vector(query)
        has_sparse = bool(sparse.indices)
        common = {
            "collection_name": self.collection,
            "limit": top_k,
            "with_payload": True,
            "query_filter": completed,
        }

        if mode == "bm25" and has_sparse:
            result = self.client.query_points(query=sparse, using=_SPARSE_VECTOR, **common)
        elif mode == "dense" or not has_sparse:
            dense = self.embedding_service.embed(query)
            result = self.client.query_points(query=dense, using=_DENSE_VECTOR, **common)
        else:
            # Hybrid: fetch each branch, fuse server-side with RRF.
            dense = self.embedding_service.embed(query)
            prefetch_limit = max(top_k * 4, 20)
            result = self.client.query_points(
                prefetch=[
                    Prefetch(query=dense, using=_DENSE_VECTOR, limit=prefetch_limit),
                    Prefetch(query=sparse, using=_SPARSE_VECTOR, limit=prefetch_limit),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                **common,
            )

        hits: list[dict] = []
        for point in result.points:
            payload = point.payload or {}
            if not payload.get("document_id"):
                continue
            hits.append(
                {
                    "document_id": payload["document_id"],
                    "file_name": payload.get("file_name"),
                    "node_id": payload.get("node_id"),
                    "heading": payload.get("heading"),
                    "summary": payload.get("summary"),
                    "content": payload.get("content"),
                    "start_page": payload.get("start_page"),
                    "end_page": payload.get("end_page"),
                    "score": point.score,
                }
            )
        return hits

    def search(self, query: str, top_k: int, mode: str = "hybrid") -> list[str]:
        """Document-level coarse search built from the best-scoring node per document."""
        ordered: list[str] = []
        for hit in self.search_nodes(query, max(top_k * 5, 20), mode):
            document_id = hit["document_id"]
            if document_id not in ordered:
                ordered.append(document_id)
            if len(ordered) >= top_k:
                break
        return ordered
