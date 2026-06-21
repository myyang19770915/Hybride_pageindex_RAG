from app.main import app
from app.services.ranking import BM25Index, reciprocal_rank_fusion, tokenize
from fastapi.testclient import TestClient


def test_tokenize_splits_cjk_into_characters() -> None:
    tokens = tokenize("真空度 ERR_01")
    assert "真" in tokens
    assert "空" in tokens
    assert "err" in tokens
    assert "01" in tokens


def test_bm25_ranks_relevant_document_first() -> None:
    index = BM25Index().fit(
        {
            "a": "真空度不足 排查 O-ring 分子泵",
            "b": "薪資 報銷 流程 與 表單",
        }
    )
    ranked = index.rank("真空度不足怎麼處理")
    assert ranked[0] == "a"


def test_rrf_prefers_consensus() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert fused[0] in {"a", "b"}
    assert set(fused) == {"a", "b", "c", "d"}


def test_query_reports_hybrid_and_rerank_stages() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"query": "真空度不足 ERR_01 怎麼處理？", "mode": "auto", "top_k": 5},
    )
    assert response.status_code == 200
    stages = {event["stage"] for event in response.json()["trace"]}
    assert "sparse_search" in stages
    assert "rerank" in stages


def test_query_accepts_strategy_override() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"query": "ERR_01", "mode": "auto", "top_k": 5, "strategy": "bm25"},
    )
    assert response.status_code == 200
    stages = {event["stage"] for event in response.json()["trace"]}
    assert "sparse_search" in stages
    assert "fusion" not in stages
