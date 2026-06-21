"""End-to-end test against a *running* backend over HTTP.

Unlike e2e_live.py (in-process TestClient), this drives the real ASGI server at
BASE_URL, exercising upload -> process -> query -> stream -> versioning ->
deletion cleanup. Start the server first:

    uv run --extra observability uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
"""

import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))


def _write_markdown(document_id: str, marker: str) -> None:
    mineru_dir = UPLOAD_DIR / "mineru" / document_id
    mineru_dir.mkdir(parents=True, exist_ok=True)
    (mineru_dir / "mineru.md").write_text(
        f"""<!-- page: 1 -->
# 設備開機與環境檢查

開機前需確認電壓、氣壓、環境溫溼度。

<!-- page: 2 -->
## 真空度不足與 ERR_01

當機台出現真空度不足且驅動器報 ERR_01 時，請確認冷卻水流量大於 2.0 L/min，
並檢查 O-ring 是否污染。唯一驗證碼 {marker}。

<!-- page: 3 -->
## 復機確認

排除異常後需重新確認分子泵轉速與真空度穩定。
""",
        encoding="utf-8",
    )


def _upload(client: httpx.Client, name: str, content: bytes) -> dict:
    response = client.post(
        "/api/documents",
        files={"file": (name, content, "application/pdf")},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    run_id = uuid4().hex[:8]
    marker = f"marker-{run_id}"
    results: dict[str, object] = {}

    with httpx.Client(base_url=BASE_URL, timeout=120) as client:
        assert client.get("/api/health").json()["status"] == "ok"

        # 1) Upload + ingest a first version.
        upload = _upload(client, f"http-e2e-{run_id}.pdf", f"%PDF-1.4 {run_id} A".encode())
        document_id, job_id = upload["document_id"], upload["job_id"]
        _write_markdown(document_id, marker)
        processed = client.post(f"/api/documents/jobs/{job_id}/process")
        processed.raise_for_status()
        assert processed.json()["status"] == "completed", processed.json()
        results["ingest"] = processed.json()["status"]

        detail = client.get(f"/api/documents/{document_id}").json()
        assert detail["total_pages"] == 3, detail
        assert len(detail["toc"]) >= 2, detail
        results["toc_nodes"] = len(detail["toc"])

        # 2) Query (LLM synthesis) + trace stages.
        query = client.post(
            "/api/query",
            json={"query": f"ERR_01 真空度不足 {marker}", "mode": "auto", "top_k": 5},
        ).json()
        assert query["citations"], query
        assert query["citations"][0]["document_id"] == document_id, query
        stages = [event["stage"] for event in query["trace"]]
        assert "synthesis" in stages, stages
        results["query_stages"] = stages
        results["answer_preview"] = query["answer"][:120]

        # 3) Streaming query.
        with client.stream(
            "POST",
            "/api/query/stream",
            json={"query": f"ERR_01 {marker}", "mode": "auto", "top_k": 5},
        ) as stream:
            stream.raise_for_status()
            body = "".join(stream.iter_text())
        assert "event: trace" in body and "event: final" in body
        results["stream"] = "ok"

        # 4) Versioning: dedup + new version + latest_only.
        dup = _upload(client, f"http-e2e-{run_id}.pdf", f"%PDF-1.4 {run_id} A".encode())
        assert dup["document_id"] == document_id, dup  # identical content -> reuse
        v2 = _upload(client, f"http-e2e-{run_id}.pdf", f"%PDF-1.4 {run_id} B".encode())
        assert v2["document_id"] != document_id, v2
        versions = client.get(f"/api/documents/{v2['document_id']}/versions").json()
        results["versions"] = {item["version"]: item["is_latest"] for item in versions}
        latest = client.get("/api/documents", params={"latest_only": "true"}).json()
        latest_ids = {item["document_id"] for item in latest}
        assert v2["document_id"] in latest_ids and document_id not in latest_ids
        results["dedup_and_versioning"] = "ok"

        # 5) Deletion cleanup (PostgreSQL + Qdrant + files).
        deleted = client.request("DELETE", f"/api/documents/{document_id}").json()
        assert deleted["status"] == "deleted", deleted
        assert client.get(f"/api/documents/{document_id}").status_code == 404
        results["delete_message"] = deleted["message"]
        # clean up the v2 we created
        client.request("DELETE", f"/api/documents/{v2['document_id']}")

    print("HTTP live E2E passed:")
    for key, value in results.items():
        print(f"  - {key}: {value}")


if __name__ == "__main__":
    sys.exit(main())
