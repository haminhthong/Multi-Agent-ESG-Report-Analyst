from app.capabilities.verification import EvidenceVerificationAgent
from app.config import settings
from app.models import Citation, RetrievalPlan
from app.rubric import RUBRICS
from app.store import Store


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


class RetrievalAgent:
    """Năng lực Truy xuất Bằng chứng Kết hợp & Tái xếp hạng (Hybrid Retrieval & Global Fusion).

    Nhiệm vụ:
    1. Thực thi truy xuất Hybrid (BM25 + Dense) kết hợp RRF Fusion và Cross-Encoder Reranker.
    2. Thực thi Global RRF Fusion qua các subqueries để triệt tiêu bias thứ tự truy vấn.
    3. Tự động khử trùng lặp và đa dạng hóa nguồn trích dẫn theo trang (Page Diversification).
    """

    def __init__(self, store: Store, mode: str | None = None):
        self.store = store
        self.mode = mode or settings.retrieval_mode

    def plan_query(self, question: str) -> str:
        """Bổ sung các thuật ngữ chủ đề liên quan của 3 trụ cột E/S/G vào câu hỏi ban đầu."""
        lowered = question.lower()
        topics = [
            topic
            for rubric in RUBRICS.values()
            if _contains_any(lowered, rubric.topics)
            for topic in rubric.topics
        ]
        if not topics:
            topics = [topic for rubric in RUBRICS.values() for topic in rubric.topics]
        return " ".join((question, *topics, "target baseline performance assurance metrics"))

    def run(self, query: str, top_k: int, document_ids: list[str] | None = None) -> list[Citation]:
        """Thực thi truy xuất đơn truy vấn."""
        raw_results = self.store.search(
            query=self.plan_query(query),
            limit=top_k,
            document_ids=document_ids,
            mode=self.mode,
        )
        citations = [
            Citation(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["name"],
                page=row["page"],
                excerpt=" ".join(row["text"].split())[:700],
                score=float(row.get("score") or round(1 / (1 + abs(row.get("rank", 1.0))), 4)),
                section=row.get("section_title"),
                block_id=row.get("block_id"),
                block_type=row.get("block_type", "text"),
                retrieval_score=float(row.get("score") or 0.0),
                reranker_score=row.get("rerank_score"),
            )
            for row in raw_results
        ]
        return EvidenceVerificationAgent.validate(citations)

    def run_plan(self, plan: RetrievalPlan, top_k: int) -> list[Citation]:
        """Thực thi truy xuất đa truy vấn theo kế hoạch RetrievalPlan với Global RRF Fusion.

        Loại bỏ bias thứ tự truy vấn bằng cách tính Reciprocal Rank Fusion (RRF)
        toàn cục qua tất cả các subqueries trước khi lọc Top-K.
        """
        if not plan.subqueries:
            return []

        sub_limit = max(top_k, 6)
        rrf_k = 60.0

        rrf_scores: dict[tuple[str, int, str], float] = {}
        row_candidates: dict[tuple[str, int, str], dict] = {}
        rerank_scores: dict[tuple[str, int, str], float] = {}

        for sq in plan.subqueries:
            sub_results = self.store.search(
                query=sq,
                limit=sub_limit,
                document_ids=plan.document_scope,
                mode=self.mode,
            )
            for rank, row in enumerate(sub_results, start=1):
                sig = (row["document_id"], row["page"], row["text"][:60])
                sub_score = 1.0 / (rrf_k + rank)
                rrf_scores[sig] = rrf_scores.get(sig, 0.0) + sub_score
                if sig not in row_candidates:
                    row_candidates[sig] = row
                if row.get("rerank_score") is not None:
                    curr_rerank = rerank_scores.get(sig, -999.0)
                    rerank_scores[sig] = max(curr_rerank, float(row["rerank_score"]))

        scored_candidates: list[Citation] = []
        for sig, row in row_candidates.items():
            fused_score = rrf_scores[sig]
            if sig in rerank_scores and rerank_scores[sig] > -999.0:
                fused_score += rerank_scores[sig] * 0.1

            citation = Citation(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["name"],
                page=row["page"],
                excerpt=" ".join(row["text"].split())[:700],
                score=round(fused_score, 4),
                section=row.get("section_title"),
                block_id=row.get("block_id"),
                block_type=row.get("block_type", "text"),
                retrieval_score=float(row.get("score") or 0.0),
                reranker_score=rerank_scores.get(sig, row.get("rerank_score")),
            )
            scored_candidates.append(citation)

        # Sắp xếp toàn cục theo điểm RRF fusion
        scored_candidates.sort(key=lambda c: c.score, reverse=True)

        # Đa dạng hóa theo trang (Page Diversification): tối đa 2 chunk / trang
        diversified: list[Citation] = []
        page_counts: dict[tuple[str, int], int] = {}
        overflow: list[Citation] = []
        for c in scored_candidates:
            pk = (c.document_id, c.page)
            if page_counts.get(pk, 0) < 2:
                page_counts[pk] = page_counts.get(pk, 0) + 1
                diversified.append(c)
            else:
                overflow.append(c)
            if len(diversified) >= top_k:
                break

        if len(diversified) < top_k:
            for c in overflow:
                diversified.append(c)
                if len(diversified) >= top_k:
                    break

        validated = EvidenceVerificationAgent.validate(diversified)
        return validated[:top_k]
