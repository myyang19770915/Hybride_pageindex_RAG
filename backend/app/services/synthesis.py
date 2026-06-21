import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.schemas.documents import DocumentDetail, DocumentPage

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s+|\n+")

_SYSTEM_PROMPT = (
    "你是企業知識庫問答助理。只根據提供的文件頁面內容回答問題，"
    "使用繁體中文，並在引用時標註頁碼，例如「（第 16 頁）」。"
    "若內容不足以回答，請明確說明資料不足，不要編造未提供的資訊。"
)


@dataclass
class SynthesisResult:
    answer: str
    method: str  # "agno" | "llm" | "extractive"


class AnswerSynthesisService:
    """Generates the final answer from selected pages.

    Generation order: Agno agent runtime (when enabled) -> direct LiteLLM call
    -> extractive fallback. Every layer degrades gracefully so the service stays
    usable without an LLM endpoint (e.g. tests and offline runs).
    """

    def synthesize(
        self, query: str, document: DocumentDetail, pages: list[DocumentPage]
    ) -> SynthesisResult:
        if not pages:
            return SynthesisResult(
                answer=f"已找到文件 {document.file_name}，但目前沒有可引用的逐頁內文。",
                method="extractive",
            )

        context = self._build_context(pages)
        settings = get_settings()

        if settings.use_agno:
            try:
                return SynthesisResult(self._synthesize_agno(query, context), "agno")
            except Exception:
                pass

        try:
            return SynthesisResult(self._synthesize_remote(query, context), "llm")
        except Exception:
            return SynthesisResult(
                self._synthesize_extractive(query, document, context), "extractive"
            )

    def _build_context(self, pages: list[DocumentPage]) -> str:
        return "\n\n".join(
            f"[第 {page.page_number} 頁]\n{page.page_content.strip()}" for page in pages
        )

    def _user_prompt(self, query: str, context: str) -> str:
        return (
            f"使用者問題：{query}\n\n"
            f"可參考的文件頁面內容：\n{context[:6000]}\n\n"
            "請依據上述內容，用繁體中文給出精確、可追溯的回答，並標註引用頁碼。"
        )

    def _synthesize_agno(self, query: str, context: str) -> str:
        from agno.agent import Agent
        from agno.models.litellm import LiteLLMOpenAI

        settings = get_settings()
        model = LiteLLMOpenAI(
            id=settings.model_id,
            api_key=settings.litellm_api_key,
            base_url=settings.litellm_base_url,
        )
        agent = Agent(
            model=model,
            instructions=[_SYSTEM_PROMPT],
            markdown=False,
            telemetry=False,
        )
        output = agent.run(self._user_prompt(query, context))
        content = (getattr(output, "content", None) or "").strip()
        if not content:
            raise ValueError("Empty answer from Agno agent.")
        return content

    def _synthesize_remote(self, query: str, context: str) -> str:
        settings = get_settings()
        response = httpx.post(
            f"{settings.litellm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
            json={
                "model": settings.model_id,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": self._user_prompt(query, context)},
                ],
                "temperature": 0,
                # qwen35-27b is a reasoning model; leave room for reasoning + answer.
                "max_tokens": settings.synthesis_max_tokens,
            },
            timeout=settings.synthesis_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]
        content = (message.get("content") or "").strip()
        if not content:
            raise ValueError("Empty answer from LLM.")
        return content

    def _synthesize_extractive(
        self, query: str, document: DocumentDetail, context: str
    ) -> str:
        return (
            f"根據 {document.file_name} 的原始頁面內容，針對「{query}」可先參考以下片段：\n\n"
            f"{context[:1800]}"
        )
