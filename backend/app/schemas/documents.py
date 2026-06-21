from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class IngestionStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    deleted = "deleted"


class TocNode(BaseModel):
    node_id: str
    heading: str
    start_page: int
    end_page: int
    summary: str
    children: list["TocNode"] = Field(default_factory=list)


class IngestionJobResponse(BaseModel):
    job_id: str
    document_id: str
    status: IngestionStatus
    message: str | None = None


class IngestionJobDetail(IngestionJobResponse):
    file_name: str | None = None
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    document_id: str
    file_name: str
    version: str
    total_pages: int
    status: IngestionStatus
    created_at: datetime
    content_hash: str | None = None
    owner: str | None = None
    is_latest: bool = True


class DocumentDetail(DocumentListItem):
    toc: list[TocNode] = Field(default_factory=list)
    stored_path: str | None = None


class DocumentPage(BaseModel):
    document_id: str
    page_number: int
    page_content: str
