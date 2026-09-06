import hashlib
import logging
from typing import Any

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class DenseEmbeddingEngine:
    """Create dense embeddings with an offline deterministic fallback.

    Sentence Transformers is used when the optional ML dependencies are
    available. Otherwise the engine falls back to deterministic feature hashing.
    The fallback is lexical rather than truly semantic, so callers can use a
    lower similarity threshold without pretending it has model-level semantics.
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embedding_model
        self._model: Any = None
        self._is_fallback: bool = False
        self.dimension: int = 384

    @property
    def is_fallback(self) -> bool:
        """Return whether deterministic feature hashing is currently active."""
        return self._is_fallback

    @property
    def backend(self) -> str:
        """Trả về tên backend embedding hiện tại (sentence_transformer hoặc feature_hashing_fallback)."""
        model = self._get_model()
        if model is not None and not self._is_fallback:
            return "sentence_transformer"
        return "feature_hashing_fallback"

    @property
    def is_semantic_loaded(self) -> bool:
        """Kiểm tra xem mô hình Transformer ngữ nghĩa thực tế có được nạp hay đang chạy fallback."""
        return self.backend == "sentence_transformer"

    def _get_model(self) -> Any:
        if self._model is not None or self._is_fallback:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
            except Exception:  # noqa: BLE001 - optional model-loading boundary
                self._model = SentenceTransformer(self.model_name)
            logger.info("Loaded SentenceTransformer model: %s", self.model_name)
        except Exception as exc:  # noqa: BLE001 - optional dependency/model boundary
            logger.warning(
                "Could not load SentenceTransformer (%s); using deterministic feature hashing.",
                exc,
            )
            self._is_fallback = True
            self._model = None
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Create normalized vectors for a list of texts."""
        if not texts:
            return []

        model = self._get_model()
        if model is not None and not self._is_fallback:
            try:
                embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return [arr.tolist() for arr in embeddings]
            except Exception as exc:  # noqa: BLE001 - optional model execution boundary
                logger.warning(
                    "SentenceTransformer encoding failed (%s); switching to fallback.",
                    exc,
                )
                self._is_fallback = True

        return [self._fallback_embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _fallback_embed(self, text: str) -> list[float]:
        """Hash whitespace tokens into a deterministic normalized vector."""
        words = text.lower().split()
        vec = np.zeros(self.dimension, dtype=np.float32)
        if not words:
            return vec.tolist()

        for word in words:
            digest = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            index = digest % self.dimension
            sign = 1.0 if (digest >> 16) % 2 == 0 else -1.0
            vec[index] += sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        a = np.array(vec1, dtype=np.float32)
        b = np.array(vec2, dtype=np.float32)
        dot = float(np.dot(a, b))
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


embedding_engine = DenseEmbeddingEngine()
