"""PDF text extraction and lightweight structural heuristics.

PyPDF exposes page text but this project does not currently extract exact
bounding boxes. Therefore ``LayoutBlock.bbox`` is intentionally left as
``None``. Exact layout provenance should only be added when a parser that
returns real coordinates is integrated.
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
        """Extract layout blocks using PyMuPDF (genuine bboxes) with pypdf fallback."""
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
