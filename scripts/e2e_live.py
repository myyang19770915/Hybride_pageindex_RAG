import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("USE_DATABASE", "true")
os.environ.setdefault("USE_QDRANT", "true")
os.environ.setdefault("DB_PASSWORD", "change-me")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> None:
    client = TestClient(app)
    run_id = uuid4().hex[:8]
    marker = f"marker-{run_id}"
    file_name = f"live-e2e-{run_id}.pdf"
    pdf_bytes = f"%PDF-1.4\nlive e2e {run_id}".encode()

    upload_response = client.post(
        "/api/documents",
        files={"file": (file_name, pdf_bytes, "application/pdf")},
    )
    upload_response.raise_for_status()
    upload_payload = upload_response.json()
    document_id = upload_payload["document_id"]
    job_id = upload_payload["job_id"]

    mineru_dir = Path(get_settings().upload_dir) / "mineru" / document_id
    mineru_dir.mkdir(parents=True, exist_ok=True)
    markdown = f"""<!-- page: 1 -->
# 設備開機與環境檢查

開機前需確認電壓、氣壓、環境溫溼度。

<!-- page: 2 -->
## 真空度不足與 ERR_01

當機台出現真空度不足且驅動器報 ERR_01 時，請確認冷卻水流量大於 2.0 L/min，
並檢查 O-ring 是否污染。唯一驗證碼 {marker}。

<!-- page: 3 -->
## 復機確認

排除異常後需重新確認分子泵轉速與真空度穩定。
"""
    (mineru_dir / "mineru.md").write_text(markdown, encoding="utf-8")

    process_response = client.post(f"/api/documents/jobs/{job_id}/process")
    process_response.raise_for_status()
    process_payload = process_response.json()
    assert process_payload["status"] == "completed", process_payload

    document_response = client.get(f"/api/documents/{document_id}")
    document_response.raise_for_status()
    document_payload = document_response.json()
    assert document_payload["total_pages"] == 3, document_payload
    assert len(document_payload["toc"]) >= 2, document_payload

    pages_response = client.get(f"/api/documents/{document_id}/pages")
    pages_response.raise_for_status()
    pages_payload = pages_response.json()
    assert len(pages_payload) == 3, pages_payload
    assert "ERR_01" in pages_payload[1]["page_content"], pages_payload

    query_response = client.post(
        "/api/query",
        json={
            "query": f"ERR_01 真空度不足 {marker}",
            "mode": "auto",
            "top_k": 5,
        },
    )
    query_response.raise_for_status()
    query_payload = query_response.json()
    assert query_payload["citations"], query_payload
    assert query_payload["citations"][0]["document_id"] == document_id, query_payload
    assert "ERR_01" in query_payload["answer"], query_payload

    with client.stream(
        "POST",
        "/api/query/stream",
        json={
            "query": f"ERR_01 真空度不足 {marker}",
            "mode": "auto",
            "top_k": 5,
        },
    ) as stream_response:
        stream_response.raise_for_status()
        stream_body = "".join(stream_response.iter_text())
    assert "event: trace" in stream_body, stream_body
    assert "event: final" in stream_body, stream_body

    print(
        "Live E2E passed:",
        {
            "document_id": document_id,
            "job_id": job_id,
            "pages": len(pages_payload),
            "citation": query_payload["citations"][0],
        },
    )


if __name__ == "__main__":
    main()
