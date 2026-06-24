"""Contract tests for the eval API endpoints."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_list_golden_returns_items() -> None:
    response = client.get("/api/eval/golden")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    if items:  # golden_set.jsonl is committed, so this should be populated
        first = items[0]
        assert {"id", "query", "file_name", "page_number"} <= set(first)


def test_run_eval_returns_metrics_and_items() -> None:
    # limit keeps the run fast; synthesize is always off for the API path.
    response = client.post("/api/eval/run", json={"limit": 2, "top_k": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["n"] <= 2
    for key in ("doc_hit_rate", "page_hit_rate", "mrr", "answered_rate"):
        assert key in body["metrics"]
    assert len(body["items"]) == body["n"]
    if body["items"]:
        assert {"query", "page_number", "doc_hit", "page_hit"} <= set(body["items"][0])


def test_run_eval_rejects_bad_top_k() -> None:
    response = client.post("/api/eval/run", json={"top_k": 999})
    assert response.status_code == 422  # validation: top_k max 20
