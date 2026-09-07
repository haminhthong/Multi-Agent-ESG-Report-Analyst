from typing import Literal

from app.models import (
    Citation,
    CriterionCitationRef,
    CriterionResult,
    ESGFact,
    PillarResult,
    RubricCriterion,
)
from app.rubric import (
    ASSURANCE_PATTERN,
    BASELINE_PATTERN,
    CRITERIA_DEFINITIONS,
    METRIC_PATTERN,
    NEGATED_ASSURANCE_PATTERN,
    NEGATED_BASELINE_PATTERN,
    NEGATED_PERFORMANCE_PATTERN,
    RUBRICS,
    TARGET_PATTERN,
    YEAR_PATTERN,
    PillarRubric,
)
from app.domain.evidence_matrix import EvidenceMatrixBuilder

__all__ = [
    "RubricEvaluator",
    "PillarEvaluator",
    "EvidenceMatrixBuilder",
]


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _field_matched_in_text(
    rf: str, text: str, criterion: RubricCriterion, value: str | None, year: int | None
) -> bool:
    """Kiểm tra một required_field có mặt trong một đoạn text hay không."""
    rf_l = rf.lower()
    if "year" in rf_l:
        return year is not None
    if "unit" in rf_l:
        return any(u.lower() in text for u in criterion.metric_units)
    if "scope_1" in rf_l:
        return "scope 1" in text and value is not None
    if "scope_2" in rf_l:
        return "scope 2" in text and value is not None
    if "scope_3" in rf_l:
        return "scope 3" in text and value is not None
    if any(k in rf_l for k in ("value", "rate", "percentage", "count")):
        return value is not None
    if "target" in rf_l:
        return bool(
            TARGET_PATTERN.search(text)
            or any(t in text for t in ("net zero", "net-zero", "target", "goal"))
        )
    if "baseline" in rf_l:
        return bool(BASELINE_PATTERN.search(text) and not NEGATED_BASELINE_PATTERN.search(text))
    if "assurance" in rf_l:
        return bool(ASSURANCE_PATTERN.search(text) and not NEGATED_ASSURANCE_PATTERN.search(text))
    return any(term in text for term in rf_l.split("_") if term)


CRITERION_FACT_MAP: dict[str, list[str]] = {
    "E_GHG_SCOPE_1_2": ["scope_1_emissions", "scope_2_emissions"],
    "E_GHG_SCOPE_3": ["scope_3_emissions"],
    "E_TARGET_SETTING": ["net_zero_target"],
    "E_RENEWABLE_ENERGY": ["renewable_energy"],
    "S_HEALTH_SAFETY": ["work_safety"],
    "S_DIVERSITY_INCLUSION": ["gender_diversity"],
    "S_SUPPLY_CHAIN_LABOR": ["supplier_assessment"],
}


