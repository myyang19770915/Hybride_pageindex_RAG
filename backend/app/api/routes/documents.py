from fastapi import APIRouter, Depends, File, UploadFile

from app.core.security import Principal, get_principal
from app.schemas.documents import (
    DocumentDetail,
    DocumentListItem,
    DocumentPage,
    IngestionJobDetail,
    IngestionJobResponse,
)
from app.services.documents import DocumentService

router = APIRouter()
PDF_UPLOAD = File(...)
CURRENT_PRINCIPAL = Depends(get_principal)


@router.post("", response_model=IngestionJobResponse)
async def upload_document(
    file: UploadFile = PDF_UPLOAD,
    principal: Principal | None = CURRENT_PRINCIPAL,
) -> IngestionJobResponse:
    return await DocumentService().enqueue_upload(file, principal)


@router.get("/jobs/{job_id}", response_model=IngestionJobDetail)
def get_ingestion_job(
    job_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> IngestionJobDetail:
    return DocumentService().get_job(job_id)


@router.post("/jobs/{job_id}/process", response_model=IngestionJobDetail)
def process_ingestion_job(
    job_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> IngestionJobDetail:
    return DocumentService().process_job(job_id)


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    latest_only: bool = False,
    principal: Principal | None = CURRENT_PRINCIPAL,
) -> list[DocumentListItem]:
    return DocumentService().list_documents(principal, latest_only=latest_only)


@router.get("/{document_id}/versions", response_model=list[DocumentListItem])
def list_document_versions(
    document_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> list[DocumentListItem]:
    return DocumentService().list_versions(document_id, principal)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> DocumentDetail:
    return DocumentService().get_document(document_id, principal)


@router.get("/{document_id}/pages", response_model=list[DocumentPage])
def list_document_pages(
    document_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> list[DocumentPage]:
    return DocumentService().list_pages(document_id, principal)


@router.delete("/{document_id}", response_model=IngestionJobResponse)
def delete_document(
    document_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> IngestionJobResponse:
    return DocumentService().delete_document(document_id, principal)
