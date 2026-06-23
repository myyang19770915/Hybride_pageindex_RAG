"""Cohere rerank client (semantic, cross-lingual page reranker).

An alternative to the local BM25 page rerank. BM25 over-ranks the keyword-dense
title/abstract page and underranks tables; a semantic reranker handles zh-Hant
queries over English page text directly.
"""

from __future__ import annotations

import time

import httpx

from app.core.config import get_settings

_ENDPOINT = "https://api.cohere.com/v2/rerank"


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[int]:
    """Return document indices in descending relevance order.

    Raises on misconfiguration or API failure so callers can fall back to BM25.
    Retries once on 429 (trial keys are rate-limited).
    """
    settings = get_settings()
    if not settings.cohere_api_key:
        raise RuntimeError("COHERE_API_KEY not set")
    if not documents:
        return []

    payload = {
        "model": settings.cohere_rerank_model,
        "query": query,
        "documents": documents,
        "top_n": top_n or len(documents),
    }
    headers = {
        "Authorization": f"bearer {settings.cohere_api_key}",
        "content-type": "application/json",
    }

    for attempt in range(2):
        response = httpx.post(_ENDPOINT, headers=headers, json=payload, timeout=30)
        if response.status_code == 429 and attempt == 0:
            time.sleep(2.0)
            continue
        response.raise_for_status()
        results = response.json()["results"]
        return [item["index"] for item in results]
    raise RuntimeError("Cohere rerank rate-limited after retry")
