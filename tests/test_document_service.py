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


def test_ingest_uses_layout_blocks(service, monkeypatch):
    from app.models import LayoutBlock

    blocks = [
        LayoutBlock(
            document_id="demo",
            page=1,
            block_id="demo_p1_b1",
            block_type="heading",
            section="Climate",
            text="CLIMATE METRICS",
        ),
        LayoutBlock(
            document_id="demo",
            page=1,
            block_id="demo_p1_b2",
            block_type="text",
            section="Climate",
            text="a" * 50 + " Scope 1 emissions were 100 tCO2e.",
        ),
        LayoutBlock(
            document_id="demo",
            page=2,
            block_id="demo_p2_b1",
            block_type="table",
            section="Climate",
            text="Metric | Value\nScope 2 | 80 tCO2e",
        ),
    ]
    monkeypatch.setattr(
        DocumentAgent,
        "extract_pdf_blocks",
        classmethod(lambda cls, source, document_id="doc": blocks),
    )

    result = service.ingest(b"%PDF-demo-blocks", "Blocks.pdf", "application/pdf", "ACME")
    assert result.status == "indexed"
    assert result.pages == 2

    with service.store.connect() as db:
        rows = db.execute(
            "SELECT block_id, block_type, section_title FROM chunks WHERE document_id=?",
            (result.id,),
        ).fetchall()
    assert rows
    block_ids = {r["block_id"] for r in rows}
    assert "demo_p1_b1" in block_ids or any("demo_p" in (b or "") for b in block_ids)
    assert any(r["block_type"] == "table" for r in rows)
