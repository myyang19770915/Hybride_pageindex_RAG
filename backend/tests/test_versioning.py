from app.main import app
from fastapi.testclient import TestClient


def _upload(client: TestClient, name: str, content: bytes) -> dict:
    return client.post(
        "/api/documents",
        files={"file": (name, content, "application/pdf")},
    ).json()


def test_duplicate_upload_reuses_existing_document() -> None:
    client = TestClient(app)
    first = _upload(client, "dup.pdf", b"%PDF-1.4\nidentical-bytes")
    again = _upload(client, "dup.pdf", b"%PDF-1.4\nidentical-bytes")

    assert again["document_id"] == first["document_id"]
    assert "Duplicate" in again["message"]


def test_new_content_creates_new_version_and_marks_latest() -> None:
    client = TestClient(app)
    v1 = _upload(client, "versioned.pdf", b"%PDF-1.4\ncontent-A")
    v2 = _upload(client, "versioned.pdf", b"%PDF-1.4\ncontent-B")

    assert v1["document_id"] != v2["document_id"]

    versions = client.get(f"/api/documents/{v2['document_id']}/versions").json()
    by_id = {item["document_id"]: item for item in versions}
    assert by_id[v1["document_id"]]["version"] == "v1"
    assert by_id[v2["document_id"]]["version"] == "v2"
    assert by_id[v1["document_id"]]["is_latest"] is False
    assert by_id[v2["document_id"]]["is_latest"] is True

    latest = client.get("/api/documents", params={"latest_only": "true"}).json()
    latest_ids = {item["document_id"] for item in latest}
    assert v2["document_id"] in latest_ids
    assert v1["document_id"] not in latest_ids
