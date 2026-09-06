import hashlib

from app.chunking import pages_from_layout_blocks
from app.document_intelligence import DocumentAgent, DocumentIntelligenceAgent
from app.models import DocumentIngestResponse, LayoutBlock
from app.store import Store

MAX_PDF_SIZE_BYTES = 75 * 1024 * 1024
MIN_TEXT_CHARACTERS = 40
MIN_TEXT_PAGE_RATIO = 0.2


class DocumentIngestError(ValueError):
    """Base business exception for document ingestion failures."""


class UnsupportedDocumentError(DocumentIngestError):
    """Raised when the upload is not a valid PDF payload."""


class DocumentTooLargeError(DocumentIngestError):
    """Raised when the PDF exceeds the configured upload limit."""


class DocumentExtractionError(DocumentIngestError):
    """Raised when page text cannot be extracted."""


class OcrRequiredError(DocumentIngestError):
    """Raised when too little native text is available for reliable indexing."""


class DocumentIngestionService:
    """Validate, extract, quality-check, and index ESG PDF reports.

    The current implementation preserves document/page identity and heuristic
    block types. It does not claim exact PDF coordinates because PyPDF text
    extraction does not provide trustworthy bounding boxes in this pipeline.
    """

    def __init__(self, store: Store):
        self.store = store
        self.doc_agent = DocumentIntelligenceAgent

    def ingest(
        self,
        content: bytes,
        filename: str,
        content_type: str | None = None,
        company: str | None = None,
        sector: str | None = None,
        year: int | None = None,
        force: bool = False,
    ) -> DocumentIngestResponse:
        self._validate_file(content, filename, content_type)

        document_id = hashlib.sha256(content).hexdigest()[:16]
        existing = self.store.get_document(document_id)
        if existing and not force and existing["extraction_quality"] is not None:
            return DocumentIngestResponse(
                id=document_id,
                name=existing["name"],
                pages=existing["page_count"],
                text_pages=existing["text_page_count"],
                extraction_quality=existing["extraction_quality"],
                status="already_indexed",
            )

        layout_blocks: list[LayoutBlock] = []
        layout_error: Exception | None = None
        try:
            layout_blocks = DocumentAgent.extract_pdf_blocks(
                content,
                document_id=document_id,
            )
        except Exception as exc:  # fallback to page-level native text extraction
            layout_error = exc

        if layout_blocks:
            pages = pages_from_layout_blocks(layout_blocks)
        else:
            try:
                pages = DocumentAgent.extract_pdf(content)
            except Exception as exc:
                context = f"; block extraction also failed: {layout_error}" if layout_error else ""
                raise DocumentExtractionError(
                    f"Không thể trích xuất PDF: {exc}{context}"
                ) from exc

        if not pages:
            raise DocumentExtractionError("Không thể trích xuất PDF: không có nội dung")

        text_pages, quality = self._measure_quality(pages)
        if quality < MIN_TEXT_PAGE_RATIO:
            raise OcrRequiredError(
                "PDF có quá ít trang chứa văn bản native; cần OCR trước khi lập chỉ mục"
            )

        self.store.add_document(
            document_id,
            filename,
            pages,
            company=company,
            sector=sector,
            year=year,
            text_page_count=text_pages,
            extraction_quality=quality,
            layout_blocks=layout_blocks or None,
        )
        return DocumentIngestResponse(
            id=document_id,
            name=filename,
            pages=len(pages),
            text_pages=text_pages,
            extraction_quality=quality,
            status="indexed",
        )

    @staticmethod
    def _validate_file(content: bytes, filename: str, content_type: str | None) -> None:
        is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
        if not is_pdf or not content.startswith(b"%PDF-"):
            raise UnsupportedDocumentError("Chỉ hỗ trợ tệp PDF hợp lệ")

        if len(content) > MAX_PDF_SIZE_BYTES:
            raise DocumentTooLargeError(
                f"Kích thước tệp vượt quá giới hạn tối đa ({MAX_PDF_SIZE_BYTES // (1024 * 1024)}MB)"
            )

    @staticmethod
    def _measure_quality(pages: list[tuple[int, str]]) -> tuple[int, float]:
        if not pages:
            return 0, 0.0
        text_pages = sum(
            1
            for _, text in pages
            if len((text or "").strip()) >= MIN_TEXT_CHARACTERS
        )
        quality = round(text_pages / len(pages), 4)
        return text_pages, quality
