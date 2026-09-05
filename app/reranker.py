import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Bộ xếp hạng chéo (Cross-Encoder Reranker) cho kết quả Hybrid Retrieval.

    Đặc tính:
    - Sử dụng Cross-Encoder (mặc định `cross-encoder/ms-marco-MiniLM-L-6-v2`).
    - Nạp trễ (Lazy Loading).
    - Offline Fallback: Khi chạy offline hoàn toàn, áp dụng thuật toán chấm điểm
      Semantic Lexical Overlap & Proximity để tái xếp hạng chính xác các đoạn chứa thực thể và số liệu.
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.reranker_model
        self._model: Any = None
        self._is_fallback: bool = False

    def _get_model(self) -> Any:
        if self._model is not None or self._is_fallback:
            return self._model

        try:
            from sentence_transformers import CrossEncoder

            try:
                self._model = CrossEncoder(self.model_name, local_files_only=True)
            except Exception:
                self._model = CrossEncoder(self.model_name)
            logger.info("Loaded CrossEncoder model: %s", self.model_name)
        except Exception as exc:
            logger.warning(
                "Không thể nạp CrossEncoder (%s). Sử dụng Semantic Lexical Proximity Reranker Fallback.",
                exc,
            )
            self._is_fallback = True
            self._model = None
        return self._model

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int = 5
    ) -> list[dict[str, Any]]:
        """Tái xếp hạng danh sách các đoạn trích ứng viên dựa trên độ tương đồng sâu với truy vấn."""
        if not candidates:
            return []

        if len(candidates) == 1:
            candidates[0]["rerank_score"] = 1.0
            return candidates[:top_k]

        model = self._get_model()
        if model is not None and not self._is_fallback:
            try:
                pairs = [[query, c["text"]] for c in candidates]
                scores = model.predict(pairs)
                for c, score in zip(candidates, scores):
                    c["rerank_score"] = round(float(score), 4)
                return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]
            except Exception as exc:
                logger.warning(
                    "Lỗi khi chấm điểm với CrossEncoder (%s). Chuyển sang fallback.", exc
                )
                self._is_fallback = True

        return self._fallback_rerank(query, candidates, top_k)

    @staticmethod
    def _fallback_rerank(
        query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        """Fallback Reranking: Chấm điểm dựa trên mật độ từ khóa, số liệu định lượng và độ dài đoạn."""
        q_terms = [w.lower() for w in query.replace('"', " ").split() if len(w) > 2]
        for c in candidates:
            text = c["text"].lower()
            term_hits = sum(text.count(t) for t in q_terms)
            has_numbers = any(char.isdigit() for char in text)
            exact_phrase = 1.5 if query.lower() in text else 0.0
            initial_score = c.get("score", 0.5)

            score = (
                term_hits * 0.4 + (0.3 if has_numbers else 0.0) + exact_phrase + initial_score * 0.3
            )
            c["rerank_score"] = round(float(score), 4)

        return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]


# Khởi tạo singleton reranker
reranker = CrossEncoderReranker()
