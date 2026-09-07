"""OCR Provider interface and implementations for scanned PDF ingestion."""

import logging
from io import BytesIO
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class OCRProvider(Protocol):
    """Protocol defining the interface for Optical Character Recognition providers."""

    def is_available(self) -> bool:
        """Return whether the OCR engine is installed and callable."""
        ...

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
        except Exception:  # noqa: BLE001 - external Tesseract availability probe
            self._available = False
        return self._available

    def extract_text(self, page_image: Any) -> str:
        """Extract text from a PIL image or encoded image bytes."""
        if not self.is_available():
            logger.debug("Tesseract OCR is not available on this system.")
            return ""
        try:
            import pytesseract  # type: ignore

            image = page_image
            if isinstance(page_image, (bytes, bytearray, memoryview)):
                from PIL import Image

                image = Image.open(BytesIO(bytes(page_image)))
            return str(pytesseract.image_to_string(image, lang=self.lang) or "")
        except Exception as exc:  # noqa: BLE001 - OCR provider boundary
            logger.warning("Tesseract OCR extraction failed: %s", exc)
            return ""
