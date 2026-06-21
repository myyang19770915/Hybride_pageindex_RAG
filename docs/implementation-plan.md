# Implementation Plan

## Phase 0: Foundation

- Create project structure and development documentation.
- Add `.env.example`, Python package metadata, and backend skeleton.
- Define initial API contract and Pydantic schemas.
- Keep external integrations behind service interfaces.

## Phase 1: Backend PoC

- Implement health/config endpoints.
- Implement document upload API. Done in PoC.
- Add local file storage for uploaded PDFs. Done in PoC.
- Add ingestion job abstraction. Done in PoC.
- Add PostgreSQL schema/migration script. Initial bootstrap script added.
- Add Qdrant collection bootstrap script. Initial bootstrap script added.

## Phase 2: Ingestion

- Integrate MinerU command invocation. Done with `mineru[core]` and `pipeline` live E2E.
- Normalize Markdown page markers. Initial parser done.
- Extract headings and page ranges. Initial parser done.
- Generate TOC summaries through the local LLM.
- Generate TOC summaries through the local LLM. LiteLLM boundary with extractive fallback done.
- Persist `km_documents` and `km_document_pages`. PostgreSQL mode done.
- Upsert document summary vectors to Qdrant. Qdrant mode done.

## Phase 3: Retrieval

- Implement query router.
- Implement simple vector RAG path.
- Implement PageIndex-style Agentic RAG path using Agno.
- Add streamed trace events for navigation and page fetching. SSE stream endpoint done.

## Phase 4: Frontend

- Build document upload and status screens.
- Build chat/query workspace.
- Add SSE trace panel.
- Add document TOC explorer.

## Phase 5: Hardening

- Add tests for ingestion parsing and retrieval routing.
- Add error handling for external service outages.
- Add versioning and deletion sync between PostgreSQL and Qdrant.
- Add security review for secrets and audit logs.
