from app.models import RetrievalPlan
from app.rubric import RUBRICS


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Kiểm tra xem đoạn văn bản có chứa ít nhất một từ khóa trong danh sách hay không."""
    return any(keyword in text for keyword in keywords)


class QueryPlanningAgent:
    """Năng lực Phân tích Ý định & Lập Kế hoạch Truy xuất (Query Planning & Intent Classifier).

    Nhiệm vụ:
    Phân rã câu hỏi tự nhiên phức tạp của người dùng thành RetrievalPlan gồm:
    - `intent`: Mục tiêu nghiệp vụ (fact_lookup, criterion_audit, cross_document_compare, greenwashing_screening, temporal_trend)
    - `subqueries`: Danh sách các truy vấn con đa góc nhìn (target, baseline, scope 1/2/3, assurance, metrics)
    - `required_evidence`: Danh mục bằng chứng bắt buộc cần tìm làm Quality Gate
    """

    def plan(
        self,
        question: str,
        mode: str = "qa",
        document_ids: list[str] | None = None,
    ) -> RetrievalPlan:
        lowered = question.lower()

        # 1. Nhận diện intent
        if any(w in lowered for w in ("compare", "versus", "vs", "so sánh", "đối chiếu")):
            intent = "cross_document_compare"
            subqueries = [
                f"{question} Scope 1 Scope 2 greenhouse gas emissions",
                f"{question} net zero target baseline year",
                f"{question} external assurance independent auditor",
            ]
            req = ["scope_1_emissions", "scope_2_emissions", "net_zero_target", "assurance"]

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
                f"{question} emissions 2021 2022 2023 2024 2025",
                f"{question} baseline year reduction progress",
                f"{question} year over year historical metrics",
            ]
            req = ["scope_1_emissions", "baseline", "progress"]

        elif any(
            w in lowered
            for w in ("greenwash", "credible", "đáng tin", "tẩy xanh", "minh bạch", "ảo tưởng")
        ):
            intent = "greenwashing_screening"
            subqueries = [
                f"{question} target year baseline year",
                f"{question} Scope 1 Scope 2 Scope 3 metrics tCO2e",
                f"{question} independent external assurance report",
                f"{question} interim target reduction pathway 2030",
            ]
            req = ["net_zero_target", "baseline", "scope_1_emissions", "assurance"]

        elif mode == "audit" or any(
            w in lowered
            for w in ("audit", "kiểm toán", "đánh giá toàn diện", "coverage", "bao phủ")
        ):
            intent = "criterion_audit"
            subqueries = [
                f"{question} Scope 1 Scope 2 Scope 3 greenhouse gas emissions tCO2e",
                f"{question} net zero target year baseline year reduction",
                f"{question} employee safety injury trir training hours",
                f"{question} board oversight ethics anti-corruption compliance",
                f"{question} independent external limited assurance",
            ]
            req = ["emissions", "net_zero_target", "safety", "governance", "assurance"]

        else:
            intent = "fact_lookup"
            # Tìm các topic liên quan trong rubric
            matched_topics = [
                topic
                for rubric in RUBRICS.values()
                if _contains_any(lowered, rubric.topics)
                for topic in rubric.topics
            ]
            if not matched_topics:
                matched_topics = ["target", "baseline", "metrics", "assurance"]
            subqueries = [
                question,
                f"{question} {' '.join(matched_topics[:4])}",
            ]
            req = matched_topics[:4]

        return RetrievalPlan(
            intent=intent,
            subqueries=subqueries,
            required_evidence=req,
            document_scope=document_ids,
            temporal_scope="multi_year" if intent == "temporal_trend" else None,
        )
