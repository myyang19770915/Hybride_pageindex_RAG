# Architecture

## Scope

The first implementation should be a modular PoC that can run locally without forcing every external service to be available. Service clients are wrapped behind interfaces so real PostgreSQL, Qdrant, MinerU, LiteLLM, and Agno integrations can be swapped in incrementally.

## Backend Modules

- `app.core`: configuration, logging, app lifecycle, dependency factories.
- `app.api`: FastAPI routers and request/response boundaries.
- `app.schemas`: Pydantic schemas for documents, ingestion, retrieval, and agent traces.
- `app.models`: persistence models and database metadata.
- `app.services`: domain logic for ingestion, retrieval, document storage, vector indexing, and agent orchestration.

## Data Model

### `km_documents`

Stores one logical document version.

- `document_id`
- `file_name`
- `version`
- `content_hash`
- `total_pages`
- `json_tree`
- `status`
- `created_at`
- `updated_at`

### `km_document_pages`

Stores raw page-level Markdown.

- `page_id`
- `document_id`
- `page_number`
- `page_content`

### `km_ingestion_jobs`

Tracks asynchronous ingestion state.

- `job_id`
- `document_id`
- `status`
- `message`
- `created_at`
- `updated_at`

## Retrieval Strategy

### Simple Vector RAG

Use when a query is direct and answerable from a narrow chunk or FAQ-like context.

1. Embed the query.
2. Search Qdrant top-k chunks or summaries.
3. Generate an answer with compact context.

### Hybrid Agentic RAG

Use when a query needs page-aware reasoning, cross-page steps, error code handling, or procedural detail.

1. Coarse-search Qdrant for candidate documents.
2. Load candidate TOC trees from PostgreSQL.
3. Ask the Agno agent to select relevant TOC nodes.
4. Fetch raw Markdown page ranges from PostgreSQL.
5. Generate final answer with cited document/page context.

## Frontend Views

- Document upload and ingestion status.
- Document list with version/status metadata.
- Query workspace with answer panel.
- Agent trace panel driven by SSE.
- Document detail view showing TOC tree and page ranges.

## Observability

The backend should emit structured logs and optional Phoenix traces around:

- PDF parsing
- TOC extraction
- LLM summarization
- Qdrant upsert/search
- Router decisions
- Agent node selection
- Final answer generation
