"""Hybrid evidence retrieval and multi-query fusion."""

from __future__ import annotations

from app.capabilities.verification import EvidenceVerificationAgent
from app.config import settings
from app.models import Citation, RetrievalPlan
from app.rubric import RUBRICS
from app.store import Store


class RetrievalAgent:
    """Retrieve, fuse, and diversify ESG evidence candidates."""

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
        return EvidenceVerificationAgent.validate(citations)

    def run_plan(self, plan: RetrievalPlan, top_k: int) -> list[Citation]:
        """Fuse candidates across subqueries using global Reciprocal Rank Fusion."""
        if not plan.subqueries:
            return []

        sub_limit = max(top_k, 6)
        rrf_k = 60.0
        rrf_scores: dict[tuple[str, int, str], float] = {}
        candidates: dict[tuple[str, int, str], dict] = {}
        rerank_scores: dict[tuple[str, int, str], float] = {}

        for subquery in plan.subqueries:
            rows = self.store.search(
                query=subquery,
                limit=sub_limit,
                document_ids=plan.document_scope,
                mode=self.mode,
            )
            for rank, row in enumerate(rows, start=1):
                signature = (row["document_id"], row["page"], row["text"][:60])
                rrf_scores[signature] = rrf_scores.get(signature, 0.0) + 1.0 / (rrf_k + rank)
                candidates.setdefault(signature, row)
                if row.get("rerank_score") is not None:
                    rerank_scores[signature] = max(
                        rerank_scores.get(signature, float("-inf")),
                        float(row["rerank_score"]),
                    )

        fused: list[Citation] = []
        for signature, row in candidates.items():
            score = rrf_scores[signature]
            rerank_score = rerank_scores.get(signature)
            if rerank_score is not None:
                score += rerank_score * 0.1
            citation = self._to_citation(row)
            citation.score = round(score, 6)
            citation.reranker_score = rerank_score
            fused.append(citation)

        fused.sort(key=lambda item: item.score, reverse=True)
        diversified = self._diversify_pages(fused, top_k)
        return EvidenceVerificationAgent.validate(diversified)[:top_k]

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
        )
