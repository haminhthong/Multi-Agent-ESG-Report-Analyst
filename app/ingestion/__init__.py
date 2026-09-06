"""Ingestion module: OCR, document validation, and text extraction."""

from app.ingestion.ocr import OCRProvider, TesseractOCRProvider

__all__ = ["OCRProvider", "TesseractOCRProvider"]
