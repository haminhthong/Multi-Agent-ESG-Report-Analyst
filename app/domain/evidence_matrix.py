"""Xây ma trận bằng chứng từ citation, fact cấu trúc và tiêu chí rubric."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from app.models import (
    Citation,
    CriterionEvidenceBundle,
    ESGFact,
    EvidenceMatrixRow,
    RubricCriterion,
)
from app.rubric import CRITERIA_DEFINITIONS

if TYPE_CHECKING:
    from app.domain.rubric_evaluator import RubricEvaluator


class EvidenceMatrixBuilder:
    """Xây ma trận audit bằng chứng ESG cho toàn bộ tiêu chí rubric."""

    def __init__(self, rubric_evaluator: RubricEvaluator | Any | None = None) -> None:
        if rubric_evaluator is None:
            from app.domain.rubric_evaluator import RubricEvaluator

            rubric_evaluator = RubricEvaluator()
        self.rubric_evaluator = rubric_evaluator

    def build(
        self,
        citations: list[Citation],
        facts: list[ESGFact],
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> list[EvidenceMatrixRow]:
        """Xây ma trận từ citation và fact được truyền vào."""
        matrix: list[EvidenceMatrixRow] = []
        fact_by_metric: dict[str, ESGFact] = {}
        for f in facts:
            prev = fact_by_metric.get(f.metric)
            if prev is None or (f.confidence or 0) >= (prev.confidence or 0):
                fact_by_metric[f.metric] = f

        defs = criteria_definitions or CRITERIA_DEFINITIONS
        for criterion in defs:
            eval_res = self.rubric_evaluator.evaluate_criterion(criterion, citations, facts=facts)
            status: Literal[
                "found", "partial", "missing", "not_found", "contradicts", "unclear"
            ] = "missing"
            if eval_res.status in ("found", "partial", "contradicts", "unclear"):
                status = eval_res.status  # type: ignore[assignment]

            # Ưu tiên fact có độ tin cậy cao để hiển thị số liệu chuẩn hóa.
            matched_fact = None
            if "scope_1" in criterion.id.lower():
                matched_fact = fact_by_metric.get("scope_1_emissions")
            elif "scope_3" in criterion.id.lower():
                matched_fact = fact_by_metric.get("scope_3_emissions")
            elif "target" in criterion.id.lower():
                matched_fact = fact_by_metric.get("net_zero_target")
            elif "safety" in criterion.id.lower():
                matched_fact = fact_by_metric.get("work_safety")

            display_val = eval_res.value
            display_unit = eval_res.unit
            display_year = eval_res.reporting_year

            if matched_fact:
                display_val = (
                    str(matched_fact.value) if matched_fact.value is not None else display_val
                )
                display_unit = matched_fact.unit or display_unit
                display_year = matched_fact.year or display_year

            matrix.append(
                EvidenceMatrixRow(
                    criterion_id=criterion.id,
                    criterion_name=criterion.name,
                    pillar=criterion.pillar,
                    status=status,
                    value=display_val,
                    unit=display_unit,
                    reporting_year=display_year,
                    citation=eval_res.citation,
                    confidence=eval_res.confidence,
                    missing_fields=eval_res.missing_fields,
                    fact_ids=eval_res.fact_ids,
                    evidence_ids=eval_res.evidence_ids
                    or [
                        _citation_key(citation)
                        for citation in citations
                        if eval_res.citation
                        and citation.document_name == eval_res.citation.document
                        and citation.page == eval_res.citation.page
                    ],
                )
            )
        return matrix

    def build_scoped(
        self,
        citations: list[Citation],
        facts: list[ESGFact],
        bundles: list[CriterionEvidenceBundle],
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> list[EvidenceMatrixRow]:
        """Xây ma trận theo bundle, không cho phép một tiêu chí mượn evidence tiêu chí khác."""
        defs = criteria_definitions or CRITERIA_DEFINITIONS
        by_id = {criterion.id: criterion for criterion in defs}
        rows: list[EvidenceMatrixRow] = []
        for bundle in bundles:
            criterion = by_id.get(bundle.criterion_id)
            if criterion is None:
                continue
            citation_ids = set(bundle.citation_ids)
            scoped_citations = [
                citation for citation in citations if _citation_key(citation) in citation_ids
            ]
            fact_ids = set(bundle.fact_ids)
            scoped_facts = [
                fact
                for fact in facts
                if fact.fact_id in fact_ids
                or (fact.source is not None and _citation_key(fact.source) in citation_ids)
            ]
            rows.extend(self.build(scoped_citations, scoped_facts, [criterion]))
        return rows


def _citation_key(citation: Citation) -> str:
    """Dùng evidence id ổn định thay vì id numeric của chunk."""
    return (
        citation.evidence_id
        or citation.stable_chunk_id
        or (
            f"{citation.document_id}:p{citation.page}:{citation.block_id or citation.chunk_id or 'text'}"
        )
    )
