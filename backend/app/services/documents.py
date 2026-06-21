import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import Principal
from app.models import KmDocument, KmDocumentPage, KmIngestionJob
from app.repositories.documents import DocumentRepository
from app.schemas.documents import (
    DocumentDetail,
    DocumentListItem,
    DocumentPage,
    IngestionJobDetail,
    IngestionJobResponse,
    IngestionStatus,
    TocNode,
)
from app.schemas.ingestion import ParsedPage
from app.services.ingestion import IngestionService
from app.services.mineru import storage_key
from app.services.vector_store import VectorStoreService

_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_DOCUMENT_NOT_FOUND = "Document not found."
_JOB_NOT_FOUND = "Job not found."


@dataclass
class StoredUpload:
    path: Path
    content_hash: str
    size_bytes: int


_documents: dict[str, DocumentDetail] = {}
_jobs: dict[str, IngestionJobDetail] = {}
_document_pages: dict[str, list[ParsedPage]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_filename(filename: str | None) -> str:
    if not filename:
        return "upload.pdf"
    return _SAFE_FILENAME_PATTERN.sub("_", Path(filename).name).strip("._") or "upload.pdf"


async def _store_upload(
    document_id: str, file: UploadFile, created_at: datetime
) -> StoredUpload:
    filename = _safe_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF uploads are supported in the first ingestion phase.",
        )

    settings = get_settings()
    # Date-partitioned: uploads/source/YYYY-MM-DD/{document_id}/{filename}
    target_dir = Path(settings.upload_dir) / "source" / storage_key(document_id, created_at)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    digest = hashlib.sha256()
    size_bytes = 0
    with target_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
            output.write(chunk)

    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF is empty.",
        )

    return StoredUpload(path=target_path, content_hash=digest.hexdigest(), size_bytes=size_bytes)


def _demo_document() -> DocumentDetail:
    return DocumentDetail(
        document_id="doc_demo_txc",
        file_name="TXC_SOP_2026.pdf",
        version="demo",
        total_pages=30,
        status=IngestionStatus.completed,
        created_at=_now(),
        content_hash="demo",
        toc=[
            TocNode(
                node_id="N3",
                heading="3. 常見異常排除 (Troubleshooting)",
                start_page=16,
                end_page=30,
                summary="針對頻率偏移、真空度不足等異常的排查步驟。",
            )
        ],
    )


def _demo_pages() -> list[DocumentPage]:
    return [
        DocumentPage(
            document_id="doc_demo_txc",
            page_number=16,
            page_content=(
                "### 3.1 真空度不足異常排查\n"
                "當設備腔體真空度低於 1.0E-3 Pa 時，請檢查 O-ring、"
                "分子泵轉速與相關異常紀錄。"
            ),
        ),
        DocumentPage(
            document_id="doc_demo_txc",
            page_number=17,
            page_content=(
                "### 3.1.2 分子泵驅動器錯誤碼\n"
                "ERR_01: 驅動器過熱，請確認冷卻水流量大於 2.0 L/min。"
            ),
        ),
    ]


def _document_from_model(document: KmDocument) -> DocumentDetail:
    toc_payload = document.json_tree.get("toc", []) if document.json_tree else []
    return DocumentDetail(
        document_id=document.document_id,
        file_name=document.file_name,
        version=document.version,
        total_pages=document.total_pages,
        status=IngestionStatus(document.status),
        created_at=document.created_at or _now(),
        content_hash=document.content_hash,
        stored_path=document.stored_path,
        owner=document.owner,
        is_latest=document.is_latest,
        toc=[TocNode.model_validate(node) for node in toc_payload],
    )


def _job_from_model(job: KmIngestionJob) -> IngestionJobDetail:
    return IngestionJobDetail(
        job_id=job.job_id,
        document_id=job.document_id or "",
        status=IngestionStatus(job.status),
        message=job.message,
        file_name=job.file_name,
        content_hash=job.content_hash,
        created_at=job.created_at or _now(),
        updated_at=job.updated_at or _now(),
    )


def _document_to_list_item(document: DocumentDetail) -> DocumentListItem:
    return DocumentListItem(
        document_id=document.document_id,
        file_name=document.file_name,
        version=document.version,
        total_pages=document.total_pages,
        status=document.status,
        created_at=document.created_at,
        content_hash=document.content_hash,
        owner=document.owner,
        is_latest=document.is_latest,
    )


