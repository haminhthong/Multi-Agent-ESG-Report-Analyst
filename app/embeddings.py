import hashlib
import logging
from typing import Any

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class DenseEmbeddingEngine:
    """Công cụ tạo vector nhúng (Dense Embeddings) phục vụ Semantic Search trong RAG.

    Đặc tính:
    - Sử dụng mô hình Sentence-Transformers (mặc định: `sentence-transformers/all-MiniLM-L6-v2`).
    - Nạp trễ (Lazy Loading) để tiết kiệm tài nguyên khi khởi động ứng dụng.
    - Deterministic Fallback: Nếu không thể tải weights từ HuggingFace (do offline),
      tự động chuyển sang thuật toán nén băm từ vựng (Feature Hashing Vector 384-dim)
      đảm bảo cosine similarity vẫn hoạt động 100% offline với $0 chi phí.
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embedding_model
        self._model: Any = None
        self._is_fallback: bool = False
        self.dimension: int = 384

    def _get_model(self) -> Any:
        if self._model is not None or self._is_fallback:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer

            # Thử nạp mô hình từ cache cục bộ trước để tránh network timeout
            try:
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
            except Exception:
                self._model = SentenceTransformer(self.model_name)
            logger.info("Loaded SentenceTransformer model: %s", self.model_name)
        except Exception as exc:
            logger.warning(
                "Không thể nạp SentenceTransformer (%s). Sử dụng Deterministic Feature Hashing Fallback.",
                exc,
            )
            self._is_fallback = True
            self._model = None
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Sinh vector nhúng cho danh sách văn bản."""
        if not texts:
            return []

        model = self._get_model()
        if model is not None and not self._is_fallback:
            try:
                embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return [arr.tolist() for arr in embeddings]
            except Exception as exc:
                logger.warning(
                    "Lỗi encode với SentenceTransformer (%s). Chuyển sang fallback.", exc
                )
                self._is_fallback = True

        return [self._fallback_embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """Sinh vector nhúng cho một câu truy vấn."""
        return self.embed_texts([text])[0]

    def _fallback_embed(self, text: str) -> list[float]:
        """Thuật toán Fallback: Feature Hashing 384 chiều chuẩn hóa L2 (100% offline, deterministic)."""
        words = text.lower().split()
        vec = np.zeros(self.dimension, dtype=np.float32)
        if not words:
            return vec.tolist()

        for word in words:
            # Tạo hash ổn định từ chuỗi từ
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
            vec[idx] += sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """Tính độ tương đồng Cosine giữa 2 vector."""
        a = np.array(vec1, dtype=np.float32)
        b = np.array(vec2, dtype=np.float32)
        dot = float(np.dot(a, b))
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


# Khởi tạo singleton embedding engine dùng chung
embedding_engine = DenseEmbeddingEngine()
