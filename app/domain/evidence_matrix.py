"""Evidence matrix builder: maps retrieved citations and structured facts to rubric criteria."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from app.models import Citation, ESGFact, EvidenceMatrixRow, RubricCriterion
from app.rubric import CRITERIA_DEFINITIONS

if TYPE_CHECKING:
    from app.domain.rubric_evaluator import RubricEvaluator


class EvidenceMatrixBuilder:
    """Build a comprehensive ESG evidence audit matrix across all rubric criteria."""

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
        """Build the evidence matrix for the supplied citations and facts."""
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

            # Match with extracted facts to enrich accurate numerical values
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
                )
            )
        return matrix

    def build_evidence_matrix(
        self,
        citations: list[Citation],
        facts: list[ESGFact],
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> list[EvidenceMatrixRow]:
        """Backward-compatible alias for build()."""
        return self.build(citations, facts, criteria_definitions=criteria_definitions)