class DocumentService:
    """Local document service.

    This stores uploads and job state in-process for the PoC. PostgreSQL repository
    boundaries are already present, so this can move to durable persistence without
    changing the API contract.
    """

    @staticmethod
    def _can_access(
        document: DocumentDetail | DocumentListItem, principal: Principal | None
    ) -> bool:
        if principal is None or principal.is_admin:
            return True
        return document.owner in (None, principal.username)

    def _scoped_documents(self, owner: str | None) -> list[DocumentDetail]:
        """Active (non-deleted) documents visible within an owner scope."""
        if get_settings().use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                docs = [_document_from_model(model) for model in repo.list_documents()]
        else:
            docs = list(_documents.values())
        return [
            doc
            for doc in docs
            if doc.status != IngestionStatus.deleted and doc.owner == owner
        ]

    def _demote_previous_latest(self, file_name: str, owner: str | None) -> None:
        if get_settings().use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                repo.demote_latest(file_name, owner)
                repo.commit()
        else:
            for doc in _documents.values():
                if doc.file_name == file_name and doc.owner == owner:
                    doc.is_latest = False

    async def enqueue_upload(
        self, file: UploadFile, principal: Principal | None = None
    ) -> IngestionJobResponse:
        document_id = f"doc_{uuid4().hex[:12]}"
        job_id = f"job_{uuid4().hex[:12]}"
        created_at = _now()
        stored = await _store_upload(document_id, file, created_at)
        filename = _safe_filename(file.filename)
        owner = principal.username if principal else None

        scoped = self._scoped_documents(owner)
        duplicate = next(
            (doc for doc in scoped if doc.content_hash == stored.content_hash), None
        )
        if duplicate is not None:
            # Identical content already ingested in this scope: drop the redundant
            # copy and point the caller at the existing document.
            shutil.rmtree(Path(stored.path).parent, ignore_errors=True)
            return IngestionJobResponse(
                job_id=job_id,
                document_id=duplicate.document_id,
                status=duplicate.status,
                message=(
                    f"Duplicate upload; reusing existing document {duplicate.document_id} "
                    f"(version {duplicate.version})."
                ),
            )

        prior_versions = [doc for doc in scoped if doc.file_name == filename]
        version = f"v{len(prior_versions) + 1}"
        if prior_versions:
            self._demote_previous_latest(filename, owner)

        document = DocumentDetail(
            document_id=document_id,
            file_name=filename,
            version=version,
            total_pages=0,
            status=IngestionStatus.queued,
            created_at=created_at,
            content_hash=stored.content_hash,
            stored_path=str(stored.path),
            owner=owner,
            is_latest=True,
            toc=[],
        )
        job = IngestionJobDetail(
            job_id=job_id,
            document_id=document_id,
            status=IngestionStatus.queued,
            message=f"Queued {filename} for MinerU parsing.",
            file_name=filename,
            content_hash=stored.content_hash,
            created_at=created_at,
            updated_at=created_at,
        )
        _documents[document_id] = document
        _jobs[job_id] = job
        if get_settings().use_database:
            self._persist_new_upload(document, job)

        message = job.message
        if get_settings().use_background_worker:
            from app.services.worker import get_job_queue

            get_job_queue().submit(job_id)
            message = f"Queued {filename} for background ingestion."

        return IngestionJobResponse(
            job_id=job_id,
            document_id=document_id,
            status=IngestionStatus.queued,
            message=message,
        )

    def list_documents(
        self, principal: Principal | None = None, latest_only: bool = False
    ) -> list[DocumentListItem]:
        if get_settings().use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                documents = [_document_from_model(document) for document in repo.list_documents()]
                items = [
                    _document_to_list_item(document)
                    for document in [_demo_document(), *documents]
                ]
        else:
            documents = [_demo_document(), *_documents.values()]
            items = [_document_to_list_item(document) for document in documents]

        accessible = [item for item in items if self._can_access(item, principal)]
        if latest_only:
            accessible = [
                item
                for item in accessible
                if item.is_latest and item.status != IngestionStatus.deleted
            ]
        return accessible

    def list_versions(
        self, document_id: str, principal: Principal | None = None
    ) -> list[DocumentListItem]:
        """All versions sharing a document's file name within its owner scope."""
        document = self.get_document(document_id, principal)
        versions = [
            _document_to_list_item(doc)
            for doc in self._scoped_documents(document.owner)
            if doc.file_name == document.file_name
        ]
        versions.sort(key=lambda item: item.version)
        return versions

    def get_document(
        self, document_id: str, principal: Principal | None = None
    ) -> DocumentDetail:
        if document_id == "doc_demo_txc":
            return _demo_document()
        if get_settings().use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                document = repo.get_document(document_id)
                if not document:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=_DOCUMENT_NOT_FOUND,
                    )
                detail = _document_from_model(document)
        elif document_id not in _documents:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_DOCUMENT_NOT_FOUND)
        else:
            detail = _documents[document_id]

        if not self._can_access(detail, principal):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_DOCUMENT_NOT_FOUND)
        return detail

    def get_job(self, job_id: str) -> IngestionJobDetail:
        if get_settings().use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                job = repo.get_job(job_id)
                if not job:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=_JOB_NOT_FOUND,
                    )
                return _job_from_model(job)

        if job_id not in _jobs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND)
        return _jobs[job_id]

    def process_job(self, job_id: str) -> IngestionJobDetail:
        if get_settings().use_database:
            return self._process_persisted_job(job_id)

        job = IngestionService(_documents, _jobs, pages=_document_pages).process_job(job_id)
        if get_settings().use_qdrant and job.status == IngestionStatus.completed:
            VectorStoreService().upsert_document(self.get_document(job.document_id))
        return job

    def list_pages(
        self, document_id: str, principal: Principal | None = None
    ) -> list[DocumentPage]:
        if document_id == "doc_demo_txc":
            return _demo_pages()

        if get_settings().use_database:
            self.get_document(document_id, principal)
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                return [
                    DocumentPage(
                        document_id=document_id,
                        page_number=page.page_number,
                        page_content=page.page_content,
                    )
                    for page in repo.list_pages(document_id)
                ]

        self.get_document(document_id, principal)
        pages = _document_pages.get(document_id, [])
        return [
            DocumentPage(
                document_id=document_id,
                page_number=page.page_number,
                page_content=page.content,
            )
            for page in pages
        ]

    def delete_document(
        self, document_id: str, principal: Principal | None = None
    ) -> IngestionJobResponse:
        if document_id == "doc_demo_txc":
            return IngestionJobResponse(
                job_id=f"job_{uuid4().hex[:12]}",
                document_id=document_id,
                status=IngestionStatus.deleted,
                message="Demo document cannot be physically deleted.",
            )

        # Raises 404 when the document is missing or not owned by the caller.
        document = self.get_document(document_id, principal)

        settings = get_settings()
        cleaned: list[str] = []

        if settings.use_database:
            with SessionLocal() as session:
                repo = DocumentRepository(session)
                repo.delete_document(document_id)
                repo.commit()
            cleaned.append("PostgreSQL")

        _documents.pop(document_id, None)
        _document_pages.pop(document_id, None)

        if settings.use_qdrant:
            try:
                VectorStoreService().delete_document(document_id)
                cleaned.append("Qdrant")
            except Exception as exc:  # pragma: no cover - depends on live Qdrant
                cleaned.append(f"Qdrant(failed: {exc})")

        if self._cleanup_source_files(document_id, document.created_at):
            cleaned.append("files")

        scope = ", ".join(cleaned) if cleaned else "in-memory state"
        return IngestionJobResponse(
            job_id=f"job_{uuid4().hex[:12]}",
            document_id=document_id,
            status=IngestionStatus.deleted,
            message=f"Deleted document and cleaned: {scope}.",
        )

    def _cleanup_source_files(self, document_id: str, created_at: datetime) -> bool:
        upload_dir = Path(get_settings().upload_dir)
        removed = False
        # Date-partitioned dirs, plus legacy flat dirs for docs created before the
        # date layout existed.
        keys = (storage_key(document_id, created_at), document_id)
        for sub_dir in ("source", "mineru"):
            for key in keys:
                target = upload_dir / sub_dir / key
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                    removed = True
        return removed

    def _persist_new_upload(self, document: DocumentDetail, job: IngestionJobDetail) -> None:
        with SessionLocal() as session:
            repo = DocumentRepository(session)
            repo.add_document(
                KmDocument(
                    document_id=document.document_id,
                    file_name=document.file_name,
                    version=document.version,
                    content_hash=document.content_hash or "",
                    total_pages=document.total_pages,
                    json_tree={"toc": [node.model_dump() for node in document.toc]},
                    status=document.status.value,
                    stored_path=document.stored_path,
                    owner=document.owner,
                    is_latest=document.is_latest,
                )
            )
            repo.add_job(
                KmIngestionJob(
                    job_id=job.job_id,
                    document_id=job.document_id,
                    status=job.status.value,
                    message=job.message,
                    file_name=job.file_name,
                    content_hash=job.content_hash,
                )
            )
            repo.commit()

    def _process_persisted_job(self, job_id: str) -> IngestionJobDetail:
        with SessionLocal() as session:
            repo = DocumentRepository(session)
            job_model = repo.get_job(job_id)
            if not job_model or not job_model.document_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND)
            document_model = repo.get_document(job_model.document_id)
            if not document_model:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=_DOCUMENT_NOT_FOUND,
                )

            document = _document_from_model(document_model)
            job = _job_from_model(job_model)
            pages: dict[str, list[ParsedPage]] = {}
            processed_job = IngestionService(
                {document.document_id: document},
                {job.job_id: job},
                pages=pages,
            ).process_job(job_id)

            document_model.total_pages = document.total_pages
            document_model.json_tree = {"toc": [node.model_dump() for node in document.toc]}
            document_model.status = document.status.value
            job_model.status = processed_job.status.value
            job_model.message = processed_job.message

            repo.replace_pages(
                document.document_id,
                [
                    KmDocumentPage(
                        document_id=document.document_id,
                        page_number=page.page_number,
                        page_content=page.content,
                    )
                    for page in pages.get(document.document_id, [])
                ],
            )
            repo.commit()

        if get_settings().use_qdrant and processed_job.status == IngestionStatus.completed:
            VectorStoreService().upsert_document(self.get_document(processed_job.document_id))

        return self.get_job(job_id)
