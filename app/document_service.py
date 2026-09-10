import hashlib
from io import BytesIO

from app.chunking import pages_from_layout_blocks
from app.config import settings
from app.document_intelligence import DocumentProcessor
from app.ingestion.ocr import OCRProvider, TesseractOCRProvider
from app.models import DocumentIngestResponse, ExtractionQualityReport, LayoutBlock
from app.store import Store

MAX_PDF_SIZE_BYTES = settings.max_file_size
MIN_TEXT_CHARACTERS = 40
MIN_TEXT_PAGE_RATIO = 0.2


class DocumentIngestError(ValueError):
    """Base business exception for document ingestion failures."""


class UnsupportedDocumentError(DocumentIngestError):
    """Raised when the upload is not a valid PDF payload."""


class DocumentTooLargeError(DocumentIngestError):
    """Raised when the PDF exceeds the configured upload limit."""


class DocumentTooManyPagesError(DocumentIngestError):
    """Raised when a PDF exceeds the configured parser page limit."""


class DocumentExtractionError(DocumentIngestError):
    """Raised when page text cannot be extracted."""


class OcrRequiredError(DocumentIngestError):
    """Raised when too little native text is available for reliable indexing."""


class DocumentIngestionService:
    """Validate, extract, quality-check, and index ESG PDF reports.

    Hỗ trợ cả trích xuất văn bản native qua PyMuPDF (với real bounding boxes)
    và phục hồi qua OCRProvider (Tesseract) khi trang tài liệu là bản scan.
    """

    def __init__(self, store: Store, ocr_provider: OCRProvider | None = None):
        self.store = store
        self.ocr_provider = ocr_provider or TesseractOCRProvider()

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

        # The document id is the full content hash so an artifact can be traced
        # unambiguously across re-indexing and metadata changes.
        document_id = hashlib.sha256(content).hexdigest()
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
            layout_blocks = DocumentProcessor.extract_pdf_blocks(
                content,
                document_id=document_id,
            )
        except Exception as exc:  # noqa: BLE001 - parser fallback boundary
            layout_error = exc

        if layout_blocks:
            pages = self._merge_page_texts(
                pages_from_layout_blocks(layout_blocks),
                self._try_extract_page_texts(content),
            )
        else:
            try:
                pages = DocumentProcessor.extract_pdf(content)
            except Exception as exc:
                context = f"; block extraction also failed: {layout_error}" if layout_error else ""
                raise DocumentExtractionError(f"Không thể trích xuất PDF: {exc}{context}") from exc

        if not pages:
            raise DocumentExtractionError("Không thể trích xuất PDF: không có nội dung")
        if len(pages) > settings.max_pdf_pages:
            raise DocumentTooManyPagesError(f"PDF vượt quá giới hạn {settings.max_pdf_pages} trang")

        native_pages = [
            page for page, text in pages if len((text or "").strip()) >= MIN_TEXT_CHARACTERS
        ]
        low_quality_pages = [page for page, text in pages if page not in native_pages]
        native_text_ratio = round(len(native_pages) / max(1, len(pages)), 4)
        text_pages, quality = self._measure_quality(pages)
        ocr_applied_ratio = 0.0
        ocr_pages: list[int] = []

        # Nếu chất lượng văn bản native thấp, thử phục hồi bằng OCR provider
        needs_page_ocr = any(len((text or "").strip()) < MIN_TEXT_CHARACTERS for _, text in pages)
        if needs_page_ocr and self._ocr_is_available():
            pages, ocr_blocks, ocr_count = self._recover_scanned_pages(content, pages, document_id)
            if ocr_blocks:
                recovered_pages = {block.page for block in ocr_blocks}
                ocr_pages = sorted(recovered_pages)
                layout_blocks = [
                    block for block in layout_blocks if block.page not in recovered_pages
                ] + ocr_blocks
                layout_blocks.sort(key=lambda block: (block.page, block.block_id))
            text_pages, quality = self._measure_quality(pages)
            ocr_applied_ratio = round(ocr_count / max(1, len(pages)), 2)

        if quality < MIN_TEXT_PAGE_RATIO:
            raise OcrRequiredError(
                "PDF có quá ít trang chứa văn bản sau khi phục hồi; cần OCR trước khi lập chỉ mục"
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
            content_sha256=document_id,
            original_file_path=filename,
        )
        empty_pages = [
            page_no for page_no, text in pages if len((text or "").strip()) < MIN_TEXT_CHARACTERS
        ]
        table_count = sum(1 for b in layout_blocks if getattr(b, "block_type", "") == "table")
        table_pages = sorted(
            {b.page for b in layout_blocks if getattr(b, "block_type", "") == "table"}
        )
        average_confidence = round(
            sum(getattr(block, "quality_score", 0.0) for block in layout_blocks)
            / max(1, len(layout_blocks)),
        )
        if not layout_blocks:
            average_confidence = round(quality, 2)
        quality_status = (
            "failed"
            if quality < MIN_TEXT_PAGE_RATIO
            else "review"
            if ocr_pages or low_quality_pages
            else "good"
        )
        report = ExtractionQualityReport(
            native_text_ratio=native_text_ratio,
            ocr_applied_ratio=ocr_applied_ratio,
            native_pages=native_pages,
            ocr_pages=ocr_pages,
            table_pages=table_pages,
            low_quality_pages=low_quality_pages,
            table_count=table_count,
            empty_pages=empty_pages,
            average_confidence=average_confidence,
            status=quality_status,
            notes=[
                f"Đã trích xuất {text_pages}/{len(pages)} trang văn bản ({quality * 100:.1f}%)"
                + (
                    f", OCR phục hồi {ocr_applied_ratio * 100:.1f}% trang"
                    if ocr_applied_ratio > 0
                    else ""
                ),
            ],
        )

        return DocumentIngestResponse(
            id=document_id,
            name=filename,
            pages=len(pages),
            text_pages=text_pages,
            extraction_quality=quality,
            status="indexed",
            extraction_report=report,
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
        text_pages = sum(1 for _, text in pages if len((text or "").strip()) >= MIN_TEXT_CHARACTERS)
        quality = round(text_pages / len(pages), 4)
        return text_pages, quality

    @staticmethod
    def _merge_page_texts(
        layout_pages: list[tuple[int, str]],
        extracted_pages: list[tuple[int, str]],
    ) -> list[tuple[int, str]]:
        """Keep every page while preferring the richer native extraction."""
        by_page = {page: text for page, text in layout_pages}
        for page, text in extracted_pages:
            if page not in by_page or len((text or "").strip()) > len(
                (by_page[page] or "").strip()
            ):
                by_page[page] = text
        return sorted(by_page.items())

    @staticmethod
    def _try_extract_page_texts(content: bytes) -> list[tuple[int, str]]:
        """Best-effort page enumeration for layout parses that omit empty scan pages."""
        try:
            return DocumentProcessor.extract_pdf(content)
        except Exception:  # noqa: BLE001 - optional parser enrichment boundary
            return []

    def _ocr_is_available(self) -> bool:
        try:
            return bool(self.ocr_provider.is_available())
        except (ImportError, OSError, RuntimeError, AttributeError):
            return False

    def _recover_scanned_pages(
        self,
        content: bytes,
        pages: list[tuple[int, str]],
        document_id: str,
    ) -> tuple[list[tuple[int, str]], list[LayoutBlock], int]:
        """Recover low-text pages and return replacement layout blocks for indexing."""
        try:
            import fitz
        except ImportError:
            return pages, [], 0

        page_map = dict(pages)
        recovered_blocks: list[LayoutBlock] = []
        recovered_count = 0
        doc = None
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            for page_no, text in pages:
                if len((text or "").strip()) >= MIN_TEXT_CHARACTERS:
                    continue
                if page_no - 1 >= len(doc):
                    continue
                try:
                    pix = doc[page_no - 1].get_pixmap()
                    img_bytes = pix.tobytes("png")
                    from PIL import Image

                    with Image.open(BytesIO(img_bytes)) as image:
                        recovered = self.ocr_provider.extract_text(image)
                except (OSError, ValueError, TypeError, RuntimeError):
                    continue

                if len((recovered or "").strip()) < MIN_TEXT_CHARACTERS:
                    continue
                recovered_text = recovered.strip()
                page_map[page_no] = recovered_text
                recovered_count += 1
                recovered_blocks.append(
                    LayoutBlock(
                        document_id=document_id,
                        page=page_no,
                        block_id=f"{document_id}_p{page_no}_ocr",
                        block_type="text",
                        section="OCR Recovered",
                        text=recovered_text,
                        bbox=None,
                        source_method="ocr",
                        extraction_method="tesseract",
                        quality_score=0.75,
                    )
                )
        finally:
            if doc is not None:
                doc.close()

        return sorted(page_map.items()), recovered_blocks, recovered_count
