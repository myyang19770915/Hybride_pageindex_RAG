from datetime import UTC, datetime

from app.schemas.documents import DocumentDetail, DocumentPage, IngestionStatus
from app.services.synthesis import AnswerSynthesisService


def _document() -> DocumentDetail:
    return DocumentDetail(
        document_id="doc_test",
        file_name="test.pdf",
        version="v1",
        total_pages=1,
        status=IngestionStatus.completed,
        created_at=datetime.now(UTC),
        content_hash="hash",
    )


def test_synthesis_falls_back_to_extractive_without_llm() -> None:
    pages = [
        DocumentPage(
            document_id="doc_test",
            page_number=16,
            page_content="真空度不足時請檢查 O-ring 與分子泵轉速。",
        )
    ]

    result = AnswerSynthesisService().synthesize("真空度不足怎麼辦？", _document(), pages)

    assert result.method == "extractive"
    assert "真空度不足" in result.answer
    assert "第 16 頁" in result.answer


def test_synthesis_handles_empty_pages() -> None:
    result = AnswerSynthesisService().synthesize("任意問題", _document(), [])

    assert result.method == "extractive"
    assert "沒有可引用" in result.answer
