from app.services.markdown_parser import MarkdownPageParser


def test_parse_pages_and_toc_from_markdown() -> None:
    markdown = """<!-- page: 1 -->
# 設備開機

檢查電壓。

<!-- page: 2 -->
## 真空度不足

確認 O-ring。
"""

    parsed = MarkdownPageParser().parse(markdown)

    assert parsed.total_pages == 2
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert parsed.toc[0].heading == "設備開機"
    assert parsed.toc[0].end_page == 1
    assert parsed.toc[1].heading == "真空度不足"
    assert parsed.toc[1].start_page == 2
