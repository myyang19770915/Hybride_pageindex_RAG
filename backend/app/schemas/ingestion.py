from pydantic import BaseModel, Field

from app.schemas.documents import TocNode


class ParsedPage(BaseModel):
    page_number: int
    content: str


class ParsedDocument(BaseModel):
    total_pages: int
    pages: list[ParsedPage]
    toc: list[TocNode] = Field(default_factory=list)
