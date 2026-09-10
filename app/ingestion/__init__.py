"""Module nạp dữ liệu: OCR, kiểm tra tài liệu và trích xuất text."""

from app.ingestion.ocr import OCRProvider, TesseractOCRProvider

__all__ = ["OCRProvider", "TesseractOCRProvider"]
