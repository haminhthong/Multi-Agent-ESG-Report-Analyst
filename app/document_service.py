import hashlib

from app.agents import DocumentAgent, DocumentIntelligenceAgent
from app.chunking import pages_from_layout_blocks
from app.models import DocumentIngestResponse, LayoutBlock
from app.store import Store

# Dung lượng tệp PDF tối đa cho phép tải lên (75 MB)
MAX_PDF_SIZE_BYTES = 75 * 1024 * 1024

# Số ký tự văn bản tối thiểu trên mỗi trang để coi là có dữ liệu đọc được
MIN_TEXT_CHARACTERS = 40

# Tỷ lệ trang có văn bản tối thiểu (20%) so với tổng số trang, nếu thấp hơn sẽ yêu cầu OCR
MIN_TEXT_PAGE_RATIO = 0.2


class DocumentIngestError(ValueError):
    """Ngoại lệ nghiệp vụ gốc cho các lỗi phát sinh trong quá trình tiếp nhận tài liệu."""


class UnsupportedDocumentError(DocumentIngestError):
    """Ngoại lệ khi tệp đầu vào không phải định dạng PDF hợp lệ hoặc sai Magic Bytes."""


class DocumentTooLargeError(DocumentIngestError):
    """Ngoại lệ khi dung lượng tệp PDF vượt quá giới hạn cấu hình (75 MB)."""


class DocumentExtractionError(DocumentIngestError):
    """Ngoại lệ khi tệp PDF bị hỏng hoặc cấu trúc không thể đọc bởi trình parser."""


class OcrRequiredError(DocumentIngestError):
    """Ngoại lệ khi tệp PDF chứa chủ yếu là ảnh quét (scanned) và cần xử lý OCR trước."""


class DocumentIngestionService:
    """Dịch vụ tiếp nhận, thẩm định, trích xuất thông minh và lập chỉ mục báo cáo PDF.

    Quy trình:
    1. Thẩm định tính toàn vẹn (Magic Bytes `%PDF-`, MIME type, Size).
    2. SHA-256 Content Hash (Idempotency).
    3. Trích xuất khối LayoutBlocks và tính điểm Extraction Quality.
    4. Cảnh báo OCR_REQUIRED nếu tài liệu chủ yếu là ảnh quét.
    5. Lưu trữ metadata và lập chỉ mục tìm kiếm Hybrid trong Store.
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
        """Thực thi quy trình tiếp nhận và lập chỉ mục một tệp PDF hoàn chỉnh."""

        # Step 1: Kiểm tra tính hợp lệ của tệp
        self._validate_file(content, filename, content_type)

        # Step 2: Tính SHA-256 hash của nội dung để kiểm tra Idempotency
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

        # Step 3: Document Intelligence — ưu tiên LayoutBlock, fallback page text
        layout_blocks: list[LayoutBlock] = []
        try:
            layout_blocks = DocumentAgent.extract_pdf_blocks(content, document_id=document_id)
        except Exception:
            layout_blocks = []

        if layout_blocks:
            pages = pages_from_layout_blocks(layout_blocks)
        else:
            try:
                pages = DocumentAgent.extract_pdf(content)
            except Exception as exc:
                raise DocumentExtractionError(f"Không thể trích xuất PDF: {exc}") from exc

        if not pages and not layout_blocks:
            raise DocumentExtractionError("Không thể trích xuất PDF: không có nội dung")

        # Step 4: Kiểm tra chất lượng văn bản trích xuất
        text_pages, quality = self._measure_quality(pages)
        if not pages or quality < MIN_TEXT_PAGE_RATIO:
            raise OcrRequiredError(
                "PDF có quá ít trang chứa văn bản; cần chạy OCR trước khi lập chỉ mục"
            )

        # Step 5: Lưu trữ vào database và chia chunk (layout-aware khi có blocks)
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
        """Thẩm định tệp đầu vào dựa trên đuôi file, Content-Type và chữ ký Magic Bytes `%PDF-`."""

        is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
        if not is_pdf or not content.startswith(b"%PDF-"):
            raise UnsupportedDocumentError("Chỉ hỗ trợ tệp PDF hợp lệ")

        if len(content) > MAX_PDF_SIZE_BYTES:
            raise DocumentTooLargeError(
                f"Kích thước tệp vượt quá giới hạn tối đa ({MAX_PDF_SIZE_BYTES // (1024 * 1024)}MB)"
            )

    @staticmethod
    def _measure_quality(pages: list[tuple[int, str]]) -> tuple[int, float]:
        """Đếm số trang có text và tỷ lệ chất lượng trích xuất."""
        if not pages:
            return 0, 0.0
        text_pages = sum(1 for _, text in pages if len((text or "").strip()) >= MIN_TEXT_CHARACTERS)
        quality = round(text_pages / len(pages), 4)
        return text_pages, quality
