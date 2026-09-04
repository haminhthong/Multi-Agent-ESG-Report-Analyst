import hashlib

from app.agents import DocumentAgent
from app.models import DocumentIngestResponse
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
    """Dịch vụ chịu trách nhiệm tiếp nhận, thẩm định, trích xuất và lập chỉ mục báo cáo PDF.

    Quy trình xử lý:
    1. Kiểm tra tính hợp lệ của tệp (đuôi file, MIME type, Magic Bytes `%PDF-`, dung lượng).
    2. Tạo mã định danh duy nhất (Content Hash SHA-256) giúp tính chất Idempotent (tránh lặp).
    3. Đọc danh sách trang và văn bản tương ứng thông qua DocumentAgent.
    4. Đánh giá chất lượng trích xuất (Extraction Quality score).
    5. Lưu trữ metadata và tạo chỉ mục tìm kiếm full-text trong Store.
    """

    def __init__(self, store: Store):
        self.store = store

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
        """Thực thi quy trình tiếp nhận và lập chỉ mục một tệp PDF hoàn chỉnh.

        Tham số:
            content: Dữ liệu nhị phân (bytes) của tệp PDF.
            filename: Tên tệp gốc.
            content_type: MIME type gửi từ client.
            company: Tên công ty (tùy chọn).
            sector: Ngành nghề GICS (tùy chọn).
            year: Năm báo cáo (tùy chọn).
            force: Nếu True, buộc lập chỉ mục lại kể cả khi tệp đã tồn tại.
        """

        # Step 1: Kiểm tra tính hợp lệ của tệp
        self._validate_file(content, filename, content_type)

        # Step 2: Tính SHA-256 hash của nội dung để kiểm tra Idempotency
        document_id = hashlib.sha256(content).hexdigest()[:16]
        existing = self.store.get_document(document_id)

        # Nếu tệp đã được lập chỉ mục trước đó và không yêu cầu force -> Bỏ qua
        if existing and not force and existing["extraction_quality"] is not None:
            return DocumentIngestResponse(
                id=document_id,
                name=existing["name"],
                pages=existing["page_count"],
                text_pages=existing["text_page_count"],
                extraction_quality=existing["extraction_quality"],
                status="already_indexed",
            )

        # Step 3: Trích xuất danh sách trang bằng DocumentAgent
        try:
            pages = DocumentAgent.extract_pdf(content)
        except Exception as exc:
            raise DocumentExtractionError(f"Không thể trích xuất PDF: {exc}") from exc

        # Step 4: Kiểm tra chất lượng văn bản trích xuất
        text_pages, quality = self._measure_quality(pages)
        if not pages or quality < MIN_TEXT_PAGE_RATIO:
            raise OcrRequiredError(
                "PDF có quá ít trang chứa văn bản; cần chạy OCR trước khi lập chỉ mục"
            )

        # Step 5: Lưu trữ vào database và chia chunk
        self.store.add_document(
            document_id,
            filename,
            pages,
            company,
            sector,
            year,
            text_page_count=text_pages,
            extraction_quality=quality,
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
            raise DocumentTooLargeError("Tệp PDF vượt quá giới hạn 75 MB")

    @staticmethod
    def _measure_quality(pages: list[tuple[int, str]]) -> tuple[int, float]:
        """Tính toán tỷ lệ số trang chứa văn bản đọc được so với tổng số trang PDF (Extraction Quality)."""

        if not pages:
            return 0, 0.0
        text_pages = sum(len(" ".join(text.split())) >= MIN_TEXT_CHARACTERS for _, text in pages)
        return text_pages, round(text_pages / len(pages), 4)
