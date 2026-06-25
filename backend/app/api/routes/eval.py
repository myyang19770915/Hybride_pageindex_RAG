"""Eval API: run the RAG golden-set evaluation from the UI.

Exposes the backend/eval harness over HTTP. The run endpoint can override global
retrieval settings (reranker, node_hits) for the duration of one run so the UI can
A/B configurations. An in-process lock serialises runs; settings are restored in a
finally block. WARNING: while a run is in flight the overrides are process-global,
so concurrent normal queries briefly see the eval's config — acceptable for a
single-operator dev/eval tool.
"""

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.schemas.query import RetrievalStrategy

logger = logging.getLogger(__name__)
router = APIRouter()

_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden_set.jsonl"
_run_lock = threading.Lock()
_gen_lock = threading.Lock()


class GoldenItemOut(BaseModel):
    id: str
    query: str
    file_name: str
    page_number: int
    expected_answer: str = ""


class GenerateConfig(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)  # empty = all completed documents
    per_doc: int = Field(default=3, ge=1, le=50)  # pages sampled per document
    questions_per_page: int = Field(default=1, ge=1, le=10)
    min_chars: int = Field(default=200, ge=0, le=5000)  # skip thinner pages
    append: bool = True  # append to the golden set vs. overwrite it


class GenerateResult(BaseModel):
    added: int  # new (deduped) items written
    total: int  # golden-set size after the write
    items: list[GoldenItemOut]  # the newly added items


class EvalConfig(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    strategy: RetrievalStrategy | None = None
    rerank_provider: str | None = None  # bm25 | cohere
    cohere_model: str | None = None
    node_hits: int | None = Field(default=None, ge=1, le=100)
    limit: int = Field(default=0, ge=0)  # 0 = all


class EvalItemResult(BaseModel):
    id: str
    query: str
    document_id: str
    file_name: str
    page_number: int
    doc_hit: bool
    page_hit: bool
    rank: int | None
    status: str
    citations: list[tuple[str, int, int]]


class EvalRunResult(BaseModel):
    n: int
    settings: dict
    metrics: dict
    items: list[EvalItemResult]


@contextmanager
def _settings_override(overrides: dict[str, str | None]):
    """Temporarily set env-backed settings, then restore. Drops the settings cache."""
    prior = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is not None:
                os.environ[key] = str(value)
        get_settings.cache_clear()
        yield
    finally:
        for key, old in prior.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        get_settings.cache_clear()


@router.get("/golden", response_model=list[GoldenItemOut])
def list_golden() -> list[GoldenItemOut]:
    """The labelled golden questions backing the eval."""
    import json

    if not _GOLDEN_PATH.exists():
        return []
    items: list[GoldenItemOut] = []
    with _GOLDEN_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            items.append(
                GoldenItemOut(
                    id=raw["id"],
                    query=raw["query"],
                    file_name=raw.get("file_name", ""),
                    page_number=int(raw["page_number"]),
                    expected_answer=raw.get("expected_answer", ""),
                )
            )
    return items


def _read_golden_raw() -> list[dict]:
    """Raw golden records (all fields), in file order. Empty if the file is absent."""
    import json

    if not _GOLDEN_PATH.exists():
        return []
    records: list[dict] = []
    with _GOLDEN_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@router.post("/generate", response_model=GenerateResult)
def generate_golden(config: GenerateConfig) -> GenerateResult:
    """Generate golden Q&A items from the corpus via the LLM and write them to the set.

    Each sampled page becomes the ground-truth source for the questions written from
    it. Synchronous and potentially slow (one LLM call per sampled page); a lock
    serialises generation so two operators can't interleave writes to the file.
    """
    import json

    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A golden-set generation is already in progress.",
        )
    try:
        from eval.generate_golden import generate_golden_items

        from app.services.documents import DocumentService

        service = DocumentService()
        # on_progress is intentionally None: printing CJK to a cp950 Windows stdout
        # crashes the request (same hazard as the eval-run path).
        generated = generate_golden_items(
            service,
            config.doc_ids or None,
            config.per_doc,
            config.min_chars,
            config.questions_per_page,
            on_progress=None,
        )

        existing = [] if not config.append else _read_golden_raw()
        seen_ids = {r["id"] for r in existing}
        fresh = [it for it in generated if it["id"] not in seen_ids]

        if generated:  # only touch the file when the LLM actually produced something
            _GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            records = existing + fresh if config.append else generated
            with _GOLDEN_PATH.open("w", encoding="utf-8") as fh:
                for record in records:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        added = fresh if config.append else generated
        total = len(_read_golden_raw())
        return GenerateResult(
            added=len(added),
            total=total,
            items=[
                GoldenItemOut(
                    id=it["id"],
                    query=it["query"],
                    file_name=it.get("file_name", ""),
                    page_number=int(it["page_number"]),
                    expected_answer=it.get("expected_answer", ""),
                )
                for it in added
            ],
        )
    finally:
        _gen_lock.release()


@router.post("/run", response_model=EvalRunResult)
def run_eval(config: EvalConfig) -> EvalRunResult:
    """Run the golden set through retrieval (no synthesis) and return metrics."""
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An eval run is already in progress."
        )
    try:
        from eval.metrics import aggregate
        from eval.run_eval import evaluate, load_golden, settings_snapshot

        if not _GOLDEN_PATH.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Golden set not found."
            )

        overrides = {
            "RERANK_PROVIDER": config.rerank_provider,
            "COHERE_RERANK_MODEL": config.cohere_model,
            "RETRIEVAL_NODE_HITS": config.node_hits,
        }
        with _settings_override(overrides):
            items = load_golden(_GOLDEN_PATH)
            if config.limit:
                items = items[: config.limit]
            if not items:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Golden set is empty."
                )
            strategy = RetrievalStrategy(config.strategy) if config.strategy else None
            outcomes = evaluate(items, config.top_k, strategy, judge=False, progress=False)
            settings = settings_snapshot()
            agg = aggregate(outcomes)

        return EvalRunResult(
            n=agg.n,
            settings=settings,
            metrics={
                "doc_hit_rate": agg.doc_hit_rate,
                "page_hit_rate": agg.page_hit_rate,
                "mrr": agg.mrr,
                "answered_rate": agg.answered_rate,
                "mean_latency_ms": agg.mean_latency_ms,
                "per_status": agg.per_status,
            },
            items=[
                EvalItemResult(
                    id=o.item.id,
                    query=o.item.query,
                    document_id=o.item.document_id,
                    file_name=o.item.file_name,
                    page_number=o.item.page_number,
                    doc_hit=o.doc_hit,
                    page_hit=o.page_hit,
                    rank=o.rank,
                    status=o.status,
                    citations=[(c.document_id, c.start_page, c.end_page) for c in o.citations],
                )
                for o in outcomes
            ],
        )
    finally:
        _run_lock.release()
