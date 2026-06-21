import json

from app.services.markdown_parser import MarkdownPageParser
from app.services.mineru import MineruClient


def test_content_list_rebuilds_page_marked_markdown(tmp_path) -> None:
    content_list = tmp_path / "sample_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "設備開機", "text_level": 2, "page_idx": 0},
                {"type": "text", "text": "確認電壓。", "page_idx": 0},
                {"type": "text", "text": "ERR_01", "text_level": 2, "page_idx": 1},
                {"type": "text", "text": "確認冷卻水流量。", "page_idx": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    markdown = MineruClient()._markdown_from_content_list(content_list)
    parsed = MarkdownPageParser().parse(markdown)

    assert parsed.total_pages == 2
    assert parsed.pages[1].page_number == 2
    assert parsed.toc[1].heading == "ERR_01"


def test_content_list_includes_tables_and_image_captions(tmp_path) -> None:
    content_list = tmp_path / "tbl_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "規格表", "text_level": 1, "page_idx": 0},
                {
                    "type": "table",
                    "table_caption": ["額定參數"],
                    "table_body": (
                        "<table><tr><th>項目</th><th>值</th></tr>"
                        "<tr><td>電壓</td><td>220V</td></tr></table>"
                    ),
                    "table_footnote": ["量測於 25°C"],
                    "page_idx": 0,
                },
                {
                    "type": "image",
                    "img_path": "images/fig1.jpg",
                    "image_caption": ["圖1 系統架構"],
                    "page_idx": 0,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    markdown = MineruClient()._markdown_from_content_list(content_list)

    assert "額定參數" in markdown
    assert "電壓 | 220V" in markdown  # HTML table flattened to pipe-separated text
    assert "量測於 25°C" in markdown
    assert "圖1 系統架構" in markdown
