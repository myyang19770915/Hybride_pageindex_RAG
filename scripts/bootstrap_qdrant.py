import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402


def main() -> None:
    # Creates the collection with the hybrid schema: a dense vector + a BM25 sparse
    # vector (IDF modifier) for Qdrant native hybrid queries.
    VectorStoreService().ensure_collection()
    print(f"Qdrant collection is ready: {get_settings().qdrant_collection}")


if __name__ == "__main__":
    main()
