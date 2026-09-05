import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Client giao tiếp với Local LLM (Ollama: Qwen / Llama) hoặc OpenAI-compatible endpoint.

    Đặc tính cốt lõi:
    - Zero-Cost First: Hỗ trợ Ollama cục bộ hoàn toàn miễn phí ($0 API cost).
    - Graceful Fallback: Nếu endpoint không khả dụng hoặc tắt, tự động trả về None
      để hệ thống chuyển sang Deterministic Heuristic Engine mà không gây lỗi.
    - Hỗ trợ Structured JSON Generation và Agentic Planning.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        enabled: bool | None = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.timeout = timeout if timeout is not None else settings.llm_timeout
        self.enabled = enabled if enabled is not None else settings.use_llm
        self._available: bool | None = None

    def is_available(self, force_refresh: bool = False) -> bool:
        """Kiểm tra xem LLM endpoint có hoạt động hay không bằng health check nhanh (timeout 1.2s)."""
        if not self.enabled:
            return False
        if self._available is not None and not force_refresh:
            return self._available

        try:
            with httpx.Client(timeout=1.2) as client:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                resp = client.get(f"{self.base_url}/models", headers=headers)
                self._available = resp.status_code in (200, 401, 403)
        except Exception:
            self._available = False
        return self._available

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        response_json: bool = False,
    ) -> str | None:
        """Gửi yêu cầu Chat Completion tới endpoint với xử lý ngoại lệ an toàn."""
        if not self.is_available():
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                logger.warning("LLM call returned status %d: %s", resp.status_code, resp.text[:200])
                return None
        except Exception as exc:
            logger.debug("LLM call failed with exception: %s. Falling back.", exc)
            return None

    def generate_plan(self, question: str, mode: str = "qa") -> list[dict[str, Any]] | None:
        """Sinh kế hoạch hành động cấu trúc (Structured Tool Planning) cho Supervisor Agent."""
        system_prompt = (
            "You are an AI Supervisor for an ESG report analysis platform. "
            "Given a user query and mode, generate a JSON object with a 'plan' list of tools to call. "
            "Available tools:\n"
            "- search_document(query: str, top_k: int)\n"
            "- retrieve_evidence(chunk_ids: list[int])\n"
            "- extract_metric(text: str)\n"
            "- score_rubric(pillar: str)\n"
            "- verify_claim(claim: str, excerpt: str)\n\n"
            'Respond strictly with valid JSON: {"plan": [{"tool": "...", "args": {...}}]}'
        )
        user_prompt = f"User Question: '{question}'\nMode: '{mode}'"
        raw = self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_json=True,
        )
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "plan" in parsed and isinstance(parsed["plan"], list):
                return parsed["plan"]
        except Exception:
            pass
        return None

    def verify_grounding(self, claim: str, excerpt: str) -> dict[str, Any] | None:
        """Sử dụng LLM để xác thực xem một khẳng định có thực sự được hỗ trợ bởi trích đoạn hay không."""
        system_prompt = (
            "You are an Evidence Verification Agent. Determine if the Claim is directly supported by the Excerpt. "
            'Respond strictly in JSON: {"supported": true/false, "confidence": float (0.0 to 1.0), "reason": "..."}'
        )
        user_prompt = f"Excerpt:\n{excerpt}\n\nClaim:\n{claim}"
        raw = self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_json=True,
        )
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def synthesize_answer(
        self,
        question: str,
        citations: list[dict[str, Any]],
        rubric_summary: str | None = None,
    ) -> str | None:
        """Tổng hợp câu trả lời chính văn dựa trên bằng chứng đã xác thực, bắt buộc kèm trích dẫn số trang."""
        context_lines = []
        for i, cite in enumerate(citations, 1):
            doc = cite.get("document_name") or cite.get("document_id", "Doc")
            page = cite.get("page", 1)
            excerpt = cite.get("excerpt", "")
            context_lines.append(f"[{i}] [{doc}, trang {page}]: {excerpt}")
        context = "\n".join(context_lines)

        system_prompt = (
            "You are an Evidence-Grounded ESG Analyst. Your task is to answer the question using ONLY "
            "the provided excerpts. Every factual statement MUST cite its source as [Tên tài liệu, trang X]. "
            "Do NOT hallucinate or assume facts not present in the excerpts. If evidence is insufficient, state clearly what is missing."
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Verified Excerpts:\n{context}\n\n"
            f"Rubric Summary:\n{rubric_summary or 'None'}\n\n"
            "Provide a concise, professional answer with explicit page citations."
        )
        return self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
