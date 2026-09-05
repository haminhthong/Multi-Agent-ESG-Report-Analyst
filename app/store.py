import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.chunking import chunk_pages
from app.config import settings
from app.embeddings import embedding_engine
from app.reranker import reranker


@runtime_checkable
class RetrievalStore(Protocol):
    """Giao diện trừu tượng (Protocol) cho các hệ thống lưu trữ và truy xuất bằng chứng ESG.

    Cho phép kiến trúc local-first cắm ghép linh hoạt giữa SQLite FTS5, FAISS hoặc Qdrant.
    """

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
    ) -> None: ...

    def search(
        self,
        query: str,
        limit: int = 6,
        document_ids: list[str] | None = None,
        mode: str | None = None,
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_document(self, document_id: str) -> dict | None: ...

    def documents(self) -> list[dict]: ...

    def stats(self) -> dict: ...


# ==============================================================================
# SCHEMA KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE & FTS5 (FULL-TEXT SEARCH)
# ==============================================================================
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
    section_title TEXT,
    block_type TEXT DEFAULT 'text',
    block_id TEXT,
    pillar TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS chunk_embeddings(
    chunk_id INTEGER PRIMARY KEY,
    vector_json TEXT NOT NULL,
    FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text);
    DELETE FROM chunk_embeddings WHERE chunk_id=old.id;
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text);
    INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text);
