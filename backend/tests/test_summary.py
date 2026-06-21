from app.schemas.documents import TocNode
from app.schemas.ingestion import ParsedPage
from app.services.summary import SummaryService


def test_summary_service_falls_back_to_extractive_summary() -> None:
    toc = [
        TocNode(
            node_id="N1",
            heading="真空度不足",
            start_page=1,
            end_page=1,
            summary="old",
        )
    ]
    pages = [
        ParsedPage(
            page_number=1,
            content="真空度不足時，請確認 O-ring 是否污染。ERR_01 需檢查冷卻水流量。",
        )
    ]

    summarized = SummaryService().summarize_toc(toc, pages)

    assert summarized[0].summary != "old"
    assert "真空度不足" in summarized[0].summary
