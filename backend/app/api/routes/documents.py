from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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


class EvidenceRequest(BaseModel):
    answer: str = Field(default="", max_length=20000)
    query: str = Field(default="", max_length=2000)


class EvidenceBlockOut(BaseModel):
    index: int
    type: str
    text: str
    bbox: list[float]  # normalised [x0, y0, x1, y1] in 0..1 of page width/height
    matched: bool
    score: float


class PageEvidenceOut(BaseModel):
    document_id: str
    page_number: int
    page_width: float
    page_height: float
    has_regions: bool  # false when no MinerU middle.json exists for this document
    blocks: list[EvidenceBlockOut]


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


@router.get("/{document_id}/pages/{page_number}/image")
def get_page_image(
    document_id: str,
    page_number: int,
    principal: Principal | None = CURRENT_PRINCIPAL,
) -> FileResponse:
    """The cited PDF page rendered to a PNG (cached), for the evidence overlay."""
    from app.services.page_evidence import render_page_png

    document = DocumentService().get_document(document_id, principal)
    png = render_page_png(document.stored_path, page_number)
    if png is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page image is unavailable for this document.",
        )
    return FileResponse(png, media_type="image/png")


@router.post("/{document_id}/pages/{page_number}/evidence", response_model=PageEvidenceOut)
def get_page_evidence(
    document_id: str,
    page_number: int,
    request: EvidenceRequest,
    principal: Principal | None = CURRENT_PRINCIPAL,
) -> PageEvidenceOut:
    """Text-region blocks for a page, with the ones the answer used flagged
    ``matched``. Returns ``has_regions=false`` (empty blocks) when the document
    has no MinerU region data (demo doc / pypdf fallback)."""
    from app.services.page_evidence import load_page_blocks, score_blocks

    document = DocumentService().get_document(document_id, principal)
    evidence = load_page_blocks(document_id, document.created_at, page_number)
    if evidence is None:
        return PageEvidenceOut(
            document_id=document_id,
            page_number=page_number,
            page_width=0.0,
            page_height=0.0,
            has_regions=False,
            blocks=[],
        )
    score_blocks(evidence, request.answer, request.query)
    return PageEvidenceOut(
        document_id=document_id,
        page_number=page_number,
        page_width=evidence.page_width,
        page_height=evidence.page_height,
        has_regions=True,
        blocks=[
            EvidenceBlockOut(
                index=b.index,
                type=b.type,
                text=b.text,
                bbox=b.bbox,
                matched=b.matched,
                score=b.score,
            )
            for b in evidence.blocks
        ],
    )


@router.delete("/{document_id}", response_model=IngestionJobResponse)
def delete_document(
    document_id: str, principal: Principal | None = CURRENT_PRINCIPAL
) -> IngestionJobResponse:
    return DocumentService().delete_document(document_id, principal)
