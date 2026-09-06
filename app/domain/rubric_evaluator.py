from typing import Literal

from app.models import (
    Citation,
    CriterionCitationRef,
    CriterionResult,
    ESGFact,
    EvidenceMatrixRow,
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


class RubricEvaluator:
    """Đánh giá chi tiết từng tiêu chí ESG dựa trên tập hợp bằng chứng trích dẫn."""

    def evaluate_criterion(
        self, criterion: RubricCriterion, citations: list[Citation]
    ) -> CriterionResult:
        """Đánh giá 1 tiêu chí bằng cách gộp bằng chứng từ nhiều citation."""
        keywords = criterion.retrieval_keywords or criterion.required_evidence
        relevant: list[Citation] = []
        for cite in citations:
            text = cite.excerpt.lower()
            matched_keywords = [req for req in keywords if req in text] or [
                unit for unit in criterion.metric_units if unit.lower() in text
            ]
            if matched_keywords:
                relevant.append(cite)

        if not relevant:
            return CriterionResult(
                criterion_id=criterion.id,
                status="missing",
                confidence=0.0,
                missing_fields=list(criterion.required_fields),
            )

        # Ưu tiên phát hiện mâu thuẫn trên bất kỳ đoạn liên quan nào
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

        matched_fields: list[str] = []
        missing_fields: list[str] = []
        best_cite = relevant[0]
        value: str | None = None
        year: int | None = None
        unit = criterion.metric_units[0] if criterion.metric_units else None

        for rf in criterion.required_fields:
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
                    if cite_value:
                        value = cite_value
                    if cite_year is not None:
                        year = cite_year
                    break
            if field_ok:
                matched_fields.append(rf)
            else:
                missing_fields.append(rf)

        if not value:
            metric_match = METRIC_PATTERN.search(best_cite.excerpt.lower())
            value = metric_match.group(0) if metric_match else None
        if year is None:
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

        return CriterionResult(
            criterion_id=criterion.id,
            status=status,
            value=value,
            unit=unit,
            reporting_year=year,
            citation=CriterionCitationRef(
                document=best_cite.document_name,
                page=best_cite.page,
                excerpt=best_cite.excerpt[:200],
                section=best_cite.section,
            ),
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
            res = self.rubric_evaluator.evaluate_criterion(criterion, evidence)
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
        self, citations: list[Citation]
    ) -> tuple[list[PillarResult], float]:
        """Đánh giá toàn bộ 3 trụ cột E, S, G."""
        if not citations:
            pillars = [self.evaluate_pillar(name, rubric, []) for name, rubric in RUBRICS.items()]
            return pillars, 0.0
        pillars = [
            self.evaluate_pillar(name, rubric, citations) for name, rubric in RUBRICS.items()
        ]
        overall_coverage = (
            round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1) if pillars else 0.0
        )
        return pillars, overall_coverage

    evaluate_all_pillars = evaluate_all


from app.domain.evidence_matrix import EvidenceMatrixBuilder
