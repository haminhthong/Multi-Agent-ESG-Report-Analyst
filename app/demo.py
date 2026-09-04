from pathlib import Path

from app.store import Store

DEMO_PATH = Path("data/demo/boeing_excerpt.txt")
DEMO_SOURCE_URL = "https://drive.google.com/file/d/1ZwngPi5jIGP6HGwTXj8UVTRyRBIVNLr0"


def seed_demo(store: Store) -> None:
    """Tự động khởi tạo và nạp dữ liệu báo cáo bền vững mẫu Boeing 2025 (Excerpt) khi cơ sở dữ liệu còn trống.

    Đảm bảo người dùng mở ứng dụng lần đầu tiên có ngay dữ liệu để trải nghiệm tìm kiếm và chạy 5 Agent.
    """

    if store.documents() or not DEMO_PATH.exists():
        return
    pages = _load_demo_pages(DEMO_PATH)
    store.add_document(
        "boeing-demo",
        "Boeing 2025 Sustainability Report (excerpt)",
        pages,
        "Boeing",
        "Industrials",
        2025,
        DEMO_SOURCE_URL,
        text_page_count=len(pages),
        extraction_quality=1.0,
    )


def _load_demo_pages(path: Path) -> list[tuple[int, str]]:
    """Hàm phụ trợ đọc tệp trích đoạn văn bản demo được cấu trúc theo thẻ `---PAGE X---`."""

    pages: list[tuple[int, str]] = []
    for block in path.read_text(encoding="utf-8").split("\n---PAGE "):
        page_header, separator, body = block.partition("---\n")
        if separator and page_header.strip().isdigit():
            pages.append((int(page_header.strip()), body))
    return pages
