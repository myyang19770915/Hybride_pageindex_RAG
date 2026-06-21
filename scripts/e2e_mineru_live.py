import os
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("USE_DATABASE", "true")
os.environ.setdefault("USE_QDRANT", "true")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("MINERU_BACKEND", "pipeline")
os.environ.setdefault(
    "MINERU_COMMAND",
    str(Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "mineru.exe"),
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def build_pdf_bytes(run_id: str) -> bytes:
    marker = f"marker-{run_id}"
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("Helvetica", 14)
    pdf.drawString(72, 760, f"Vacuum ERR_01 Procedure {marker}")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 730, "When vacuum is insufficient and ERR_01 appears,")
    pdf.drawString(72, 712, "check cooling water flow above 2.0 L/min.")
    pdf.drawString(72, 694, marker)
    pdf.showPage()
    pdf.setFont("Helvetica", 14)
    pdf.drawString(72, 760, "Recovery Check")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 730, "Verify turbo pump speed and stable vacuum before restart.")
    pdf.save()
    return buffer.getvalue()


def main() -> None:
    client = TestClient(app)
    run_id = uuid4().hex[:8]
    marker = f"marker-{run_id}"
    file_name = f"mineru-live-{run_id}.pdf"

    upload_response = client.post(
        "/api/documents",
        files={"file": (file_name, build_pdf_bytes(run_id), "application/pdf")},
    )
    upload_response.raise_for_status()
    upload_payload = upload_response.json()
    document_id = upload_payload["document_id"]
    job_id = upload_payload["job_id"]

    process_response = client.post(f"/api/documents/jobs/{job_id}/process")
    process_response.raise_for_status()
    process_payload = process_response.json()
    assert process_payload["status"] == "completed", process_payload
    assert "MinerU content list" in process_payload["message"], process_payload

    pages_response = client.get(f"/api/documents/{document_id}/pages")
    pages_response.raise_for_status()
    pages_payload = pages_response.json()
    assert len(pages_payload) >= 2, pages_payload
    assert any("ERR" in page["page_content"] for page in pages_payload), pages_payload

    query_response = client.post(
        "/api/query",
        json={
            "query": f"ERR_01 vacuum insufficient cooling water {marker}",
            "mode": "auto",
            "top_k": 5,
        },
    )
    query_response.raise_for_status()
    query_payload = query_response.json()
    assert query_payload["citations"], query_payload
    assert query_payload["citations"][0]["document_id"] == document_id, query_payload
    assert "ERR" in query_payload["answer"], query_payload

    print(
        "MinerU live E2E passed:",
        {
            "document_id": document_id,
            "job_id": job_id,
            "pages": len(pages_payload),
            "citation": query_payload["citations"][0],
        },
    )


if __name__ == "__main__":
    main()
