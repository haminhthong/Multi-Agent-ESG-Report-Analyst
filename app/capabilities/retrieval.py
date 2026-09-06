"""Hybrid evidence retrieval and multi-query fusion."""

from __future__ import annotations

from app.config import settings
from app.models import Citation, RetrievalPlan
from app.reranker import reranker
from app.rubric import RUBRICS
from app.store import Store


class RetrievalAgent:
    """Retrieve, fuse, and diversify ESG evidence candidates without performing validation."""

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
        rows = self.store.search(
            query=self.plan_query(query),
            limit=top_k,
            document_ids=document_ids,
            mode=self.mode,
        )
        citations = [self._to_citation(row) for row in rows]
        return self._diversify_pages(citations, top_k)

    def run_plan(self, plan: RetrievalPlan, top_k: int) -> list[Citation]:
        """Two-stage retrieval: RRF candidate pool generation followed by optional Cross-Encoder reranking."""
        if not plan.subqueries:
            return []

        sub_limit = max(top_k, 6)
        rrf_k = 60.0
        rrf_scores: dict[Any, float] = {}
        candidates: dict[Any, dict] = {}

        for subquery in plan.subqueries:
            rows = self.store.search(
                query=subquery,
                limit=sub_limit,
                document_ids=plan.document_scope,
                mode=self.mode,
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

        # Stage 2: Cross-Encoder Reranker on Top-20 Candidate Pool (if hybrid_rerank is active)
        if self.mode == "hybrid_rerank" and len(ranked_rows) > 1:
            candidate_pool = ranked_rows[:max(top_k * 3, 20)]
            rerank_query = plan.subqueries[0]
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
        """Prioritize chunk_id for provenance identity; fallback to document/page/block."""
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
        return Citation(
            chunk_id=row.get("chunk_id"),
            document_id=row["document_id"],
            document_name=row.get("name") or row["document_id"],
            page=row["page"],
            excerpt=" ".join((row.get("text") or "").split())[:700],
            score=base_score,
            section=row.get("section_title"),
            block_id=row.get("block_id"),
            block_type=row.get("block_type", "text"),
            retrieval_score=base_score,
            reranker_score=row.get("rerank_score"),
            validated=False,
            validation_status="valid",
        )
