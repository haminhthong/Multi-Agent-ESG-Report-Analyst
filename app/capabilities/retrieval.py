"""Truy xuất bằng chứng hybrid và hợp nhất nhiều truy vấn."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.models import Citation, RetrievalPlan
from app.reranker import reranker
from app.rubric import RUBRICS
from app.store import Store


class EvidenceRetriever:
    """Truy xuất, hợp nhất và đa dạng hóa bằng chứng ESG trước khi thẩm định."""

    def __init__(self, store: Store, mode: str | None = None) -> None:
        self.store = store
        self.mode = mode or settings.retrieval_mode

    def plan_query(self, question: str) -> str:
        lowered = question.lower()
        topics = [
            topic
            for rubric in RUBRICS.values()
            if any(keyword in lowered for keyword in rubric.topics)
            for topic in rubric.topics
        ]
        if not topics:
            topics = [topic for rubric in RUBRICS.values() for topic in rubric.topics]
        topics = list(dict.fromkeys(topics))
        return " ".join((question, *topics, "target baseline performance assurance metrics"))

    def run(
        self,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[Citation]:
        primitive_mode = "hybrid" if self.mode in ("hybrid", "hybrid_rerank") else self.mode
        rows = self.store.search(
            query=self.plan_query(query),
            limit=max(top_k * 3, 15) if self.mode == "hybrid_rerank" else top_k,
            document_ids=document_ids,
            mode=primitive_mode,
        )
        if self.mode == "hybrid_rerank" and len(rows) > 1:
            rows = reranker.rerank(query=query, candidates=rows, top_k=top_k)
        citations = [self._to_citation(row) for row in rows]
        return self._diversify_pages(citations, top_k)

    def run_plan(self, plan: RetrievalPlan, top_k: int) -> list[Citation]:
        """Truy xuất hai giai đoạn: tạo pool bằng RRF rồi rerank Cross-Encoder tối đa một lần."""
        if not plan.subqueries:
            return []

        sub_limit = max(top_k, 6)
        rrf_k = 60.0
        rrf_scores: dict[Any, float] = {}
        candidates: dict[Any, dict] = {}

        # Giai đoạn 1: truy xuất nhiều truy vấn bằng primitive hybrid RRF.
        primitive_mode = "hybrid" if self.mode in ("hybrid", "hybrid_rerank") else self.mode
        for subquery in plan.subqueries:
            rows = self.store.search(
                query=subquery,
                limit=sub_limit,
                document_ids=plan.document_scope,
                mode=primitive_mode,
            )
            for rank, row in enumerate(rows, start=1):
                signature = self._extract_signature(row)
                rrf_scores[signature] = rrf_scores.get(signature, 0.0) + 1.0 / (rrf_k + rank)
                candidates.setdefault(signature, row)

        if not candidates:
            return []

        ranked_rows = sorted(
            candidates.values(),
            key=lambda r: rrf_scores[self._extract_signature(r)],
            reverse=True,
        )

        # Giai đoạn 2: chạy Cross-Encoder một lần trên candidate pool bằng query chuẩn.
        if self.mode == "hybrid_rerank" and len(ranked_rows) > 1:
            candidate_pool = ranked_rows[: max(top_k * 3, 20)]
            rerank_query = (
                plan.canonical_query.strip()
                or plan.original_question.strip()
                or (plan.subqueries[0] if plan.subqueries else "")
            )
            reranked_pool = reranker.rerank(
                query=rerank_query,
                candidates=candidate_pool,
                top_k=len(candidate_pool),
            )
            fused = []
            for row in reranked_pool:
                citation = self._to_citation(row)
                if row.get("rerank_score") is not None:
                    citation.score = float(row["rerank_score"])
                    citation.reranker_score = float(row["rerank_score"])
                else:
                    sig = self._extract_signature(row)
                    citation.score = round(rrf_scores.get(sig, 0.0), 6)
                fused.append(citation)
        else:
            fused = []
            for row in ranked_rows:
                sig = self._extract_signature(row)
                citation = self._to_citation(row)
                citation.score = round(rrf_scores.get(sig, 0.0), 6)
                citation.reranker_score = row.get("rerank_score")
                fused.append(citation)

        fused.sort(key=lambda item: item.score, reverse=True)
        diversified = self._diversify_pages(fused, top_k)
        return diversified[:top_k]

    @staticmethod
    def _extract_signature(row: dict) -> Any:
        """Ưu tiên stable_id hoặc chunk_id, fallback về document/page/block."""
        if row.get("stable_id") is not None:
            return row["stable_id"]
        if row.get("chunk_id") is not None:
            return row["chunk_id"]
        return (
            row["document_id"],
            row["page"],
            row.get("block_id") or (row.get("text") or "")[:60],
        )

    @staticmethod
    def _diversify_pages(citations: list[Citation], top_k: int) -> list[Citation]:
        selected: list[Citation] = []
        overflow: list[Citation] = []
        page_counts: dict[tuple[str, int], int] = {}

        for citation in citations:
            page_key = (citation.document_id, citation.page)
            if page_counts.get(page_key, 0) < 2:
                page_counts[page_key] = page_counts.get(page_key, 0) + 1
                selected.append(citation)
            else:
                overflow.append(citation)
            if len(selected) >= top_k:
                break

        if len(selected) < top_k:
            selected.extend(overflow[: top_k - len(selected)])
        return selected

    @staticmethod
    def _to_citation(row: dict) -> Citation:
        base_score = float(row.get("score") or 0.0)
        source_key = row.get("stable_id") or row.get("block_id") or row.get("chunk_id")
        evidence_id = f"{row['document_id']}:p{row['page']}:{source_key}" if source_key else None
        return Citation(
            chunk_id=row.get("chunk_id"),
            stable_chunk_id=row.get("stable_id"),
            document_id=row["document_id"],
            document_name=row.get("name") or row["document_id"],
            company=row.get("company"),
            document_year=row.get("year"),
            page=row["page"],
            excerpt=" ".join((row.get("text") or "").split())[:700],
            score=base_score,
            section=row.get("section_title"),
            block_id=row.get("block_id"),
            block_type=row.get("block_type", "text"),
            evidence_id=evidence_id,
            retrieval_score=base_score,
            reranker_score=row.get("rerank_score"),
            validated=False,
            validation_status="valid",
        )
