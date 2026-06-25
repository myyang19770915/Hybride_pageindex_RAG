import json
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

from app.core.config import get_settings


def storage_key(document_id: str, created_at: datetime | None) -> str:
    """Date-partitioned storage subpath (``YYYY-MM-DD/document_id``).

    Uploaded sources and MinerU artifacts are stored under this key so files are
    easy to find by date. Falls back to a flat key when no date is available.
    """
    if created_at is None:
        return document_id
    return f"{created_at.strftime('%Y-%m-%d')}/{document_id}"


class _TableTextExtractor(HTMLParser):
    """Flatten a MinerU HTML table into pipe-separated rows of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
        elif tag == "tr":
            self._row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append("".join(self._cell).strip())
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _html_table_to_text(html: str) -> str:
    parser = _TableTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    lines = [" | ".join(row) for row in parser.rows if any(row)]
    return "\n".join(lines)


class MineruClient:
    """MinerU integration boundary with a local PDF extraction fallback."""

    def _mineru_dirs(self, doc_key: str) -> list[Path]:
        """Existing MinerU output dirs for a doc: dated path first, then the legacy
        flat path (`mineru/{document_id}`) for artifacts created before dating."""
        base = Path(get_settings().upload_dir) / "mineru"
        candidates = [base / doc_key]
        flat = doc_key.split("/")[-1]
        if flat != doc_key:
            candidates.append(base / flat)
        return [path for path in candidates if path.exists()]

    def find_markdown_output(self, doc_key: str) -> Path | None:
        for output_dir in self._mineru_dirs(doc_key):
            markdown_files = sorted(output_dir.rglob("*.md"))
            if markdown_files:
                return markdown_files[0]
        return None

    def find_content_list_output(self, doc_key: str) -> Path | None:
        for output_dir in self._mineru_dirs(doc_key):
            candidates = sorted(output_dir.rglob("*_content_list.json"))
            if candidates:
                return candidates[0]
        return None

    def find_middle_output(self, doc_key: str) -> Path | None:
        """MinerU's ``*_middle.json`` (per-page ``page_size`` + ``para_blocks`` with
        bbox in that same coordinate space) — the source of truth for region
        highlighting. content_list.json bbox is a different scaled space, so it is
        not used for overlays."""
        for output_dir in self._mineru_dirs(doc_key):
            candidates = sorted(output_dir.rglob("*_middle.json"))
            if candidates:
                return candidates[0]
        return None

    def read_markdown_or_fallback(self, doc_key: str, pdf_path: Path) -> tuple[str, str]:
        existing_content_list = self.find_content_list_output(doc_key)
        if existing_content_list:
            return (
                self._markdown_from_content_list(existing_content_list),
                f"Parsed existing MinerU content list: {existing_content_list}",
            )

        existing_markdown = self.find_markdown_output(doc_key)
        if existing_markdown:
            return (
                existing_markdown.read_text(encoding="utf-8"),
                f"Parsed existing MinerU markdown: {existing_markdown}",
            )

        generated_markdown = self._run_mineru_if_available(doc_key, pdf_path)
        generated_content_list = self.find_content_list_output(doc_key)
        if generated_content_list:
            return (
                self._markdown_from_content_list(generated_content_list),
                f"Parsed MinerU content list: {generated_content_list}",
            )

        if generated_markdown:
            return (
                generated_markdown.read_text(encoding="utf-8"),
                f"Parsed MinerU markdown: {generated_markdown}",
            )

        return self._extract_pdf_text(pdf_path), (
            "MinerU command was not available or did not produce Markdown; "
            "used local pypdf page extraction fallback."
        )

    def _markdown_from_content_list(self, content_list_path: Path) -> str:
        payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        by_page: dict[int, list[str]] = defaultdict(list)
        for item in payload:
            page_number = int(item.get("page_idx", 0)) + 1
            block = self._content_block(item)
            if block:
                by_page[page_number].append(block)

        markdown_pages = []
        for page_number in sorted(by_page):
            markdown_pages.append(
                f"<!-- page: {page_number} -->\n" + "\n\n".join(by_page[page_number])
            )
        return "\n\n".join(markdown_pages)

    def _content_block(self, item: dict) -> str:
        """Render one MinerU content-list item as Markdown.

        Text/headings keep their level; tables are flattened to pipe-separated
        rows (so the cell text is searchable and citable); images contribute
        their caption/footnote text. Anything else is skipped.
        """
        text = str(item.get("text") or "").strip()
        if text:
            level = item.get("text_level")
            if isinstance(level, int) and 1 <= level <= 6:
                return f"{'#' * level} {text}"
            return text

        item_type = item.get("type")
        if item_type == "table" or item.get("table_body"):
            return self._table_block(item)
        if item_type == "image" or item.get("img_path"):
            return self._image_block(item)
        return ""

    @staticmethod
    def _join(values: object) -> str:
        if isinstance(values, list):
            return " ".join(str(value).strip() for value in values if str(value).strip())
        return str(values or "").strip()

    def _table_block(self, item: dict) -> str:
        parts: list[str] = []
        caption = self._join(item.get("table_caption"))
        if caption:
            parts.append(f"**表格：{caption}**")
        body = self._html_to_text_or_empty(item.get("table_body"))
        if body:
            parts.append(body)
        footnote = self._join(item.get("table_footnote"))
        if footnote:
            parts.append(f"（表格附註：{footnote}）")
        return "\n".join(parts).strip()

    def _image_block(self, item: dict) -> str:
        caption = self._join(item.get("image_caption"))
        footnote = self._join(item.get("image_footnote"))
        parts = [f"[圖片] {caption}" if caption else "[圖片]"]
        if footnote:
            parts.append(f"（圖片附註：{footnote}）")
        return " ".join(parts).strip()

    @staticmethod
    def _html_to_text_or_empty(body: object) -> str:
        html = str(body or "").strip()
        return _html_table_to_text(html) if html else ""

    def _run_mineru_if_available(self, doc_key: str, pdf_path: Path) -> Path | None:
        settings = get_settings()
        command = settings.mineru_command
        if not shutil.which(command):
            return None

        output_dir = Path(settings.upload_dir) / "mineru" / doc_key
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                command,
                "-p",
                str(pdf_path),
                "-o",
                str(output_dir),
                "-b",
                settings.mineru_backend,
                "-m",
                settings.mineru_method,
                "-f",
                "true" if settings.mineru_formula else "false",
                "-t",
                "true" if settings.mineru_table else "false",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=settings.mineru_timeout_seconds,
        )
        return self.find_markdown_output(doc_key)

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        reader = PdfReader(str(pdf_path))
        markdown_pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            content = text.strip() or f"No extractable text found on page {index}."
            markdown_pages.append(f"<!-- page: {index} -->\n# Page {index}\n\n{content}")
        return "\n\n".join(markdown_pages)
