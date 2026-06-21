import re
from dataclasses import dataclass

from app.schemas.documents import TocNode
from app.schemas.ingestion import ParsedDocument, ParsedPage

_PAGE_MARKER_PATTERNS = [
    re.compile(r"^\s*<!--\s*page(?:_idx|_number)?\s*[:=]\s*(\d+)\s*-->\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[PAGE\s*[:=]\s*(\d+)\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*---\s*page\s+(\d+)\s*---\s*$", re.IGNORECASE),
    re.compile(r"^\s*#{1,6}\s*page\s+(\d+)\s*$", re.IGNORECASE),
]
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class HeadingHit:
    level: int
    text: str
    page_number: int


class MarkdownPageParser:
    """Parse MinerU-style Markdown into page content and a first-pass TOC tree."""

    def parse(self, markdown: str) -> ParsedDocument:
        pages = self._split_pages(markdown)
        headings = self._collect_headings(pages)
        total_pages = max((page.page_number for page in pages), default=0)
        toc = self._build_toc(headings, total_pages=total_pages)
        return ParsedDocument(total_pages=total_pages, pages=pages, toc=toc)

    def _split_pages(self, markdown: str) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        current_page = 1
        current_lines: list[str] = []
        saw_marker = False

        for line in markdown.splitlines():
            marker = self._extract_page_marker(line)
            if marker is None:
                current_lines.append(line)
                continue

            saw_marker = True
            if current_lines:
                pages.append(
                    ParsedPage(
                        page_number=current_page,
                        content="\n".join(current_lines).strip(),
                    )
                )
                current_lines = []
            current_page = marker

        if current_lines or not saw_marker:
            pages.append(
                ParsedPage(
                    page_number=current_page,
                    content="\n".join(current_lines).strip(),
                )
            )

        return [page for page in pages if page.content]

    def _extract_page_marker(self, line: str) -> int | None:
        for pattern in _PAGE_MARKER_PATTERNS:
            match = pattern.match(line)
            if match:
                return int(match.group(1))
        return None

    def _collect_headings(self, pages: list[ParsedPage]) -> list[HeadingHit]:
        headings: list[HeadingHit] = []
        for page in pages:
            for line in page.content.splitlines():
                match = _HEADING_PATTERN.match(line)
                if match:
                    headings.append(
                        HeadingHit(
                            level=len(match.group(1)),
                            text=match.group(2).strip(),
                            page_number=page.page_number,
                        )
                    )
        return headings

    def _build_toc(self, headings: list[HeadingHit], total_pages: int) -> list[TocNode]:
        if not headings:
            return [
                TocNode(
                    node_id="N1",
                    heading="全文",
                    start_page=1,
                    end_page=max(total_pages, 1),
                    summary="MinerU 解析後尚未偵測到 Markdown 標題階層。",
                )
            ]

        nodes: list[TocNode] = []
        for index, heading in enumerate(headings):
            next_heading = headings[index + 1] if index + 1 < len(headings) else None
            if next_heading is None:
                # Last heading runs to the end of the document.
                end_page = total_pages
            elif next_heading.page_number > heading.page_number:
                # Section ends on the page before the next heading starts.
                end_page = next_heading.page_number - 1
            else:
                # Next heading shares this page: this node is confined to its own page.
                end_page = heading.page_number
            nodes.append(
                TocNode(
                    node_id=f"N{index + 1}",
                    heading=heading.text,
                    start_page=heading.page_number,
                    end_page=max(heading.page_number, end_page),
                    summary=f"{heading.text}，第 {heading.page_number} 頁起。",
                )
            )
        return nodes
