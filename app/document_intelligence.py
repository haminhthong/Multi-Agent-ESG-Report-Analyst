"""Trích xuất text PDF và các heuristic cấu trúc nhẹ.

PyPDF chỉ cung cấp text theo trang; module này chưa lấy được bounding box chính
xác. Vì vậy ``LayoutBlock.bbox`` được giữ là ``None``. Chỉ bổ sung provenance
bố cục khi parser trả về tọa độ thực được tích hợp.
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import BinaryIO

from app.chunking import is_table_content
from app.models import LayoutBlock


class DocumentProcessor:
    """Trích xuất text và block theo trang, đồng thời giữ provenance."""

    @staticmethod
    def classify_page(text: str) -> str:
        clean_text = " ".join(text.split())
        if len(clean_text) < 40:
            return "low_text"
        has_table_like_text = is_table_content(text)
        has_paragraphs = len(re.split(r"\n\s*\n", text.strip())) >= 2
        if has_table_like_text and has_paragraphs:
            return "mixed_text"
        if has_table_like_text:
            return "table_like_text"
        return "native_text"

    @classmethod
    def extract_pdf_blocks(
        cls,
        source: bytes | BinaryIO,
        document_id: str = "doc",
    ) -> list[LayoutBlock]:
        """Trích xuất block bố cục bằng PyMuPDF, fallback sang pypdf."""
        from app.ingestion.layout_parser import LayoutParser

        return LayoutParser.parse_blocks(source, document_id=document_id)

    @staticmethod
    def extract_pdf(source: bytes | BinaryIO) -> list[tuple[int, str]]:
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(stream).pages, start=1)
        ]
