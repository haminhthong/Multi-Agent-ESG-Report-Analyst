import re
from dataclasses import dataclass

# Biểu thức chính quy nhận diện tiêu đề (Heading) dựa trên định dạng IN HOA hoặc cấu trúc chỉ mục (VD: 1.2 Climate Risk)
HEADING = re.compile(
    r"^(?:[A-Z][A-Z\s&/–-]{3,}|\d+(?:\.\d+)*\s+[A-Z].{3,80}|(?:Section|Chapter|Part)\s+\d+.{0,60})$"
)

# Mẫu phát hiện cấu trúc bảng (Table detection pattern): chứa dấu gạch đứng hoặc nhiều cột số phân tách bằng tab/khoảng trắng
TABLE_ROW_PATTERN = re.compile(
    r"(?:\|.+?\||^(?:[A-Za-z\s]+?\s{2,}\d+(?:[,.]\d+)?\s{2,}\d+))", re.MULTILINE
)

# Từ khóa phân loại trụ cột ESG
PILLAR_KEYWORDS = {
    "E": (
        "emission",
        "ghg",
        "scope 1",
        "scope 2",
        "scope 3",
        "climate",
        "carbon",
        "energy",
        "renewable",
        "water",
        "waste",
        "tco2e",
        "net-zero",
        "net zero",
    ),
    "S": (
        "safety",
        "injury",
        "trir",
        "employee",
        "workforce",
        "diversity",
        "gender",
        "women",
        "human rights",
        "supplier",
        "training",
        "fatalit",
    ),
    "G": (
        "board",
        "governance",
        "audit",
        "compliance",
        "ethics",
        "anti-corruption",
        "bribery",
        "assurance",
        "whistleblower",
        "director",
        "committee",
    ),
}


@dataclass(frozen=True)
class TextChunk:
    """Đoạn văn bản đã được chuẩn hóa và gắn liền với số trang PDF gốc cùng metadata phân tầng.

    Thuộc tính:
        page (int): Số trang PDF gốc (bắt đầu từ 1).
        text (str): Nội dung văn bản của chunk.
        section_title (str | None): Tiêu đề phần hoặc mục cha.
        block_type (str): Loại khối ("text", "table", "heading").
        block_id (str | None): Mã định danh duy nhất của block.
        company (str | None): Tên doanh nghiệp.
        year (int | None): Năm báo cáo.
        pillar (str | None): Trụ cột ESG ("E", "S", "G").
    """

    page: int
    text: str
    section_title: str | None = None
    block_type: str = "text"
    block_id: str | None = None
    company: str | None = None
    year: int | None = None
    pillar: str | None = None


def detect_pillar(text: str) -> str | None:
    """Phát hiện trụ cột ESG (E/S/G) chủ đạo của một đoạn văn bản."""
    lowered = text.lower()
    counts = {
        pillar: sum(lowered.count(kw) for kw in kws) for pillar, kws in PILLAR_KEYWORDS.items()
    }
    best_pillar, best_count = max(counts.items(), key=lambda x: x[1])
    return best_pillar if best_count > 0 else None


