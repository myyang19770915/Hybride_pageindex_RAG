from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, status

from app.schemas.documents import DocumentDetail, IngestionJobDetail, IngestionStatus
from app.services.markdown_parser import MarkdownPageParser
from app.services.mineru import MineruClient, storage_key
from app.services.summary import SummaryService


def now_utc() -> datetime:
    return datetime.now(UTC)


class IngestionService:
    def __init__(
        self,
        documents: dict[str, DocumentDetail],
        jobs: dict[str, IngestionJobDetail],
        pages: dict[str, list] | None = None,
        mineru_client: MineruClient | None = None,
        parser: MarkdownPageParser | None = None,
        summary_service: SummaryService | None = None,
    ) -> None:
        self.documents = documents
        self.jobs = jobs
        self.pages = pages
        self.mineru_client = mineru_client or MineruClient()
        self.parser = parser or MarkdownPageParser()
        self.summary_service = summary_service or SummaryService()

    def process_job(self, job_id: str) -> IngestionJobDetail:
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

        document = self.documents.get(job.document_id)
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

        job.status = IngestionStatus.processing
        job.message = "Running MinerU markdown ingestion."
        job.updated_at = now_utc()
        document.status = IngestionStatus.processing

        try:
            if not document.stored_path:
                raise ValueError("Document has no stored source path.")
            markdown, source_message = self.mineru_client.read_markdown_or_fallback(
                storage_key(document.document_id, document.created_at),
                Path(document.stored_path),
            )
            parsed = self.parser.parse(markdown)
            parsed.toc = self.summary_service.summarize_toc(parsed.toc, parsed.pages)
            document.total_pages = parsed.total_pages
            document.toc = parsed.toc
            if self.pages is not None:
                self.pages[document.document_id] = parsed.pages
            document.status = IngestionStatus.completed
            job.status = IngestionStatus.completed
            job.message = source_message
            job.updated_at = now_utc()
        except Exception as exc:
            document.status = IngestionStatus.failed
            job.status = IngestionStatus.failed
            job.message = str(exc)
            job.updated_at = now_utc()

        return job
