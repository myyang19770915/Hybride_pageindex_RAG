"""Tests for the page-evidence service (region extraction, normalisation,
answer-to-block matching) and the evidence API route."""

import json

from app.main import app
from app.services import page_evidence
from fastapi.testclient import TestClient

client = TestClient(app)


def _middle_fixture(tmp_path):
    """A minimal MinerU middle.json: one page, page_size 100x200, two blocks."""
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [100, 200],
                "para_blocks": [
                    {
                        "type": "title",
                        "bbox": [10, 20, 90, 40],
                        "lines": [{"spans": [{"content": "Docling 文件轉換工具"}]}],
                    },
                    {
                        "type": "text",
                        "bbox": [10, 60, 90, 120],
                        "lines": [{"spans": [{"content": "完全無關的雜訊內容片段"}]}],
                    },
                ],
            }
        ]
    }
    path = tmp_path / "doc_x_middle.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_page_blocks_normalises_bbox(tmp_path, monkeypatch):
    middle = _middle_fixture(tmp_path)
    monkeypatch.setattr(page_evidence.MineruClient, "find_middle_output", lambda self, key: middle)

    evidence = page_evidence.load_page_blocks("doc_x", None, 1)
    assert evidence is not None
    assert (evidence.page_width, evidence.page_height) == (100.0, 200.0)
    assert len(evidence.blocks) == 2
    # bbox [10,20,90,40] over a 100x200 page -> [0.1, 0.1, 0.9, 0.2]
    assert evidence.blocks[0].bbox == [0.1, 0.1, 0.9, 0.2]
    assert "Docling" in evidence.blocks[0].text


def test_load_page_blocks_missing_middle_returns_none(monkeypatch):
    monkeypatch.setattr(page_evidence.MineruClient, "find_middle_output", lambda self, key: None)
    assert page_evidence.load_page_blocks("doc_x", None, 1) is None


def test_load_page_blocks_out_of_range_page(tmp_path, monkeypatch):
    middle = _middle_fixture(tmp_path)
    monkeypatch.setattr(page_evidence.MineruClient, "find_middle_output", lambda self, key: middle)
    assert page_evidence.load_page_blocks("doc_x", None, 99) is None


def test_score_blocks_flags_the_relevant_block(tmp_path, monkeypatch):
    middle = _middle_fixture(tmp_path)
    monkeypatch.setattr(page_evidence.MineruClient, "find_middle_output", lambda self, key: middle)

    evidence = page_evidence.load_page_blocks("doc_x", None, 1)
    page_evidence.score_blocks(
        evidence, answer="Docling 是一個文件轉換工具", query="什麼是 Docling"
    )

    title, noise = evidence.blocks
    assert title.matched is True
    assert title.score > noise.score
    assert noise.matched is False


def test_score_blocks_marks_best_when_nothing_crosses_threshold(tmp_path, monkeypatch):
    middle = _middle_fixture(tmp_path)
    monkeypatch.setattr(page_evidence.MineruClient, "find_middle_output", lambda self, key: middle)

    evidence = page_evidence.load_page_blocks("doc_x", None, 1)
    # An answer that weakly overlaps only the title; still, the modal must not be
    # empty -> the single best block is marked matched.
    page_evidence.score_blocks(evidence, answer="Docling", query="")
    assert sum(b.matched for b in evidence.blocks) >= 1


def test_evidence_route_demo_doc_has_no_regions():
    # The synthetic demo doc has no MinerU middle.json -> graceful empty payload.
    response = client.post(
        "/api/documents/doc_demo_txc/pages/16/evidence",
        json={"answer": "真空度不足", "query": "真空度"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_regions"] is False
    assert body["blocks"] == []


def test_evidence_route_validates_payload():
    # answer over the max length is rejected.
    response = client.post(
        "/api/documents/doc_demo_txc/pages/1/evidence",
        json={"answer": "x" * 20001},
    )
    assert response.status_code == 422
