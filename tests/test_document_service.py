from pathlib import Path

import pytest

import app.document_service as service_module
from app.agents import DocumentAgent
from app.document_service import (
    DocumentIngestionService,
    DocumentTooLargeError,
    OcrRequiredError,
    UnsupportedDocumentError,
)
from app.store import Store


@pytest.fixture
def service(tmp_path: Path) -> DocumentIngestionService:
    return DocumentIngestionService(Store(tmp_path / "test.db"))


def test_ingest_returns_quality_and_persists_document(service, monkeypatch):
    pages = [(1, "a" * 50), (2, "b" * 50), (3, "")]
    monkeypatch.setattr(DocumentAgent, "extract_pdf", staticmethod(lambda _: pages))

    result = service.ingest(b"%PDF-demo", "Report.pdf", "application/pdf", "ACME")

    assert result.text_pages == 2
    assert result.extraction_quality == pytest.approx(2 / 3, abs=0.001)
    assert service.store.documents()[0]["status"] == "indexed"

    second = service.ingest(b"%PDF-demo", "Report.pdf", "application/pdf", "ACME")
    assert second.status == "already_indexed"


def test_ingest_rejects_pdf_that_needs_ocr(service, monkeypatch):
    monkeypatch.setattr(
        DocumentAgent,
        "extract_pdf",
        staticmethod(lambda _: [(1, "scan"), (2, "")]),
    )

    with pytest.raises(OcrRequiredError, match="OCR"):
        service.ingest(b"%PDF-scan", "Scan.pdf", "application/pdf")


def test_ingest_rejects_invalid_file(service):
    with pytest.raises(UnsupportedDocumentError):
        service.ingest(b"not-a-pdf", "notes.txt", "text/plain")


def test_ingest_rejects_oversized_file(service, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_PDF_SIZE_BYTES", 8)
    with pytest.raises(DocumentTooLargeError):
        service.ingest(b"%PDF-too-large", "large.pdf", "application/pdf")
