# Security Notes

## Secrets

Do not hard-code internal endpoints, API keys, database passwords, or model keys in source code. Use `.env` for local development and secret management in deployment.

The original project notes include internal URLs and example credentials. Implementation files should only reference environment variables and safe placeholders.

## Data Boundary

The system is intended for on-premise operation. Document contents, embeddings, traces, and prompts should remain inside the internal network unless explicitly approved.

## Logging

Logs should be useful for debugging but should avoid dumping full document pages by default. Trace events may include document IDs, page ranges, and short summaries.

## Deletion

Document deletion must remove:

- PostgreSQL document metadata.
- PostgreSQL page content.
- Qdrant vectors and payloads for that document/version.
- Uploaded source file if the deployment policy requires it.
