import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.services.mineru_api import MineruApiClient, MineruApiError

router = APIRouter()
PDF_UPLOAD = File(...)


@router.get("/status")
def mineru_status() -> dict:
    return MineruApiClient().status()


@router.post("/parse")
async def mineru_parse(
    file: UploadFile = PDF_UPLOAD,
    backend: str = Form("pipeline"),
    parse_method: str = Form("auto"),
    lang: str = Form("ch"),
    formula_enable: bool = Form(True),
    table_enable: bool = Form(True),
    image_analysis: bool = Form(True),
    effort: str = Form("medium"),
    start_page_id: int = Form(0),
    end_page_id: int = Form(99999),
    server_url: str | None = Form(None),
) -> dict:
    """Parse one uploaded file via MinerU's FastAPI with the chosen parameters."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty."
        )

    params = {
        "backend": backend,
        "parse_method": parse_method,
        "lang_list": lang,
        "formula_enable": formula_enable,
        "table_enable": table_enable,
        "image_analysis": image_analysis,
        "effort": effort,
        "start_page_id": start_page_id,
        "end_page_id": end_page_id,
        "server_url": server_url or None,
    }
    started = time.monotonic()
    try:
        result = MineruApiClient().parse(file_bytes, file.filename or "upload.pdf", params)
    except MineruApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result
