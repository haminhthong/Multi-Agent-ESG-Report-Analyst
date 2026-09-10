import json
import logging
import re
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
    - Chỉ hỗ trợ tổng hợp câu trả lời và kiểm tra grounding khi được bật.
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
        except Exception:  # noqa: BLE001 - optional local LLM availability probe
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
        except Exception as exc:  # noqa: BLE001 - optional LLM request boundary
            logger.debug("LLM call failed with exception: %s. Falling back.", exc)
            return None

    def verify_grounding(self, claim: str, evidence_text: str) -> bool:
        """NLI-style verification: kiểm tra xem claim có được hỗ trợ trực tiếp bởi evidence hay không."""
        if not self.is_available():
            return True
        system_prompt = (
            "You are an audit verification engine. Determine whether the Claim is strictly supported by the Evidence.\n"
            'Answer ONLY with a JSON object: {"supported": true} or {"supported": false}.'
        )
        user_prompt = f"Evidence:\n{evidence_text}\n\nClaim:\n{claim}"
        response = self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_json=True,
        )
        if response:
            try:
                data = json.loads(response)
                return bool(data.get("supported", True))
            except (TypeError, ValueError, json.JSONDecodeError):
                return "false" not in response.lower()
        return True

    def synthesize_answer(
        self,
        question: str,
        citations: list[dict[str, Any]],
        rubric_summary: str | None = None,
    ) -> str | None:
        """Tổng hợp câu trả lời chính văn dựa trên bằng chứng đã xác thực, bắt buộc kèm trích dẫn số trang hoặc citation ID."""
        context_lines = []
        for i, cite in enumerate(citations, 1):
            doc = cite.get("document_name") or cite.get("document_id", "Doc")
            page = cite.get("page", 1)
            excerpt = cite.get("excerpt", "")
            cid = cite.get("cid", f"[C{i}]")
            context_lines.append(f"{cid} [{doc}, trang {page}]: {excerpt}")
        context = "\n".join(context_lines)

        system_prompt = (
            "You are an Evidence-Grounded ESG Analyst. Your task is to answer the question using ONLY "
            "the provided excerpts. Every factual statement MUST cite its source as [C1] or [Tên tài liệu, trang X]. "
            "Do NOT hallucinate or assume facts not present in the excerpts. If evidence is insufficient, state clearly what is missing."
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Verified Excerpts:\n{context}\n\n"
            f"Rubric Summary:\n{rubric_summary or 'None'}\n\n"
            "Provide a concise, professional answer with explicit citations (e.g. [C1] or [Document, page X])."
        )
        return self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )


def _normalize_number_token(token: str) -> str:
    return token.replace(",", "").replace(" ", "")


def validate_answer_grounding(
    answer: str,
    valid_citations: list[dict[str, Any]],
    check_numbers: bool = True,
) -> tuple[bool, list[str]]:
    """Kiểm tra grounding: [Cn], số trang, và số liệu định lượng phải neo vào citation đã truy xuất.

    Trả về `(is_valid, issues)` với issues dạng chuỗi ngắn phục vụ fallback/observability.
    """
    if not answer:
        return True, []

    issues: list[str] = []

    # Grounding is reference-by-construction: every non-empty answer sentence
    # must carry a citation id (or the legacy explicit document/page form).
    for sentence in (part.strip() for part in re.split(r"(?<=[.!?])\s+", answer) if part.strip()):
        has_cid = bool(re.search(r"\[C\d+\]", sentence, re.IGNORECASE))
        has_legacy_ref = bool(
            re.search(r"\[[^,\]]+,\s*(?:trang|page)\s*\d+\]", sentence, re.IGNORECASE)
        )
        if not has_cid and not has_legacy_ref:
            issues.append("missing_evidence_ids")
            break

    valid_cids: set[int] = set()
    for i, cite in enumerate(valid_citations, start=1):
        cid_raw = str(cite.get("cid") or f"C{i}")
        match = re.search(r"C(\d+)", cid_raw, re.IGNORECASE)
        valid_cids.add(int(match.group(1)) if match else i)

    cited_cids = [int(m.group(1)) for m in re.finditer(r"\[C(\d+)\]", answer, re.IGNORECASE)]
    bad_cids = sorted({c for c in cited_cids if c not in valid_cids})
    if bad_cids:
        issues.append(f"hallucinated_cids={bad_cids}")

    valid_pages = {int(c["page"]) for c in valid_citations if c.get("page")}
    cited_pages = [
        int(m.group(1)) for m in re.finditer(r"(?:trang|page)\s*(\d+)", answer, re.IGNORECASE)
    ]
    # Dạng [Document, page 5] / [Document, trang 5]
    cited_pages.extend(
        int(m.group(1))
        for m in re.finditer(r"\[\s*[^,\]]+,\s*(?:trang|page)\s*(\d+)\s*\]", answer, re.IGNORECASE)
    )
    bad_pages = sorted({p for p in cited_pages if p not in valid_pages})
    if bad_pages:
        issues.append(f"hallucinated_pages={bad_pages}")

    unsupported: list[str] = []
    if check_numbers:
        excerpt_numbers: set[str] = set()
        for cite in valid_citations:
            for num in re.findall(r"\b\d+(?:[.,]\d+)?\b", cite.get("excerpt") or ""):
                excerpt_numbers.add(_normalize_number_token(num))
            if cite.get("page") is not None:
                excerpt_numbers.add(str(int(cite["page"])))

        cited_cid_set = set(cited_cids)
        for num in re.findall(r"\b\d+(?:[.,]\d+)?\b", answer):
            norm = _normalize_number_token(num)
            # Bỏ qua chỉ số citation ngắn (1, 2, …) khi đã có [Cn]
            if norm.isdigit() and int(norm) in cited_cid_set and len(norm) <= 2:
                continue
            # Chỉ kiểm tra số liệu substantive (>=3 chữ số hoặc thập phân)
            if len(norm.replace(".", "")) < 3 and "." not in norm:
                continue
            if norm in excerpt_numbers:
                continue
            unsupported.append(num)
        if unsupported:
            issues.append(f"unsupported_numbers={unsupported}")

    is_valid = not issues
    return is_valid, issues
