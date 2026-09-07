"""Query intent classification and retrieval planning."""

from __future__ import annotations

from app.models import RetrievalPlan
from app.rubric import RUBRICS


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Kiểm tra xem đoạn văn bản có chứa ít nhất một từ khóa trong danh sách hay không."""
    return any(keyword in text for keyword in keywords)


class QueryPlanningAgent:
    """Turn a natural-language ESG request into an explicit retrieval contract."""

    def plan(
        self,
        question: str,
        mode: str = "qa",
        document_ids: list[str] | None = None,
    ) -> RetrievalPlan:
        lowered = question.lower()

        if any(w in lowered for w in ("compare", "versus", " vs ", "vs", "so sánh", "đối chiếu")):
            intent = "cross_document_compare"
            subqueries = [
                f"{question} Scope 1 Scope 2 greenhouse gas emissions",
                f"{question} net zero target baseline year",
                f"{question} external assurance independent auditor",
            ]
            required = [
                "scope_1_emissions",
                "scope_2_emissions",
                "net_zero_target",
                "assurance",
            ]
        elif any(
            w in lowered
            for w in (
                "trend",
                "trajectory",
                "yoy",
                "qua các năm",
                "lịch sử",
                "tiến trình",
                "timeline",
            )
        ):
            intent = "temporal_trend"
            subqueries = [
                f"{question} emissions yearly historical metrics",
                f"{question} baseline year reduction progress",
                f"{question} year over year trajectory",
            ]
            required = ["emissions", "baseline", "progress"]
        elif any(
            w in lowered
            for w in (
                "greenwash",
                "credible",
                "đáng tin",
                "tẩy xanh",
                "minh bạch",
                "ảo tưởng",
            )
        ):
            intent = "greenwashing_screening"
            subqueries = [
                f"{question} target year baseline year",
                f"{question} Scope 1 Scope 2 Scope 3 metrics tCO2e",
                f"{question} independent external assurance report",
                f"{question} interim target reduction pathway",
            ]
            required = ["target", "baseline", "emissions", "assurance"]
        elif mode == "audit" or any(
            w in lowered
            for w in ("audit", "kiểm toán", "đánh giá toàn diện", "coverage", "bao phủ")
        ):
            intent = "criterion_audit"
            subqueries = [
                f"{question} Scope 1 Scope 2 Scope 3 greenhouse gas emissions",
                f"{question} net zero target baseline year reduction",
                f"{question} worker safety injury TRIR training",
                f"{question} board oversight ethics anti-corruption compliance",
                f"{question} independent external assurance",
            ]
            required = ["emissions", "target", "safety", "governance", "assurance"]
        else:
            intent = "fact_lookup"
            matched_topics = [
                topic
                for rubric in RUBRICS.values()
                if _contains_any(lowered, rubric.topics)
                for topic in rubric.topics
            ]
            if not matched_topics:
                matched_topics = ["target", "baseline", "metrics", "assurance"]
            deduped_topics = list(dict.fromkeys(matched_topics))[:4]
            subqueries = [question, f"{question} {' '.join(deduped_topics)}"]
            required = deduped_topics

        return RetrievalPlan(
            intent=intent,
            subqueries=subqueries,
            required_evidence=required,
            document_scope=document_ids,
            temporal_scope="multi_year" if intent == "temporal_trend" else None,
        )
