import sqlite3
from pathlib import Path

from app.chunking import chunk_pages

# ==============================================================================
# SCHEMA KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE & FTS5 (FULL-TEXT SEARCH)
# ==============================================================================
# Bảng `documents`: Lưu thông tin metadata của tệp PDF (tên, công ty, ngành, số trang, chất lượng trích xuất).
# Bảng `chunks`: Lưu các đoạn văn bản đã chia nhỏ kèm số trang PDF gốc.
# Bảng ảo `chunks_fts`: Bảng SQLite FTS5 phục vụ thuật toán tìm kiếm toàn văn và tính điểm BM25.
# Triggers: Tự động đồng bộ thêm/sửa/xóa giữa bảng `chunks` và bảng ảo `chunks_fts`.
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT,
    sector TEXT,
    year INTEGER,
    source_url TEXT,
    page_count INTEGER,
    text_page_count INTEGER,
    extraction_quality REAL,
    status TEXT NOT NULL DEFAULT 'indexed'
);
CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text);
    INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text);
END;
"""

SEARCH_COLUMNS = "c.id chunk_id,c.document_id,c.page,c.text,d.name"


class Store:
    """Kho lưu trữ dữ liệu SQLite quản lý metadata báo cáo, danh sách chunk và chỉ mục FTS5.

    Hỗ trợ:
    - Lưu trữ metadata báo cáo và tự động cập nhật schema (migration).
    - Ingestion có tính Idempotent: Ghi đè hoặc tái lập chỉ mục báo cáo theo Content Hash.
    - Tìm kiếm kết hợp BM25 RAG thông qua SQLite FTS5 và fallback tự động sang Lexical Search.
    """

    def __init__(self, path: Path):
        """Khởi tạo kho dữ liệu, tạo thư mục chứa và khởi chạy migration schema."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate_documents(db)

    @staticmethod
    def _migrate_documents(db: sqlite3.Connection) -> None:
        """Tự động thêm các cột mới vào bảng `documents` nếu nâng cấp từ phiên bản cũ mà không mất dữ liệu."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
        columns = {
            "page_count": "INTEGER",
            "text_page_count": "INTEGER",
            "extraction_quality": "REAL",
            "status": "TEXT NOT NULL DEFAULT 'indexed'",
        }
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")

    def connect(self) -> sqlite3.Connection:
        """Tạo kết nối ngắn hạn tới cơ sở dữ liệu SQLite với cấu hình Row Factory."""
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def add_document(
        self,
        doc_id: str,
        name: str,
        pages: list[tuple[int, str]],
        company: str | None = None,
        sector: str | None = None,
        year: int | None = None,
        source_url: str | None = None,
        text_page_count: int | None = None,
        extraction_quality: float | None = None,
        status: str = "indexed",
    ) -> None:
        """Thêm mới hoặc cập nhật báo cáo cùng toàn bộ chunk của nó trong một database transaction duy nhất."""
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO documents"
                "(id,name,company,sector,year,source_url,page_count,text_page_count,"
                "extraction_quality,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    name,
                    company,
                    sector,
                    year,
                    source_url,
                    len(pages),
                    text_page_count,
                    extraction_quality,
                    status,
                ),
            )
            # Xóa các chunk cũ của tài liệu này để tránh trùng lặp khi re-index
            db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
            for chunk in chunk_pages(pages):
                db.execute(
                    "INSERT INTO chunks(document_id,page,text) VALUES(?,?,?)",
                    (doc_id, chunk.page, chunk.text),
                )

    def documents(self) -> list[dict]:
        """Lấy danh sách toàn bộ các báo cáo đã được lập chỉ mục trong hệ thống."""
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY name")]

    def get_document(self, document_id: str) -> dict | None:
        """Lấy thông tin chi tiết của một báo cáo theo mã định danh (SHA-256 hash)."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict:
        """Tổng hợp nhanh quy mô corpus (số báo cáo, số chunk, số công ty, số ngành) cho health check và UI."""
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(DISTINCT d.id) documents, COUNT(c.id) chunks, "
                "COUNT(DISTINCT d.company) companies, COUNT(DISTINCT d.sector) sectors "
                "FROM documents d LEFT JOIN chunks c ON c.document_id=d.id"
            ).fetchone()
            return dict(row)

    def search(
        self, query: str, limit: int = 6, document_ids: list[str] | None = None
    ) -> list[dict]:
        """Thực thi tìm kiếm đoạn văn bản bằng thuật toán FTS5 BM25.

        Nếu FTS5 không trả về kết quả (do khác biệt từ vựng hoặc lỗi cú pháp FTS),
        hệ thống tự động chuyển sang thuật toán Lexical Fallback để đảm bảo luôn trả bằng chứng.
        """
        terms = [t.lower() for t in query.replace('"', " ").split() if len(t) > 2]
        with self.connect() as db:
            return self._search_fts(db, terms, limit, document_ids) or self._search_lexical(
                db, terms, limit, document_ids
            )

    @staticmethod
    def _search_fts(
        db: sqlite3.Connection,
        terms: list[str],
        limit: int,
        document_ids: list[str] | None,
    ) -> list[dict]:
        """Tìm kiếm bằng thuật toán xếp hạng BM25 mặc định của SQLite FTS5."""
        fts = " OR ".join(f'"{t}"' for t in terms[:20]) or "ESG"
        sql = (
            f"SELECT {SEARCH_COLUMNS},bm25(chunks_fts) rank FROM chunks_fts "
            "JOIN chunks c ON c.id=chunks_fts.rowid "
            "JOIN documents d ON d.id=c.document_id WHERE chunks_fts MATCH ?"
        )
        params = [fts]
        if document_ids:
            sql += f" AND c.document_id IN ({','.join('?' for _ in document_ids)})"
            params.extend(document_ids)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            return [dict(row) for row in db.execute(sql, params)]
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def _search_lexical(
        db: sqlite3.Connection,
        terms: list[str],
        limit: int,
        document_ids: list[str] | None,
    ) -> list[dict]:
        """Phương thức dự phòng (Lexical Fallback) khớp tần suất từ xuất hiện (term frequency) khi FTS5 không khớp."""
        sql = (
            f"SELECT {SEARCH_COLUMNS},0.0 rank FROM chunks c JOIN documents d ON d.id=c.document_id"
        )
        params: list[str] = []
        if document_ids:
            sql += f" WHERE c.document_id IN ({','.join('?' for _ in document_ids)})"
            params.extend(document_ids)

        stems = {term.rstrip("s") for term in terms}
        candidates = [dict(row) for row in db.execute(sql, params)]
        for row in candidates:
            text = row["text"].lower()
            hits = sum(text.count(stem) + text.count(stem + "s") for stem in stems)
            row["rank"] = -float(hits)
        matched = (row for row in candidates if row["rank"] < 0)
        return sorted(matched, key=lambda row: row["rank"])[:limit]
