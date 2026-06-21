from app.main import app
from fastapi.testclient import TestClient


def test_query_contract() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"query": "ERR_01 怎麼處理？", "mode": "auto", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "hybrid_agentic"
    assert payload["answer"]
    assert payload["citations"]
    assert payload["trace"]


def test_query_stream_contract() -> None:
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/query/stream",
        json={"query": "ERR_01 怎麼處理？", "mode": "auto", "top_k": 5},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: trace" in body
    assert "event: final" in body
    assert "data:" in body
