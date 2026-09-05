import re
from typing import Any

from app.models import Citation
from app.rubric import (
    CRITERIA_DEFINITIONS,
    METRIC_PATTERN,
    NEGATED_PERFORMANCE_PATTERN,
    RUBRICS,
    YEAR_PATTERN,
)
from app.store import Store


class AgentTools:
    """Tập hợp các công cụ (Agent Tools) cho kiến trúc Agentic RAG.

    Các tool này có thể được gọi độc lập bởi Supervisor Agent trong luồng LLM Tool Calling
    hoặc chạy trong luồng Deterministic Orchestration.
    """

    def __init__(self, store: Store):
        self.store = store

    def search_document(
        self,
        query: str,
        limit: int = 6,
        document_ids: list[str] | None = None,
        retrieval_mode: str = "hybrid_rerank",
    ) -> list[Citation]:
        """Tool 1: Tìm kiếm đoạn văn bản bằng chứng theo nhiều chế độ (BM25, Dense, Hybrid, Rerank)."""
        raw_results = self.store.search(
            query=query,
            limit=limit,
            document_ids=document_ids,
            mode=retrieval_mode,
        )
        citations: list[Citation] = []
        for row in raw_results:
            rank = row.get("rank", 0.0)
            score = (
                row.get("rerank_score") or row.get("hybrid_score") or round(1 / (1 + abs(rank)), 4)
            )
            citations.append(
                Citation(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    document_name=row["name"],
                    page=row["page"],
                    excerpt=" ".join(row["text"].split())[:700],
                    score=float(score),
                )
            )
        return citations

    def retrieve_evidence(self, chunk_ids: list[int]) -> list[dict[str, Any]]:
        """Tool 2: Truy xuất trực tiếp các đoạn văn bản đầy đủ theo danh sách chunk_id."""
        with self.store.connect() as db:
            placeholders = ",".join("?" for _ in chunk_ids)
            sql = (
                f"SELECT c.id chunk_id, c.document_id, c.page, c.text, d.name "
                f"FROM chunks c JOIN documents d ON d.id=c.document_id "
                f"WHERE c.id IN ({placeholders})"
            )
            rows = db.execute(sql, chunk_ids).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def extract_metric(text: str) -> dict[str, Any]:
        """Tool 3: Trích xuất các số liệu định lượng, đơn vị và năm báo cáo từ đoạn văn bản."""
        metric_matches = METRIC_PATTERN.findall(text)
        year_matches = YEAR_PATTERN.findall(text)
        numbers = re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", text)
        return {
            "metrics": metric_matches,
            "years": [int(y) for y in year_matches],
            "raw_numbers": numbers,
            "has_metric": len(metric_matches) > 0 or len(numbers) > 0,
        }

    @staticmethod
    def verify_claim(claim: str, excerpt: str) -> dict[str, Any]:
        """Tool 4: Thẩm định xem khẳng định (claim) có được căn cứ trên trích đoạn hay không.

        Kiểm tra:
        - Có bị mâu thuẫn bởi mẫu câu phủ định hay không.
        - Các con số/năm trong claim có xuất hiện trong excerpt hay không.
        - Mức độ tương đồng từ khóa giữa claim và excerpt.
        """
        claim_lower = claim.lower()
        excerpt_lower = excerpt.lower()

        # Kiểm tra mâu thuẫn
        has_contradiction = bool(NEGATED_PERFORMANCE_PATTERN.search(excerpt_lower))

        # Kiểm tra sự xuất hiện của các số liệu
        claim_numbers = set(re.findall(r"\b\d+(?:[\.,]\d+)?\b", claim_lower))
        excerpt_numbers = set(re.findall(r"\b\d+(?:[\.,]\d+)?\b", excerpt_lower))
        numbers_supported = claim_numbers.issubset(excerpt_numbers) if claim_numbers else True

        # Kiểm tra từ khóa
        claim_words = [w for w in re.findall(r"\w+", claim_lower) if len(w) > 3]
        matched_words = [w for w in claim_words if w in excerpt_lower]
        keyword_overlap = len(matched_words) / max(1, len(claim_words))

        supported = (not has_contradiction) and numbers_supported and (keyword_overlap >= 0.3)
        return {
            "supported": supported,
            "has_contradiction": has_contradiction,
            "numbers_supported": numbers_supported,
            "keyword_overlap": round(keyword_overlap, 2),
            "unmatched_numbers": list(claim_numbers - excerpt_numbers),
        }

    @staticmethod
    def score_rubric(pillar: str, evidence_texts: list[str]) -> dict[str, Any]:
        """Tool 5: Đánh giá bộ tiêu chí ESG chuẩn cho một trụ cột (E, S, hoặc G)."""
        combined_text = " ".join(evidence_texts).lower()
        pillar_criteria = [c for c in CRITERIA_DEFINITIONS if c.pillar == pillar]
        rubric = RUBRICS.get(pillar)

        matched_criteria = []
        for c in pillar_criteria:
            found = any(req in combined_text for req in c.required_evidence) or any(
                unit.lower() in combined_text for unit in c.metric_units
            )
            if found:
                matched_criteria.append(c.id)

        total = len(pillar_criteria) if pillar_criteria else (len(rubric.criteria) if rubric else 1)
        coverage = round((len(matched_criteria) / total) * 100, 1) if total > 0 else 0.0

        return {
            "pillar": pillar,
            "matched_criteria": matched_criteria,
            "total_criteria": total,
            "disclosure_coverage": coverage,
        }
