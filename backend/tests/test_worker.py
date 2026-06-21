from pathlib import Path

from app.core.config import get_settings
from app.main import app
from app.services.worker import get_job_queue
from fastapi.testclient import TestClient


def test_job_queue_processes_ingestion_in_background() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/documents",
        files={"file": ("worker.pdf", b"%PDF-1.4\nsample", "application/pdf")},
    ).json()
    job_id = upload["job_id"]
    document_id = upload["document_id"]

    mineru_dir = Path(get_settings().upload_dir) / "mineru" / document_id
    mineru_dir.mkdir(parents=True, exist_ok=True)
    (mineru_dir / "worker.md").write_text(
        "<!-- page: 1 -->\n# 背景處理\n\nERR_01 由 worker 解析完成。",
        encoding="utf-8",
    )

    status = get_job_queue().submit(job_id).result(timeout=15)
    assert status == "completed"

    job = client.get(f"/api/documents/jobs/{job_id}").json()
    assert job["status"] == "completed"
