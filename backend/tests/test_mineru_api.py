import json

from app.services.mineru_api import MineruApiClient


def test_tidy_parses_content_list_string_and_extracts_first_result() -> None:
    payload = {
        "backend": "pipeline",
        "version": "3.4.0",
        "results": {
            "doc": {
                "md_content": "# 標題\n內文",
                "content_list": json.dumps(
                    [{"type": "text", "text": "內文", "page_idx": 0}], ensure_ascii=False
                ),
                "images": {"fig1.jpg": "data:image/jpeg;base64,AAAA"},
            }
        },
    }
    tidy = MineruApiClient._tidy(payload)
    assert tidy["backend"] == "pipeline"
    assert tidy["version"] == "3.4.0"
    assert tidy["markdown"].startswith("# 標題")
    assert tidy["content_list"][0]["text"] == "內文"
    assert tidy["images"]["fig1.jpg"].startswith("data:image")


def test_tidy_handles_missing_and_malformed_fields() -> None:
    assert MineruApiClient._tidy({})["content_list"] == []
    bad = {"results": {"d": {"content_list": "not-json"}}}
    tidy = MineruApiClient._tidy(bad)
    assert tidy["content_list"] == []
    assert tidy["markdown"] == ""
    assert tidy["images"] == {}