class RubricEvaluator:
    """Đánh giá chi tiết từng tiêu chí ESG dựa trên Fact-First (ưu tiên ESGFact) kết hợp Citation provenance."""

    def evaluate_criterion(
        self,
        criterion: RubricCriterion,
        citations: list[Citation],
        facts: list[ESGFact] | None = None,
    ) -> CriterionResult:
        """Đánh giá 1 tiêu chí: ưu tiên Fact-first rồi mới fallback về quét text regex trên citation."""
        keywords = criterion.retrieval_keywords or criterion.required_evidence
        relevant: list[Citation] = []
        for cite in citations:
            text = cite.excerpt.lower()
            matched_keywords = [req for req in keywords if req in text] or [
                unit for unit in criterion.metric_units if unit.lower() in text
            ]
            if matched_keywords:
                relevant.append(cite)

        # 1. Fact-First Evaluation: Kiểm tra trực tiếp trên structured ESGFact
        matched_fields: list[str] = []
        missing_fields: list[str] = []
        value: str | None = None
        year: int | None = None
        unit = criterion.metric_units[0] if criterion.metric_units else None
        best_cite: Citation | None = (
            relevant[0] if relevant else (citations[0] if citations else None)
        )

        expected_metric_keys = CRITERION_FACT_MAP.get(criterion.id, [])
        relevant_facts = [
            f
            for f in (facts or [])
            if any(k in f.metric.lower() for k in expected_metric_keys)
            or any(kw in f.metric.lower() for kw in keywords)
        ]

        if relevant_facts:
            # Fact có độ tin cậy cao nhất
            top_fact = max(relevant_facts, key=lambda f: f.confidence)
            if top_fact.source:
                best_cite = top_fact.source
            if top_fact.value is not None:
                value = str(top_fact.value)
            if top_fact.year is not None:
                year = top_fact.year
            if top_fact.unit:
                unit = top_fact.unit

            for rf in criterion.required_fields:
                rf_l = rf.lower()
                field_satisfied = False
                if "scope_1" in rf_l:
                    field_satisfied = any(
                        "scope_1" in f.metric and f.value is not None for f in relevant_facts
                    )
                elif "scope_2" in rf_l:
                    field_satisfied = any(
                        "scope_2" in f.metric and f.value is not None for f in relevant_facts
                    )
                elif "scope_3" in rf_l:
                    field_satisfied = any(
                        "scope_3" in f.metric and f.value is not None for f in relevant_facts
                    )
                elif any(k in rf_l for k in ("value", "rate", "percentage", "count", "trir")):
                    field_satisfied = any(f.value is not None for f in relevant_facts)
                elif "year" in rf_l:
                    field_satisfied = any(f.year is not None for f in relevant_facts)
                elif "unit" in rf_l:
                    field_satisfied = any(bool(f.unit or f.normalized_unit) for f in relevant_facts)
                elif "target" in rf_l:
                    field_satisfied = any("target" in f.metric for f in relevant_facts)
                elif "baseline" in rf_l:
                    field_satisfied = any(f.baseline_year is not None for f in relevant_facts)

                if field_satisfied:
                    matched_fields.append(rf)
                else:
                    missing_fields.append(rf)

        if not relevant and not relevant_facts:
            return CriterionResult(
                criterion_id=criterion.id,
                status="missing",
                confidence=0.0,
                missing_fields=list(criterion.required_fields),
            )

        # 2. Phát hiện mâu thuẫn / phủ định trên các đoạn trích dẫn liên quan
        for cite in relevant:
            text = cite.excerpt.lower()
            if criterion.id == "G_EXTERNAL_ASSURANCE" and NEGATED_ASSURANCE_PATTERN.search(text):
                return CriterionResult(
                    criterion_id=criterion.id,
                    status="contradicts",
                    citation=CriterionCitationRef(
                        document=cite.document_name,
                        page=cite.page,
                        excerpt=cite.excerpt[:200],
                        section=cite.section,
                    ),
                    confidence=0.85,
                    missing_fields=list(criterion.required_fields),
                )
            if NEGATED_PERFORMANCE_PATTERN.search(text):
                return CriterionResult(
                    criterion_id=criterion.id,
                    status="contradicts",
                    citation=CriterionCitationRef(
                        document=cite.document_name,
                        page=cite.page,
                        excerpt=cite.excerpt[:200],
                        section=cite.section,
                    ),
                    confidence=0.8,
                    missing_fields=list(criterion.required_fields),
                )

        # 3. Fallback: Nếu Fact-first chưa đủ hoặc không có facts, quét regex bổ sung trên citations
        if missing_fields or not relevant_facts:
            remaining_missing = (
                list(missing_fields) if relevant_facts else list(criterion.required_fields)
            )
            missing_fields = []
            for rf in remaining_missing:
                field_ok = False
                for cite in relevant:
                    text = cite.excerpt.lower()
                    metric_match = METRIC_PATTERN.search(text)
                    cite_value = metric_match.group(0) if metric_match else None
                    year_match = YEAR_PATTERN.search(text)
                    cite_year = int(year_match.group(0)) if year_match else None
                    if _field_matched_in_text(rf, text, criterion, cite_value, cite_year):
                        field_ok = True
                        best_cite = cite
                        if cite_value and not value:
                            value = cite_value
                        if cite_year is not None and year is None:
                            year = cite_year
                        break
                if field_ok:
                    if rf not in matched_fields:
                        matched_fields.append(rf)
                else:
                    missing_fields.append(rf)

        if not value and best_cite:
            metric_match = METRIC_PATTERN.search(best_cite.excerpt.lower())
            value = metric_match.group(0) if metric_match else None
        if year is None and best_cite:
            year_match = YEAR_PATTERN.search(best_cite.excerpt.lower())
            year = int(year_match.group(0)) if year_match else None

        if not missing_fields and matched_fields:
            status: Literal[
                "found", "partial", "not_found", "missing", "contradicts", "unclear"
            ] = "found"
            confidence = 0.95
        elif matched_fields:
            status = "partial"
            confidence = 0.75
        else:
            status = "partial" if value or year else "unclear"
            confidence = 0.50

        cite_ref = (
            CriterionCitationRef(
                document=best_cite.document_name,
                page=best_cite.page,
                excerpt=best_cite.excerpt[:200],
                section=best_cite.section,
            )
            if best_cite
            else None
        )

        return CriterionResult(
            criterion_id=criterion.id,
            status=status,
            value=value,
            unit=unit,
            reporting_year=year,
            citation=cite_ref,
            confidence=confidence,
            matched_fields=matched_fields,
            missing_fields=missing_fields,
        )


