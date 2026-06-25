"""Page-evidence service: render a cited PDF page and locate the text regions
the answer drew from.

Region geometry comes from MinerU's ``*_middle.json`` (``pdf_info[].para_blocks``
with bbox in the page's ``page_size`` coordinate space). Bboxes are normalised to
0..1 fractions of the page so the frontend can overlay them on a page image
rendered at any scale. The page image itself is rendered from the original
uploaded PDF with ``pypdfium2`` (a MinerU dependency, no new package), cached to
disk. ``score_blocks`` flags which blocks the answer used via character-bigram
overlap, so the modal can highlight only the regions that actually answered.

Everything is read on demand from artifacts already on disk — no database
migration and no re-ingestion of existing documents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.services.mineru import MineruClient, storage_key

# Score at/above which a block is treated as "used by the answer". Tuned for
# character-bigram overlap on CJK text: high enough to avoid lighting up every
# block, low enough to catch paraphrased source sentences.
_MATCH_THRESHOLD = 0.45
_MIN_BLOCK_CHARS = 6


@dataclass
class PageBlock:
    index: int
    type: str
    text: str
    # Normalised [x0, y0, x1, y1] in 0..1 fractions of page width/height.
    bbox: list[float]
    matched: bool = False
    score: float = 0.0


@dataclass
class PageEvidence:
    document_id: str
    page_number: int
    page_width: float
    page_height: float
    blocks: list[PageBlock] = field(default_factory=list)


def _collect_text(node: object) -> str:
    """Recursively gather span text under a MinerU block (lines→spans→content).

    Non-dict/list nodes (and missing keys) recurse to an empty string, so the
    structure walk stays branch-light."""
    parts: list[str] = []
    if isinstance(node, dict):
        for key in ("content", "text"):
            value = node.get(key)
            if isinstance(value, str):
                parts.append(value.strip())
        for key in ("lines", "spans", "blocks"):
            parts.append(_collect_text(node.get(key)))
    elif isinstance(node, list):
        parts.extend(_collect_text(item) for item in node)
    return " ".join(part for part in parts if part).strip()


def _normalize_bbox(bbox: list, width: float, height: float) -> list[float] | None:
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4 and width > 0 and height > 0):
        return None
    x0, y0, x1, y1 = (float(v) for v in bbox)
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))

    def clamp(value: float, span: float) -> float:
        return max(0.0, min(1.0, value / span))

    return [clamp(left, width), clamp(top, height), clamp(right, width), clamp(bottom, height)]


def load_page_blocks(
    document_id: str, created_at: datetime | None, page_number: int
) -> PageEvidence | None:
    """Blocks (normalised bbox + text) for one page, or None when no MinerU
    middle.json exists for the document (e.g. demo doc / pypdf fallback)."""
    middle = MineruClient().find_middle_output(storage_key(document_id, created_at))
    if middle is None:
        return None
    payload = json.loads(middle.read_text(encoding="utf-8"))
    pages = payload.get("pdf_info") or []
    page_idx = page_number - 1
    if not (0 <= page_idx < len(pages)):
        return None

    page = pages[page_idx]
    size = page.get("page_size") or [0, 0]
    width, height = float(size[0] or 0), float(size[1] or 0)

    blocks: list[PageBlock] = []
    for raw in page.get("para_blocks") or []:
        norm = _normalize_bbox(raw.get("bbox") or [], width, height)
        if norm is None:
            continue
        blocks.append(
            PageBlock(
                index=len(blocks),
                type=str(raw.get("type") or "text"),
                text=_collect_text(raw),
                bbox=norm,
            )
        )
    return PageEvidence(
        document_id=document_id,
        page_number=page_number,
        page_width=width,
        page_height=height,
        blocks=blocks,
    )


def _bigrams(text: str) -> set[str]:
    """Character bigrams over alphanumeric/CJK content (whitespace/punct dropped,
    case-folded so English paraphrases like 'Efficient'/'efficient' still match)."""
    chars = [c for c in text.casefold() if c.isalnum()]
    cleaned = "".join(chars)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def score_blocks(evidence: PageEvidence, answer: str, query: str = "") -> PageEvidence:
    """Flag blocks whose text overlaps the answer (and query). Score is the
    fraction of the block's bigrams that appear in the reference text — high when
    the block's content shows up in the answer. The single best block is always
    marked matched when anything overlaps, so the modal is never empty."""
    reference = _bigrams(f"{answer}\n{query}")
    if not reference:
        return evidence

    best_index = -1
    best_score = 0.0
    for block in evidence.blocks:
        block_grams = _bigrams(block.text)
        if len(block.text) < _MIN_BLOCK_CHARS or not block_grams:
            continue
        overlap = len(block_grams & reference) / len(block_grams)
        block.score = round(overlap, 4)
        block.matched = overlap >= _MATCH_THRESHOLD
        if overlap > best_score:
            best_score, best_index = overlap, block.index

    if best_index >= 0 and not any(b.matched for b in evidence.blocks):
        evidence.blocks[best_index].matched = True
    return evidence


def render_page_png(stored_path: str | None, page_number: int, scale: float = 2.0) -> Path | None:
    """Render one page of the source PDF to a cached PNG. Returns the cached path,
    or None when the PDF is missing/unreadable."""
    if not stored_path:
        return None
    pdf_path = Path(stored_path)
    if not pdf_path.exists():
        return None

    # Key the cache by the document's own directory (…/source/DATE/doc_id/file.pdf)
    # so two documents that share a file name don't collide.
    cache_dir = Path(get_settings().upload_dir) / "render" / pdf_path.parent.name / pdf_path.stem
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"p{page_number}@{scale:g}.png"
    if cache_path.exists():
        return cache_path

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page_idx = page_number - 1
        if not (0 <= page_idx < len(pdf)):
            return None
        bitmap = pdf[page_idx].render(scale=scale)
        image = bitmap.to_pil()
        image.save(cache_path, format="PNG")
    finally:
        pdf.close()
    return cache_path
