from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_name: str = "Hybride PageIndex RAG"
    log_level: str = "INFO"
    use_database: bool = False
    use_qdrant: bool = False
    require_auth: bool = False
    auth_secret: str = "change-me-auth-secret"
    auth_token_ttl_minutes: int = 720
    auth_users_raw: str = Field(default="admin:admin:admin", validation_alias="AUTH_USERS")
    mineru_command: str = "mineru"
    mineru_backend: str = "pipeline"
    mineru_method: str = "auto"  # auto | txt | ocr (txt skips OCR for born-digital PDFs)
    mineru_formula: bool = True  # set False to skip the expensive formula model (faster on CPU)
    mineru_table: bool = True  # set False to skip table parsing (faster on CPU)
    mineru_timeout_seconds: int = 1200
    # MinerU parsing playground: proxy to MinerU's own FastAPI (mineru-api). When
    # mineru_api_url is unset and autostart is on, a local mineru-api is launched
    # on mineru_api_port (8201 avoids 8000, which is taken by supabase-kong here).
    mineru_api_url: str | None = None
    mineru_api_port: int = 8201
    mineru_api_autostart: bool = True
    use_background_worker: bool = False
    worker_max_workers: int = 2
    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ORIGINS",
    )
    upload_dir: str = "uploads"

    db_user: str = "postgres"
    db_password: str = "change-me"
    db_host: str = "127.0.0.1"
    db_port: int = 5433
    db_name: str = "postgres"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "km_nodes"
    qdrant_vector_size: int = 1024

    retrieval_strategy: str = "hybrid"  # dense | bm25 | hybrid
    retrieval_rerank: bool = True
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    use_agno: bool = False
    llm_toc_summary: bool = False  # one LLM call per TOC node; off keeps ingestion fast
    litellm_base_url: str = "http://127.0.0.1:4001/v1"
    litellm_api_key: str = "change-me"
    model_id: str = "qwen35-27b"
    synthesis_timeout_seconds: float = 60.0
    synthesis_max_tokens: int = 1536
    # Agno agent query path: reasoning model + tool calls + JSON output needs a
    # generous output budget or qwen strands the answer in reasoning_content.
    agent_max_tokens: int = 4096
    agent_search_top_k: int = 5
    agent_num_history_runs: int = 5  # prior conversation turns Agno injects as context

    embedding_base_url: str = "http://127.0.0.1:1234/v1"
    embedding_model: str = "text-embedding-qwen3-embedding-0.6b"
    embedding_context_length: int = 4096
    embedding_timeout_seconds: float = 3.0

    phoenix_endpoint: str | None = None
    phoenix_project: str = "hybride-pageindex-rag"
    phoenix_protocol: str = "http/protobuf"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def auth_users(self) -> dict[str, dict[str, str]]:
        """Parse ``username:password:role`` triples into a credential registry."""
        users: dict[str, dict[str, str]] = {}
        for entry in self.auth_users_raw.split(","):
            parts = [part.strip() for part in entry.split(":")]
            if len(parts) < 2 or not parts[0]:
                continue
            username, password = parts[0], parts[1]
            role = parts[2] if len(parts) > 2 and parts[2] else "user"
            users[username] = {"password": password, "role": role}
        return users

    @property
    def database_url(self) -> str:
        return (
            "postgresql+psycopg://"
            f"{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
