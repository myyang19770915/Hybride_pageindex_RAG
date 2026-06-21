from pathlib import Path

from app.core.config import get_settings
from app.main import app
from fastapi.testclient import TestClient


def test_upload_document_and_read_job() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/documents",
        files={"file": ("sample.pdf", b"%PDF-1.4\nsample", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["document_id"].startswith("doc_")
    assert payload["job_id"].startswith("job_")

    job_response = client.get(f"/api/documents/jobs/{payload['job_id']}")
    assert job_response.status_code == 200
    job_payload = job_response.json()
    assert job_payload["document_id"] == payload["document_id"]
    assert job_payload["content_hash"]

    mineru_dir = Path(get_settings().upload_dir) / "mineru" / payload["document_id"]
    mineru_dir.mkdir(parents=True, exist_ok=True)
    (mineru_dir / "sample.md").write_text(
        "<!-- page: 1 -->\n# 真空度不足\n\nERR_01 冷卻水流量需大於 2.0 L/min。",
        encoding="utf-8",
    )

    documents_response = client.get("/api/documents")
    assert documents_response.status_code == 200
    file_names = {item["file_name"] for item in documents_response.json()}
    assert "sample.pdf" in file_names

    process_response = client.post(f"/api/documents/jobs/{payload['job_id']}/process")
    assert process_response.status_code == 200
    assert process_response.json()["status"] == "completed"

    document_response = client.get(f"/api/documents/{payload['document_id']}")
    assert document_response.status_code == 200
    document_payload = document_response.json()
    assert document_payload["status"] == "completed"
    assert document_payload["total_pages"] == 1
    assert document_payload["toc"]

    pages_response = client.get(f"/api/documents/{payload['document_id']}/pages")
    assert pages_response.status_code == 200
    pages_payload = pages_response.json()
    assert pages_payload[0]["page_number"] == 1
    assert "ERR_01" in pages_payload[0]["page_content"]


def test_delete_document_cleans_source_files() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/documents",
        files={"file": ("todelete.pdf", b"%PDF-1.4\nsample", "application/pdf")},
    ).json()
    document_id = upload["document_id"]

    # Source is stored date-partitioned (source/YYYY-MM-DD/{id}); match either layout.
    source_root = Path(get_settings().upload_dir) / "source"

    def source_dirs() -> list[Path]:
        return [
            path
            for path in [*source_root.glob(f"*/{document_id}"), source_root / document_id]
            if path.exists()
        ]

    assert source_dirs()

    delete_response = client.delete(f"/api/documents/{document_id}")
    assert delete_response.status_code == 200
    payload = delete_response.json()
    assert payload["status"] == "deleted"
    assert "files" in payload["message"]
    assert not source_dirs()

    missing = client.get(f"/api/documents/{document_id}")
    assert missing.status_code == 404


def test_reject_non_pdf_upload() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/documents",
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
