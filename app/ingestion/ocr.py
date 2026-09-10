"""Giao diện và triển khai OCR cho PDF scan."""

import logging
from io import BytesIO
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class OCRProvider(Protocol):
    """Protocol định nghĩa giao diện của provider nhận dạng ký tự quang học."""

    def is_available(self) -> bool:
        """Cho biết engine OCR đã cài và có thể gọi hay chưa."""
        ...

    def extract_text(self, page_image: Any) -> str:
        """Trích xuất text từ ảnh hoặc bytes của ảnh."""
        ...


class TesseractOCRProvider:
    """Provider OCR dùng Tesseract với fallback an toàn."""

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
        """Trích xuất text từ ảnh PIL hoặc bytes ảnh đã mã hóa."""
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
