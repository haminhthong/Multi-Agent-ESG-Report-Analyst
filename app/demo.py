from pathlib import Path

from app.store import Store

DEMO_REPORTS = [
    {
        "id": "boeing-demo",
        "name": "Boeing 2025 Sustainability Report (excerpt)",
        "company": "Boeing",
        "sector": "Industrials",
        "year": 2025,
        "path": Path("data/demo/boeing_excerpt.txt"),
        "source_url": "https://drive.google.com/file/d/1ZwngPi5jIGP6HGwTXj8UVTRyRBIVNLr0",
    },
    {
        "id": "nextera-demo",
        "name": "NextEra Energy 2024 Sustainability Report (excerpt)",
        "company": "NextEra Energy",
        "sector": "Energy",
        "year": 2024,
        "path": Path("data/demo/nextera_energy_excerpt.txt"),
        "source_url": "https://www.nexteraenergy.com/sustainability.html",
    },
    {
        "id": "alcoa-demo",
        "name": "Alcoa 2024 Sustainability Report (excerpt)",
        "company": "Alcoa",
        "sector": "Materials",
        "year": 2024,
        "path": Path("data/demo/alcoa_materials_excerpt.txt"),
        "source_url": "https://www.alcoa.com/sustainability",
    },
]


def seed_demo(store: Store, force: bool = False) -> None:
    """Tự động khởi tạo và nạp dữ liệu đa báo cáo đa ngành (Industrials, Energy, Materials).

    Đảm bảo kiểm thử Retrieval có môi trường đối sánh thực tế với nhiều văn bản gây nhiễu (distractors).
    """
    existing_docs = {d["id"] for d in store.documents()}
    for item in DEMO_REPORTS:
        p: Path = item["path"]
        if (item["id"] in existing_docs and not force) or not p.exists():
            continue
        pages = _load_demo_pages(p)
        store.add_document(
            item["id"],
            item["name"],
            pages,
            company=item["company"],
            sector=item["sector"],
            year=item["year"],
            source_url=item["source_url"],
            text_page_count=len(pages),
            extraction_quality=1.0,
        )


def _load_demo_pages(path: Path) -> list[tuple[int, str]]:
    """Hàm phụ trợ đọc tệp trích đoạn văn bản demo được cấu trúc theo thẻ `---PAGE X---`."""
    import re

    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith("---PAGE "):
        raw = raw[len("---PAGE ") :]

    pages: list[tuple[int, str]] = []
    for block in re.split(r"(?:\n|^)---PAGE ", raw):
        page_header, separator, body = block.partition("---\n")
        if separator and page_header.strip().isdigit():
            pages.append((int(page_header.strip()), body.strip()))
    return pages
