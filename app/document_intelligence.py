import re
from io import BytesIO
from typing import BinaryIO

from app.chunking import HEADING, is_table_content
from app.models import LayoutBlock


class DocumentIntelligenceAgent:
    """Năng lực Document Intelligence & Thẩm định Cấu trúc Trang (Page Quality Gate).

    Nhiệm vụ:
    1. Tiếp nhận và giải mã cấu trúc tài liệu PDF đa tầng (Native Text, Table, Scanned, Mixed).
    2. Phân loại cấu trúc trang (Page Classification Router).
    3. Trích xuất văn bản theo từng khối LayoutBlock có provenance chuẩn xác, block_type, section và chất lượng.
    4. Không bịa tọa độ giả lập (bbox=None khi parser văn bản không trả tọa độ thật).
    5. Bảo toàn tuyệt đối số trang (Page Number) cho toàn bộ pipeline.
    """

    @staticmethod
    def classify_page(text: str, image_count: int = 0) -> str:
        """Phân loại hình thức của một trang PDF."""
        clean_text = " ".join(text.split())
        if len(clean_text) < 40:
            return "scanned_image"
        has_table = is_table_content(text)
        has_text_paragraphs = len(re.split(r"\n\s*\n", text.strip())) >= 2
        if has_table and has_text_paragraphs:
            return "mixed_page"
        if has_table:
            return "table"
        return "native_text"

    @classmethod
    def extract_pdf_blocks(
        cls, source: bytes | BinaryIO, document_id: str = "doc"
    ) -> list[LayoutBlock]:
        """Trích xuất PDF thành danh sách các khối LayoutBlock chi tiết.

        Chỉ giữ nguyên page provenance và để bbox=None vì pypdf_text parser thuần không trích xuất bounding box hình học.
        """
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        reader = PdfReader(stream)
        blocks: list[LayoutBlock] = []
        current_section = "General Information"

        for page_num, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            page_type = cls.classify_page(raw_text)

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
            for block_idx, p in enumerate(paragraphs, start=1):
                block_id = f"{document_id}_p{page_num}_b{block_idx}"

                if HEADING.match(p):
                    current_section = p[:100]
                    b_type = "heading"
                elif is_table_content(p):
                    b_type = "table"
                else:
                    b_type = "text"

                clean_words = p.split()
                quality = round(
                    min(1.0, sum(len(w) >= 2 for w in clean_words) / max(1, len(clean_words))), 2
                )

                blocks.append(
                    LayoutBlock(
                        document_id=document_id,
                        page=page_num,
                        block_id=block_id,
                        block_type=b_type,
                        section=current_section,
                        text=p,
                        bbox=None,  # Real provenance: parser không trả tọa độ hình học
                        source_method="pypdf_text" if page_type != "scanned_image" else "ocr_candidate",
                        quality_score=quality,
                    )
                )

        return blocks

    @staticmethod
    def extract_pdf(source: bytes | BinaryIO) -> list[tuple[int, str]]:
        """Đọc tệp PDF từ dữ liệu bytes hoặc file stream và trả danh sách (số_trang, nội_dung_văn_bản)."""
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(stream).pages, start=1)
        ]


DocumentAgent = DocumentIntelligenceAgent
