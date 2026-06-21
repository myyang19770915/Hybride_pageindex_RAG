import re

import httpx

from app.core.config import get_settings
from app.schemas.documents import TocNode
from app.schemas.ingestion import ParsedPage

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s+|\n+")


class SummaryService:
    def summarize_toc(self, toc: list[TocNode], pages: list[ParsedPage]) -> list[TocNode]:
        page_text = {page.page_number: page.content for page in pages}
        return [
            node.model_copy(
                update={
                    "summary": self.summarize_node(
                        node,
                        [
                            page_text.get(page_number, "")
                            for page_number in range(node.start_page, node.end_page + 1)
                        ],
                    )
                }
            )
            for node in toc
        ]

    def summarize_node(self, node: TocNode, page_chunks: list[str]) -> str:
        context = "\n\n".join(chunk for chunk in page_chunks if chunk).strip()
        if not context:
            return node.summary

        # LLM summarization is one call per TOC node; on a large tree that dominates
        # ingestion time, so it is opt-in. Extractive summaries are fast and adequate
        # for retrieval ranking.
        if get_settings().llm_toc_summary:
            try:
                return self._summarize_remote(node.heading, context)
            except Exception:
                pass
        return self._summarize_extractive(node.heading, context)

    def _summarize_remote(self, heading: str, context: str) -> str:
        settings = get_settings()
        response = httpx.post(
            f"{settings.litellm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
            json={
                "model": settings.model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是企業知識庫文件摘要器，只根據輸入內容產生繁體中文短摘要。",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"章節標題：{heading}\n\n"
                            f"章節內容：\n{context[:3000]}\n\n"
                            "請輸出 40 字以內摘要，不要加入未提供的資訊。"
                        ),
                    },
                ],
                "temperature": 0,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()
        if not content:
            raise ValueError("Empty summary from LLM.")
        return content

    def _summarize_extractive(self, heading: str, context: str) -> str:
        clean = re.sub(r"\s+", " ", context).strip()
        sentences = [
            sentence.strip() for sentence in _SENTENCE_SPLIT.split(clean) if sentence.strip()
        ]
        if sentences:
            summary = " ".join(sentences[:2])
        else:
            summary = clean[:120]
        return f"{heading}: {summary[:160]}"
