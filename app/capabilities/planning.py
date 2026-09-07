"""Query intent classification and retrieval planning."""

from __future__ import annotations

import re

from app.models import RetrievalPlan
from app.rubric import CLIMATE_CRITERIA_DEFINITIONS, RUBRICS


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
        criteria = self._infer_criteria(lowered)
        metrics = self._infer_metrics(lowered)
        reporting_years = sorted({int(year) for year in re.findall(r"\b20[12]\d\b", question)})

        if any(w in lowered for w in ("compare", "versus", " vs ", "vs", "so sánh", "đối chiếu")):
            intent = "cross_document_compare"
            topic_queries = [f"{question} {metric.replace('_', ' ')}" for metric in metrics]
            subqueries = topic_queries or [question]
            required = metrics or ["comparison_scope"]
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
            required = metrics or ["emissions", "baseline", "progress"]
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
            required = metrics or ["target", "baseline", "emissions", "assurance"]
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
            required = criteria or ["emissions", "target", "safety", "governance", "assurance"]
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

        if not subqueries:
            subqueries = [question]
        if intent == "cross_document_compare" and len(subqueries) < 3:
            subqueries.extend(
                [
                    f"{question} methodology boundary",
                    f"{question} independent external assurance",
                ][: 3 - len(subqueries)]
            )

        return RetrievalPlan(
            intent=intent,
            original_question=question,
            canonical_query=question,
            subqueries=subqueries,
            required_evidence=required,
            document_scope=document_ids,
            temporal_scope="multi_year" if intent == "temporal_trend" else None,
            criteria=criteria,
            metrics=metrics,
            reporting_years=reporting_years,
            requires_numeric=bool(metrics),
        )

    @staticmethod
    def _infer_criteria(question: str) -> list[str]:
        """Chỉ yêu cầu tiêu chí thực sự liên quan tới câu hỏi."""
        matched: list[str] = []
        for criterion in CLIMATE_CRITERIA_DEFINITIONS:
            keywords = [criterion.name.lower(), *criterion.retrieval_keywords]
            if any(keyword.lower() in question for keyword in keywords):
                matched.append(criterion.id)
        return list(dict.fromkeys(matched))

    @staticmethod
    def _infer_metrics(question: str) -> list[str]:
        """Ánh xạ chủ đề câu hỏi sang fact type để planner có scope rõ ràng."""
        metric_keywords = {
            "scope_1_emissions": ("scope 1", "scope1", "direct emission"),
            "scope_2_emissions": ("scope 2", "scope2", "indirect emission"),
            "scope_3_emissions": ("scope 3", "scope3", "value chain"),
            "net_zero_target": ("target", "net zero", "net-zero", "baseline", "pathway"),
            "renewable_energy": ("renewable", "mwh", "gwh", "electricity"),
            "work_safety": ("safety", "injury", "trir", "fatality"),
            "gender_diversity": ("gender", "women", "female", "diversity"),
            "supplier_assessment": ("supplier", "supply chain", "vendor"),
        }
        return [
            metric
            for metric, keywords in metric_keywords.items()
            if _contains_any(question, keywords)
        ]
