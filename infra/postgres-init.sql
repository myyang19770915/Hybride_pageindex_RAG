CREATE TABLE IF NOT EXISTS km_documents (
    document_id VARCHAR(64) PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    version VARCHAR(64) NOT NULL,
    content_hash VARCHAR(128) NOT NULL,
    total_pages INT NOT NULL,
    json_tree JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    stored_path TEXT,
    owner VARCHAR(128),
    is_latest BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_name, version, owner)
);

CREATE TABLE IF NOT EXISTS km_document_pages (
    page_id BIGSERIAL PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL REFERENCES km_documents(document_id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    page_content TEXT NOT NULL,
    UNIQUE(document_id, page_number)
);

CREATE TABLE IF NOT EXISTS km_ingestion_jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    message TEXT,
    file_name VARCHAR(255),
    content_hash VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_km_documents_status ON km_documents(status);
CREATE INDEX IF NOT EXISTS idx_km_document_pages_document_id ON km_document_pages(document_id);
