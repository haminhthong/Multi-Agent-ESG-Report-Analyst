"""OCR Provider interface and implementations for scanned PDF ingestion."""

from typing import Any, Protocol, runtime_checkable
import logging

logger = logging.getLogger(__name__)


@runtime_checkable
class OCRProvider(Protocol):
    """Protocol defining the interface for Optical Character Recognition providers."""

    def extract_text(self, page_image: Any) -> str:
        """Extract text from an image or image bytes."""
        ...


class TesseractOCRProvider:
    """Tesseract-based OCR provider with graceful fallback."""

    def __init__(self, lang: str = "eng+vie"):
        self.lang = lang
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import pytesseract  # type: ignore

            pytesseract.get_tesseract_version()
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def extract_text(self, page_image: Any) -> str:
        """Extract text from an image. Returns empty string if OCR engine unavailable."""
        if not self.is_available():
            logger.debug("Tesseract OCR is not available on this system.")
            return ""
        try:
            import pytesseract  # type: ignore

            return str(pytesseract.image_to_string(page_image, lang=self.lang) or "")
        except Exception as exc:
            logger.warning("Tesseract OCR extraction failed: %s", exc)
            return ""
