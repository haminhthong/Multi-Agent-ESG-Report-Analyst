from app.ingestion.ocr import OCRProvider, TesseractOCRProvider
from app.models import ExtractionQualityReport


def test_ocr_provider_protocol():
    provider = TesseractOCRProvider()
    assert isinstance(provider, OCRProvider)


def test_tesseract_ocr_graceful_fallback():
    provider = TesseractOCRProvider()
    # When tesseract is not available or mock image passed, should not crash
    result = provider.extract_text(b"mock_bytes")
    assert isinstance(result, str)


def test_extraction_quality_report():
    report = ExtractionQualityReport(
        native_text_ratio=0.95,
        ocr_applied_ratio=0.0,
        table_count=3,
        empty_pages=[],
        average_confidence=1.0,
        notes=["Quality verified"],
    )
    assert report.native_text_ratio == 0.95
    assert report.table_count == 3
    assert len(report.notes) == 1
