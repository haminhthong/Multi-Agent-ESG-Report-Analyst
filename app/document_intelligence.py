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

from app.chunking import HEADING, is_table_content
from app.models import LayoutBlock


class DocumentIntelligenceAgent:
    """Extract page text and heuristic text blocks while preserving page numbers."""

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
        """Extract heuristic blocks from PyPDF text without fabricating coordinates."""
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        reader = PdfReader(stream)
        blocks: list[LayoutBlock] = []
        current_section = "General Information"

        for page_number, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            paragraphs = [
                paragraph.strip()
                for paragraph in re.split(r"\n\s*\n", raw_text)
                if paragraph.strip()
            ]

            for block_index, paragraph in enumerate(paragraphs, start=1):
                if HEADING.match(paragraph):
                    current_section = paragraph[:100]
                    block_type = "heading"
                elif is_table_content(paragraph):
                    block_type = "table"
                else:
                    block_type = "text"

                words = paragraph.split()
                readable_words = sum(len(word) >= 2 for word in words)
                quality = round(min(1.0, readable_words / max(1, len(words))), 2)

                blocks.append(
                    LayoutBlock(
                        document_id=document_id,
                        page=page_number,
                        block_id=f"{document_id}_p{page_number}_b{block_index}",
                        block_type=block_type,
                        section=current_section,
                        text=paragraph,
                        bbox=None,
                        source_method="pypdf_text",
                        quality_score=quality,
                    )
                )

        return blocks

    @staticmethod
    def extract_pdf(source: bytes | BinaryIO) -> list[tuple[int, str]]:
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(stream).pages, start=1)
        ]


DocumentAgent = DocumentIntelligenceAgent