def is_table_content(text: str) -> bool:
    """Kiểm tra xem nội dung đoạn văn có biểu hiện cấu trúc bảng (table) hay không."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return False
    tabular_lines = sum(
        1
        for line in lines
        if "|" in line or "\t" in line or len(re.findall(r"\b\d+(?:[.,]\d+)?\b", line)) >= 2
    )
    return (tabular_lines / len(lines)) >= 0.5


def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản trích xuất từ tệp PDF, khắc phục các lỗi ký tự và xuống dòng phổ biến.

    Xử lý:
    - Loại bỏ các ký tự điều khiển ẩn và ký tự gạch nối mềm (soft hyphen).
    - Nối các từ bị ngắt dòng do dấu gạch nối ở cuối dòng (line-break hyphenation).
    - Quy đổi khoảng trắng liên tiếp về single space và rút gọn nhiều dòng trống liên tiếp.
    """

    # Thay thế các ký tự unicode đặc biệt do PyPDF trích xuất
    text = text.replace("\u0002", "-").replace("\u00ad", "")

    # Nối từ bị ngắt ở cuối dòng: "emiss-\n ions" -> "emissions"
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)

    # Chuẩn hóa khoảng trắng ngang và xuống dòng
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_pages(
    pages: list[tuple[int, str]],
    max_words: int = 260,
    overlap_words: int = 45,
    company: str | None = None,
    year: int | None = None,
) -> list[TextChunk]:
    """Chia nhỏ văn bản theo trang PDF, kết hợp nhận diện tiêu đề (heading-aware),
    cấu trúc bảng (table-aware) và cửa sổ trượt (sliding window).

    Đảm bảo:
    1. Không gộp văn bản giữa các trang khác nhau để bảo toàn số trang nguồn cho citation.
    2. Tách chunk mới khi gặp tiêu đề chính và bảo toàn tiêu đề mục cha (section hierarchy).
    3. Nhận diện các đoạn bảng số liệu (table) để gán block_type phù hợp.
    4. Tạo độ chồng lấp (overlap) giữa các chunk liên tiếp để tránh mất ngữ cảnh ở ranh giới.
    """

    if max_words <= 0:
        raise ValueError("max_words phải lớn hơn 0")
    if not 0 <= overlap_words < max_words:
        raise ValueError("overlap_words phải nằm trong khoảng [0, max_words)")

    chunks: list[TextChunk] = []
    step = max_words - overlap_words
    current_section: str | None = None
    chunk_index = 0

    for page, raw in pages:
        text = normalize_text(raw)
        if not text:
            continue

        # Tách văn bản thành các đoạn (paragraph)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buffer: list[str] = []

        for paragraph in paragraphs:
            words = paragraph.split()

            # Nếu gặp đoạn là tiêu đề chính: cập nhật section và ngắt buffer
            if HEADING.match(paragraph):
                if buffer:
                    chunk_index = _append_windows_with_meta(
                        chunks=chunks,
                        page=page,
                        words=buffer,
                        max_words=max_words,
                        step=step,
                        section_title=current_section,
                        company=company,
                        year=year,
                        chunk_index=chunk_index,
                    )
                    buffer = []
                current_section = paragraph[:120]
                buffer = [paragraph]

            # Nếu đoạn văn có cấu trúc bảng số liệu: giữ nguyên khối bảng không cắt đôi tùy tiện
            elif is_table_content(paragraph):
                if buffer:
                    chunk_index = _append_windows_with_meta(
                        chunks=chunks,
                        page=page,
                        words=buffer,
                        max_words=max_words,
                        step=step,
                        section_title=current_section,
                        company=company,
                        year=year,
                        chunk_index=chunk_index,
                    )
                    buffer = []
                # Đẩy riêng bảng thành một chunk độc lập
                chunk_index += 1
                pillar = detect_pillar(paragraph)
                chunks.append(
                    TextChunk(
                        page=page,
                        text=paragraph,
                        section_title=current_section,
                        block_type="table",
                        block_id=f"p{page}_b{chunk_index}",
                        company=company,
                        year=year,
                        pillar=pillar,
                    )
                )

            # Nếu thêm đoạn này làm vượt quá max_words -> ngắt chunk và giữ lại từ overlap
            elif len(buffer) + len(words) > max_words and buffer:
                chunk_index = _append_windows_with_meta(
                    chunks=chunks,
                    page=page,
                    words=buffer,
                    max_words=max_words,
                    step=step,
                    section_title=current_section,
                    company=company,
                    year=year,
                    chunk_index=chunk_index,
                )
                buffer = buffer[-overlap_words:] + words
            else:
                buffer.extend(words)

        # Xử lý phần văn bản còn lại trong buffer của trang
        if buffer:
            chunk_index = _append_windows_with_meta(
                chunks=chunks,
                page=page,
                words=buffer,
                max_words=max_words,
                step=step,
                section_title=current_section,
                company=company,
                year=year,
                chunk_index=chunk_index,
            )

    return chunks


def _append_windows_with_meta(
    chunks: list[TextChunk],
    page: int,
    words: list[str],
    max_words: int,
    step: int,
    section_title: str | None,
    company: str | None,
    year: int | None,
    chunk_index: int,
) -> int:
    """Hàm phụ trợ áp dụng kỹ thuật cửa sổ trượt và gán metadata phong phú cho từng TextChunk."""

    for start in range(0, len(words), step):
        window = words[start : start + max_words]
        if window:
            chunk_index += 1
            chunk_text = " ".join(window)
            pillar = detect_pillar(chunk_text)
            chunks.append(
                TextChunk(
                    page=page,
                    text=chunk_text,
                    section_title=section_title,
                    block_type="text",
                    block_id=f"p{page}_b{chunk_index}",
                    company=company,
                    year=year,
                    pillar=pillar,
                )
            )
        if start + max_words >= len(words):
            break
    return chunk_index
