# System Survey

## Source Documents

- `sdd.md`: Main software design document for an on-premise hybrid Agentic RAG system.
- `技術規格.md`: Concrete infrastructure notes, model endpoints, framework choices, and style preferences.

## Product Goal

Build an on-premise enterprise KM system that avoids the semantic breakage of naive chunking. The system combines vector-based coarse retrieval with PageIndex-style document navigation over a prebuilt table-of-contents tree.

## Core Pipeline

1. User uploads one or many PDF documents.
2. MinerU converts PDFs into Markdown with page markers and structural headings.
3. Ingestion extracts headings and page ranges, then asks the local LLM to summarize TOC nodes.
4. PostgreSQL stores document metadata, JSONB TOC trees, versions, and page-level raw Markdown.
5. Qdrant stores coarse retrieval vectors and payload metadata.
6. Query router chooses simple vector RAG or hybrid Agentic RAG.
7. Agent navigates candidate TOC trees, fetches raw page ranges, and answers with evidence.

## Confirmed Technical Choices

- Python 3.12+
- `uv` for Python package/environment management
- FastAPI backend
- React 19 frontend
- PostgreSQL with JSONB
- Qdrant for vector/hybrid search
- MinerU / Magic-PDF for PDF parsing. Installed as `mineru[core]>=3.4.0` for Windows-compatible pipeline use.
- Agno as the agent framework
- LiteLLM/OpenAI-compatible local model endpoint
- Phoenix/OpenTelemetry for tracing

## Gaps To Resolve During Build

- Exact MinerU output page-marker format.
- Production document versioning policy.
- Qdrant collection schema and sparse/BM25 implementation details.
- Whether ingestion runs in-process for PoC or via a dedicated worker.
- Exact frontend screens beyond upload, document list, chat, and trace viewer.