END;
"""

SEARCH_COLUMNS = (
    "c.id chunk_id, c.document_id, c.page, c.text, "
    "c.section_title, c.block_type, c.block_id, c.pillar, "
    "d.name, d.company, d.year"
)


class Store:
    """Kho lưu trữ dữ liệu SQLite FTS5 quản lý metadata báo cáo, danh sách chunk phân tầng và vector embedding.

    Triển khai chuẩn mực theo giao diện `RetrievalStore` (Local-First Architecture).
    """

    def __init__(self, path: Path):
        """Khởi tạo kho dữ liệu, tạo thư mục chứa và khởi chạy migration schema."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate_documents(db)
            self._migrate_chunks(db)

    @staticmethod
    def _migrate_documents(db: sqlite3.Connection) -> None:
        """Tự động thêm các cột mới vào bảng `documents` nếu nâng cấp từ phiên bản cũ."""
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

    @staticmethod
    def _migrate_chunks(db: sqlite3.Connection) -> None:
        """Tự động thêm các cột metadata phân tầng vào bảng `chunks`."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(chunks)")}
        columns = {
            "section_title": "TEXT",
            "block_type": "TEXT DEFAULT 'text'",
            "block_id": "TEXT",
            "pillar": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE chunks ADD COLUMN {name} {definition}")

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
            inserted_chunks = []
            for chunk in chunk_pages(pages, company=company, year=year):
                cur = db.execute(
                    "INSERT INTO chunks(document_id, page, text, section_title, block_type, block_id, pillar) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        doc_id,
                        chunk.page,
                        chunk.text,
                        chunk.section_title,
                        chunk.block_type,
                        chunk.block_id,
                        chunk.pillar,
                    ),
                )
                inserted_chunks.append((cur.lastrowid, chunk.text))

            # Tự động tính toán và lưu trữ vector nhúng cho từng chunk
            if inserted_chunks:
                texts = [c[1] for c in inserted_chunks]
                vectors = embedding_engine.embed_texts(texts)
                for (cid, _), vec in zip(inserted_chunks, vectors):
                    db.execute(
                        "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, vector_json) VALUES(?,?)",
                        (cid, json.dumps(vec)),
                    )

    def ensure_embeddings(self) -> None:
        """Đảm bảo mọi chunk trong cơ sở dữ liệu đều có vector embedding."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.id, c.text FROM chunks c "
                "LEFT JOIN chunk_embeddings ce ON ce.chunk_id = c.id "
                "WHERE ce.chunk_id IS NULL"
            ).fetchall()
            if not rows:
                return
            texts = [r["text"] for r in rows]
            vectors = embedding_engine.embed_texts(texts)
            for r, vec in zip(rows, vectors):
                db.execute(
                    "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, vector_json) VALUES(?,?)",
                    (r["id"], json.dumps(vec)),
                )

    def documents(self) -> list[dict]:
        """Lấy danh sách toàn bộ các báo cáo đã được lập chỉ mục trong hệ thống."""
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY name")]

    def get_document(self, document_id: str) -> dict | None:
        """Lấy thông tin chi tiết của một báo cáo theo mã định danh."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict:
        """Tổng hợp nhanh quy mô corpus cho health check và UI."""
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(DISTINCT d.id) documents, COUNT(c.id) chunks, "
                "COUNT(DISTINCT d.company) companies, COUNT(DISTINCT d.sector) sectors "
                "FROM documents d LEFT JOIN chunks c ON c.document_id=d.id"
            ).fetchone()
            return dict(row)

    def search(
        self,
        query: str,
        limit: int = 6,
        document_ids: list[str] | None = None,
        mode: str | None = None,
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Thực thi tìm kiếm đoạn văn bản theo các chế độ Hybrid & Rerank kết hợp khử trùng ngữ nghĩa (Diversification)."""
        search_mode = mode or settings.retrieval_mode
        terms = [t.lower() for t in query.replace('"', " ").split() if len(t) > 2]

        with self.connect() as db:
            if search_mode == "bm25":
                raw = self._search_fts(
                    db, terms, limit * 2, document_ids, pillar, year
                ) or self._search_lexical(db, terms, limit * 2, document_ids, pillar, year)
                for r in raw:
                    r["score"] = round(1 / (1 + abs(r.get("rank", 1.0))), 4)
                return self._diversify_results(raw, limit)

            if search_mode == "dense":
                raw = self._search_dense(db, query, limit * 2, document_ids, pillar, year)
                return self._diversify_results(raw, limit)

            if search_mode == "hybrid":
                raw = self._search_hybrid(
                    db,
                    query,
                    limit * 2,
                    document_ids,
                    rrf_k=settings.rrf_k,
                    pillar=pillar,
                    year=year,
                )
                return self._diversify_results(raw, limit)

            # Chế độ mặc định: hybrid_rerank
            candidate_limit = max(limit * 3, 15)
            candidates = self._search_hybrid(
                db,
                query,
                candidate_limit,
                document_ids,
                rrf_k=settings.rrf_k,
                pillar=pillar,
                year=year,
            )
            reranked = reranker.rerank(query, candidates, top_k=candidate_limit)
            return self._diversify_results(reranked, limit)

    def _search_dense(
        self,
        db: sqlite3.Connection,
        query: str,
        limit: int,
        document_ids: list[str] | None,
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Tìm kiếm tương đồng ngữ nghĩa (Dense Semantic Search) bằng Cosine Similarity."""
        self.ensure_embeddings()
        q_vec = embedding_engine.embed_query(query)
        sql = (
            f"SELECT {SEARCH_COLUMNS}, ce.vector_json "
            f"FROM chunks c JOIN documents d ON d.id=c.document_id "
            f"JOIN chunk_embeddings ce ON ce.chunk_id=c.id"
        )
        conditions: list[str] = []
        params: list[Any] = []

        if document_ids:
            conditions.append(f"c.document_id IN ({','.join('?' for _ in document_ids)})")
            params.extend(document_ids)
        if pillar:
            conditions.append("c.pillar = ?")
            params.append(pillar)
        if year:
            conditions.append("d.year = ?")
            params.append(year)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        rows = db.execute(sql, params).fetchall()
        scored = []
        for r in rows:
            vec = json.loads(r["vector_json"])
            sim = embedding_engine.cosine_similarity(q_vec, vec)
            if sim < 0.15:
                continue
            item = dict(r)
            del item["vector_json"]
            item["score"] = round(sim, 4)
            item["dense_score"] = round(sim, 4)
            item["rank"] = -sim
            scored.append(item)

        scored.sort(key=lambda x: x["dense_score"], reverse=True)
        return scored[:limit]

    def _search_hybrid(
        self,
        db: sqlite3.Connection,
        query: str,
        limit: int,
        document_ids: list[str] | None,
        rrf_k: int = 60,
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Tìm kiếm Hybrid Fusion kết hợp BM25 và Dense bằng Reciprocal Rank Fusion (RRF)."""
        candidate_k = max(limit * 3, 20)
        terms = [t.lower() for t in query.replace('"', " ").split() if len(t) > 2]
        bm25_results = self._search_fts(
            db, terms, candidate_k, document_ids, pillar, year
        ) or self._search_lexical(db, terms, candidate_k, document_ids, pillar, year)
        dense_results = self._search_dense(db, query, candidate_k, document_ids, pillar, year)

        rrf_scores: dict[int, float] = {}
        chunks_map: dict[int, dict[str, Any]] = {}

        for rank, item in enumerate(bm25_results, start=1):
            cid = item["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
            chunks_map[cid] = item

        for rank, item in enumerate(dense_results, start=1):
            cid = item["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
            if cid not in chunks_map:
                chunks_map[cid] = item

        combined = []
        for cid, score in rrf_scores.items():
            item = dict(chunks_map[cid])
            item["hybrid_score"] = round(score, 5)
            item["score"] = round(score, 5)
            item["rank"] = -score
            combined.append(item)

        combined.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return combined[:limit]

    @staticmethod
    def _search_fts(
        db: sqlite3.Connection,
        terms: list[str],
        limit: int,
        document_ids: list[str] | None,
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict]:
        """Tìm kiếm bằng thuật toán xếp hạng BM25 mặc định của SQLite FTS5."""
        fts = " OR ".join(f'"{t}"' for t in terms[:20]) or "ESG"
        sql = (
            f"SELECT {SEARCH_COLUMNS}, bm25(chunks_fts) rank FROM chunks_fts "
            "JOIN chunks c ON c.id=chunks_fts.rowid "
            "JOIN documents d ON d.id=c.document_id WHERE chunks_fts MATCH ?"
        )
        params: list[Any] = [fts]

        if document_ids:
            sql += f" AND c.document_id IN ({','.join('?' for _ in document_ids)})"
            params.extend(document_ids)
        if pillar:
            sql += " AND c.pillar = ?"
            params.append(pillar)
        if year:
            sql += " AND d.year = ?"
            params.append(year)

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
        pillar: str | None = None,
        year: int | None = None,
    ) -> list[dict]:
        """Phương thức dự phòng (Lexical Fallback) khớp tần suất từ xuất hiện (term frequency)."""
        sql = f"SELECT {SEARCH_COLUMNS}, 0.0 rank FROM chunks c JOIN documents d ON d.id=c.document_id"
        conditions: list[str] = []
        params: list[Any] = []

        if document_ids:
            conditions.append(f"c.document_id IN ({','.join('?' for _ in document_ids)})")
            params.extend(document_ids)
        if pillar:
            conditions.append("c.pillar = ?")
            params.append(pillar)
        if year:
            conditions.append("d.year = ?")
            params.append(year)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        stems = {term.rstrip("s") for term in terms}
        candidates = [dict(row) for row in db.execute(sql, params)]
        for row in candidates:
            text = row["text"].lower()
            hits = sum(text.count(stem) + text.count(stem + "s") for stem in stems)
            row["rank"] = -float(hits)
        matched = (row for row in candidates if row["rank"] < 0)
        return sorted(matched, key=lambda row: row["rank"])[:limit]

    @staticmethod
    def _diversify_results(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Khử trùng lặp ngữ nghĩa (Evidence Diversification):

        Ưu tiên các đoạn từ các trang khác nhau hoặc phần nội dung khác nhau,
        tránh việc top-K bị chiếm toàn bộ bởi các chunk trùng lặp từ 1 trang duy nhất.
        """
        if len(candidates) <= limit:
            return candidates

        selected: list[dict[str, Any]] = []
        seen_signatures: set[tuple[str, int]] = set()
        overflow: list[dict[str, Any]] = []

        for item in candidates:
            sig = (item["document_id"], item["page"])
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                selected.append(item)
            else:
                overflow.append(item)

            if len(selected) == limit:
                break

        # Nếu còn thiếu chỗ thì lấy tiếp từ overflow
        if len(selected) < limit:
            selected.extend(overflow[: limit - len(selected)])

        return selected


# Alias phục vụ khái niệm pluggable retrieval backends trong README
SQLiteFTSStore = Store