class PillarEvaluator:
    """Đánh giá toàn diện theo từng trụ cột E, S, G."""

    def __init__(self, rubric_evaluator: RubricEvaluator | None = None):
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()

    def evaluate_pillar(
        self,
        name: str,
        rubric: PillarRubric,
        citations: list[Citation],
        criteria_definitions: list[RubricCriterion] | None = None,
        facts: list[ESGFact] | None = None,
    ) -> PillarResult:
        evidence = [
            item for item in citations if _contains_any(item.excerpt.lower(), rubric.topics)
        ]
        text = " ".join(item.excerpt.lower() for item in evidence)

        defs = criteria_definitions or CRITERIA_DEFINITIONS
        pillar_criteria = [c for c in defs if c.pillar == name]
        criteria_results: list[CriterionResult] = []
        found_count = 0
        partial_count = 0

        for criterion in pillar_criteria:
            res = self.rubric_evaluator.evaluate_criterion(criterion, evidence, facts=facts)
            criteria_results.append(res)
            if res.status == "found":
                found_count += 1
            elif res.status == "partial":
                partial_count += 1

        total_criteria = len(pillar_criteria) if pillar_criteria else len(rubric.criteria)
        disclosure_coverage = (
            round(((found_count + 0.5 * partial_count) / total_criteria) * 100, 1)
            if total_criteria > 0
            else 0.0
        )

        metrics = len(METRIC_PATTERN.findall(text))
        data_completeness = round(min(100.0, (metrics / max(1, total_criteria)) * 50.0), 1)

        quality_checks = [
            bool(METRIC_PATTERN.search(text)),
            bool(YEAR_PATTERN.search(text)),
            bool(BASELINE_PATTERN.search(text)) and not bool(NEGATED_BASELINE_PATTERN.search(text)),
            bool(ASSURANCE_PATTERN.search(text))
            and not bool(NEGATED_ASSURANCE_PATTERN.search(text)),
        ]
        evidence_quality = (
            round((sum(quality_checks) / len(quality_checks)) * 100, 1) if evidence else 0.0
        )
        confidence = round(min(1.0, len(evidence) / 4) * (evidence_quality / 100.0), 2)

        findings = [
            f"Hệ thống tìm thấy bằng chứng cho {found_count} tiêu chí đầy đủ và {partial_count} tiêu chí một phần trên {total_criteria} tiêu chí thuộc trụ cột {name}.",
            f"Ghi nhận {metrics} số liệu định lượng có đơn vị đo lường.",
        ]

        risks = []
        if not evidence:
            risks.append(
                f"Không tìm thấy đoạn văn bản bằng chứng liên quan đến trụ cột {name} trong các đoạn đã truy xuất."
            )
        elif metrics == 0:
            risks.append(
                "Các bằng chứng đã tìm thấy mới ở dạng mô tả định tính, thiếu số liệu đo lường cụ thể."
            )
        if evidence and (
            not ASSURANCE_PATTERN.search(text) or NEGATED_ASSURANCE_PATTERN.search(text)
        ):
            risks.append(
                "Chưa tìm thấy tuyên bố bảo đảm độc lập (External Assurance) cho dữ liệu này."
            )

        return PillarResult(
            pillar=name,
            score=disclosure_coverage,
            disclosure_coverage=disclosure_coverage,
            evidence_quality=evidence_quality,
            data_completeness=data_completeness,
            confidence=confidence,
            criteria_results=criteria_results,
            findings=findings,
            risks=risks,
            citations=evidence[:4],
        )

    def evaluate_all(
        self,
        citations: list[Citation],
        facts: list[ESGFact] | None = None,
    ) -> tuple[list[PillarResult], float]:
        """Đánh giá toàn bộ 3 trụ cột E, S, G."""
        if not citations and not facts:
            pillars = [self.evaluate_pillar(name, rubric, []) for name, rubric in RUBRICS.items()]
            return pillars, 0.0
        pillars = [
            self.evaluate_pillar(name, rubric, citations, facts=facts)
            for name, rubric in RUBRICS.items()
        ]
        overall_coverage = (
            round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1) if pillars else 0.0
        )
        return pillars, overall_coverage

    evaluate_all_pillars = evaluate_all
