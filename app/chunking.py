import re
from dataclasses import dataclass

# Biểu thức chính quy nhận diện tiêu đề (Heading) dựa trên định dạng IN HOA hoặc cấu trúc chỉ mục (VD: 1.2 Climate Risk)
HEADING = re.compile(r"^(?:[A-Z][A-Z\s&/-]{4,}|\d+(?:\.\d+)*\s+[A-Z].{3,80})$")


@dataclass(frozen=True)
class TextChunk:
    """Đoạn văn bản đã được chuẩn hóa và gắn liền với số trang PDF gốc.

    Thuộc tính:
        page (int): Số trang PDF gốc (bắt đầu từ 1).
        text (str): Nội dung văn bản của chunk.
    """

    page: int
    text: str


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
    pages: list[tuple[int, str]], max_words: int = 260, overlap_words: int = 45
) -> list[TextChunk]:
    """Chia nhỏ văn bản theo trang PDF, kết hợp nhận diện tiêu đề (heading-aware) và cửa sổ trượt (sliding window).

    Đảm bảo:
    1. Không gộp văn bản giữa các trang khác nhau để bảo toàn số trang nguồn cho citation.
    2. Tách chunk mới khi gặp tiêu đề chính để giữ tính vẹn toàn ngữ nghĩa.
    3. Tạo độ chồng lấp (overlap) giữa các chunk liên tiếp để tránh mất ngữ cảnh ở ranh giới.

    Tham số:
        pages: Danh sách tuple chứa (số trang, nội dung thô).
        max_words: Số lượng từ tối đa trong một chunk (mặc định 260 từ).
        overlap_words: Số từ gối đầu giữa 2 chunk liên tiếp (mặc định 45 từ).
    """

    if max_words <= 0:
        raise ValueError("max_words phải lớn hơn 0")
    if not 0 <= overlap_words < max_words:
        raise ValueError("overlap_words phải nằm trong khoảng [0, max_words)")

    chunks: list[TextChunk] = []
    step = max_words - overlap_words

    for page, raw in pages:
        text = normalize_text(raw)
        if not text:
            continue

        # Tách văn bản thành các đoạn (paragraph)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buffer: list[str] = []

        for paragraph in paragraphs:
            words = paragraph.split()

            # Nếu gặp đoạn là tiêu đề và buffer đã có dữ liệu -> đẩy buffer hiện tại vào chunks
            if HEADING.match(paragraph) and buffer:
                _append_windows(chunks, page, buffer, max_words, step)
                buffer = [paragraph]
            # Nếu thêm đoạn này làm vượt quá max_words -> ngắt chunk và giữ lại từ overlap
            elif len(buffer) + len(words) > max_words and buffer:
                _append_windows(chunks, page, buffer, max_words, step)
                buffer = buffer[-overlap_words:] + words
            else:
                buffer.extend(words)

        # Xử lý phần văn bản còn lại trong buffer của trang
        if buffer:
            _append_windows(chunks, page, buffer, max_words, step)

    return chunks


def _append_windows(
    chunks: list[TextChunk], page: int, words: list[str], max_words: int, step: int
) -> None:
    """Hàm phụ trợ áp dụng kỹ thuật cửa sổ trượt (sliding window) để chia danh sách từ thành các TextChunk."""

    for start in range(0, len(words), step):
        window = words[start : start + max_words]
        if window:
            chunks.append(TextChunk(page=page, text=" ".join(window)))
        if start + max_words >= len(words):
            break
