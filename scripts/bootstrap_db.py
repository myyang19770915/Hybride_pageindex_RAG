import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.database import Base, engine  # noqa: E402
from app.models import KmDocument, KmDocumentPage, KmIngestionJob  # noqa: E402


def main() -> None:
    _ = (KmDocument, KmDocumentPage, KmIngestionJob)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE km_documents ADD COLUMN IF NOT EXISTS stored_path TEXT")
        )
        connection.execute(
            text("ALTER TABLE km_ingestion_jobs ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)")
        )
        connection.execute(
            text("ALTER TABLE km_ingestion_jobs ADD COLUMN IF NOT EXISTS content_hash VARCHAR(128)")
        )
        connection.execute(
            text("ALTER TABLE km_documents ADD COLUMN IF NOT EXISTS owner VARCHAR(128)")
        )
        connection.execute(
            text(
                "ALTER TABLE km_documents "
                "ADD COLUMN IF NOT EXISTS is_latest BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
    print("PostgreSQL schema is ready.")


if __name__ == "__main__":
    main()
