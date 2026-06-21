import hashlib
import math
import re

import httpx

from app.core.config import get_settings

_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingService:
    def embed(self, text: str) -> list[float]:
        settings = get_settings()
        try:
            return self._embed_remote(text)
        except Exception:
            return self._embed_deterministic(text, settings.qdrant_vector_size)

    def _embed_remote(self, text: str) -> list[float]:
        settings = get_settings()
        response = httpx.post(
            f"{settings.embedding_base_url.rstrip('/')}/embeddings",
            json={
                "model": settings.embedding_model,
                "input": text[: settings.embedding_context_length],
            },
            timeout=settings.embedding_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload["data"][0]["embedding"]
        if len(vector) != settings.qdrant_vector_size:
            return self._resize(vector, settings.qdrant_vector_size)
        return vector

    def _embed_deterministic(self, text: str, size: int) -> list[float]:
        vector = [0.0] * size
        tokens = _TOKEN_PATTERN.findall(text.lower())
        if not tokens:
            tokens = [text.lower()]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % size
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _resize(self, vector: list[float], size: int) -> list[float]:
        if len(vector) > size:
            resized = vector[:size]
        else:
            resized = [*vector, *([0.0] * (size - len(vector)))]
        norm = math.sqrt(sum(value * value for value in resized)) or 1.0
        return [value / norm for value in resized]
