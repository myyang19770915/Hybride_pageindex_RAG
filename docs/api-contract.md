# API Contract

Base path: `/api`

## Health

`GET /health`

```json
{
  "status": "ok",
  "app_name": "Hybride PageIndex RAG",
  "environment": "local"
}
```

## Documents

`POST /documents`

Upload a PDF and create an ingestion job.

Response:

```json
{
  "job_id": "job_...",
  "document_id": "doc_...",
  "status": "queued"
}
```

`GET /documents/jobs/{job_id}`

Return queued/processing/completed/failed ingestion status plus upload hash metadata.

`POST /documents/jobs/{job_id}/process`

Trigger the PoC ingestion processor. It reads MinerU Markdown from
`uploads/mineru/{document_id}` when available, parses pages/headings, and updates
the document status. If no MinerU Markdown exists yet, it uses a placeholder page
so the job lifecycle remains testable.

`GET /documents`

List documents and ingestion status.

`GET /documents/{document_id}`

Return document metadata and TOC tree.

`GET /documents/{document_id}/pages`

Return page-level raw Markdown captured by the ingestion processor.

`DELETE /documents/{document_id}`

Delete one document version and synchronize PostgreSQL/Qdrant cleanup.

## Query

`POST /query`

```json
{
  "query": "當機台出現真空度不足，且驅動器報 ERR_01 時該怎麼處置？",
  "mode": "auto",
  "top_k": 5
}
```

Response:

```json
{
  "answer": "...",
  "mode": "hybrid_agentic",
  "citations": [
    {
      "document_id": "doc_txc_001",
      "file_name": "TXC_SOP_2026.pdf",
      "start_page": 16,
      "end_page": 17
    }
  ],
  "trace": []
}
```

`POST /query/stream`

SSE endpoint for agent trace events. It accepts the same JSON body as `POST /query` and emits:

- `event: trace` with one `TraceEvent`.
- `event: final` with the final `QueryResponse`.
