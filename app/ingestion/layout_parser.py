"""Phân tích bố cục PDF bằng PyMuPDF với bounding box và fallback."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import BinaryIO

from app.chunking import HEADING, is_table_content
from app.models import LayoutBlock

logger = logging.getLogger(__name__)


class LayoutParser:
    """Trích xuất block bố cục có bounding box từ tài liệu PDF."""

    @classmethod
    def is_pymupdf_available(cls) -> bool:
        """Kiểm tra sự tồn tại của thư viện PyMuPDF (fitz)."""
        import importlib.util

        return importlib.util.find_spec("fitz") is not None

    @classmethod
    def parse_blocks(
        cls,
        source: bytes | BinaryIO,
        document_id: str = "doc",
    ) -> list[LayoutBlock]:
        """Thử PyMuPDF để lấy bbox thật, fallback sang pypdf khi cần."""
        data_bytes = source.read() if hasattr(source, "read") else source
        if not data_bytes:
            return []

        try:
            return cls._parse_with_pymupdf(data_bytes, document_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PyMuPDF block extraction failed (%s); falling back to pypdf.", exc)
            return cls._fallback_parse_pypdf(data_bytes, document_id)

    @classmethod
    def _parse_with_pymupdf(cls, content: bytes, document_id: str) -> list[LayoutBlock]:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=content, filetype="pdf")
        blocks: list[LayoutBlock] = []
        current_section = "General Information"

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_no = page_idx + 1

            # 1. Trích xuất bảng bằng PyMuPDF find_tables() nếu có
            table_rects: list[fitz.Rect] = []
            try:
                tables = page.find_tables()
                for t_idx, tab in enumerate(tables, start=1):
                    t_bbox = [round(coord, 2) for coord in tab.bbox]
                    table_rects.append(fitz.Rect(tab.bbox))
                    tab_df_markdown = ""
                    try:
                        tab_df = tab.extract()
                        if tab_df:
                            rows_str = []
                            for row in tab_df:
                                clean_row = [str(c or "").strip().replace("\n", " ") for c in row]
                                rows_str.append("| " + " | ".join(clean_row) + " |")
                            tab_df_markdown = "\n".join(rows_str)
                    except Exception:  # noqa: BLE001 - table extractor is optional
                        tab_df_markdown = ""

                    if not tab_df_markdown:
                        tab_df_markdown = tab.extract() if hasattr(tab, "extract") else ""
                        if isinstance(tab_df_markdown, list):
                            tab_df_markdown = "\n".join(
                                "| " + " | ".join(str(c or "") for c in r) + " |"
                                for r in tab_df_markdown
                            )

                    if tab_df_markdown and str(tab_df_markdown).strip():
                        blocks.append(
                            LayoutBlock(
                                document_id=document_id,
                                page=page_no,
                                block_id=f"{document_id}_p{page_no}_tab{t_idx}",
                                block_type="table",
                                section=current_section,
                                text=str(tab_df_markdown).strip(),
                                bbox=t_bbox,
                                source_method="pymupdf_table",
                                quality_score=1.0,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - optional table extraction boundary
                logger.debug("Table detection error on page %d: %s", page_no, exc)

                # 2. Trích xuất block text cùng bounding box thật.
                # get_text("blocks") trả về x0, y0, x1, y1, text, block_no, block_type.
            page_blocks = page.get_text("blocks")
            for b_idx, block in enumerate(page_blocks, start=1):
                if len(block) < 5:
                    continue
                x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
                block_type_code = block[6] if len(block) >= 7 else 0

                # Bỏ qua block ảnh (code 1) hoặc text quá ngắn.
                if block_type_code != 0:
                    continue
                clean_text = text.strip()
                if not clean_text:
                    continue

                # Kiểm tra nếu block này nằm trọn trong table rect đã trích xuất thì bỏ qua
                b_rect = fitz.Rect(x0, y0, x1, y1)
                if any(
                    t_rect.contains(b_rect)
                    or (b_rect.intersect(t_rect).get_area() > 0.8 * b_rect.get_area())
                    for t_rect in table_rects
                ):
                    continue

                bbox = [
                    round(float(x0), 2),
                    round(float(y0), 2),
                    round(float(x1), 2),
                    round(float(y1), 2),
                ]

                # Phân loại loại block
                if HEADING.match(clean_text) and len(clean_text) < 120:
                    current_section = clean_text[:100]
                    block_type = "heading"
                elif is_table_content(clean_text):
                    block_type = "table"
                else:
                    block_type = "text"

                words = clean_text.split()
                readable_words = sum(len(w) >= 2 for w in words)
                quality = round(min(1.0, readable_words / max(1, len(words))), 2)

                blocks.append(
                    LayoutBlock(
                        document_id=document_id,
                        page=page_no,
                        block_id=f"{document_id}_p{page_no}_b{b_idx}",
                        block_type=block_type,
                        section=current_section,
                        text=clean_text,
                        bbox=bbox,
                        source_method="pymupdf_blocks",
                        quality_score=quality,
                    )
                )

        doc.close()
        return blocks

    @classmethod
    def _fallback_parse_pypdf(cls, content: bytes, document_id: str) -> list[LayoutBlock]:
        """Fallback heuristic bằng pypdf khi không có PyMuPDF."""
        from pypdf import PdfReader

        stream = BytesIO(content)
        reader = PdfReader(stream)
        blocks: list[LayoutBlock] = []
        current_section = "General Information"

        for page_number, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]

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
