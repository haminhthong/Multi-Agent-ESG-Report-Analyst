"""Company comparison service: evaluates cross-company ESG performance using scoped evidence."""

from __future__ import annotations

from typing import Any

from app.domain.evidence_matrix import EvidenceMatrixBuilder
from app.domain.rubric_evaluator import RubricEvaluator
from app.facts.repository import FactRepository
from app.models import Citation, CompanyComparisonCriterion, CompanyComparisonResult, ESGFact
from app.rubric import CRITERIA_DEFINITIONS, RubricCriterion, resolve_criterion_id
from app.store import Store


class CompanyComparisonService:
    """Evaluate and compare ESG disclosure quality across companies using standardized rubrics."""

    def __init__(
        self,
        rubric_evaluator: RubricEvaluator | None = None,
        evidence_matrix_builder: EvidenceMatrixBuilder | None = None,
    ) -> None:
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()
        self.evidence_matrix_builder = evidence_matrix_builder or EvidenceMatrixBuilder(
            self.rubric_evaluator
        )

    def compare(
        self,
        companies: list[str],
        store: Store | None = None,
        company_documents: dict[str, list[str]] | None = None,
        criteria_ids: list[str] | None = None,
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> CompanyComparisonResult:
        """So sánh theo fact accepted, không trích xuất candidate trong request."""
        defs = criteria_definitions or CRITERIA_DEFINITIONS
        requested_ids = (
            {resolve_criterion_id(value) for value in criteria_ids}
            if criteria_ids is not None
            else None
        )
        target_criteria = [c for c in defs if requested_ids is None or c.id in requested_ids]
        comp_rows: list[CompanyComparisonCriterion] = []
        coverage_summary: dict[str, float] = {}
        fact_repository = FactRepository(store) if store else None

        def accepted_facts(company: str) -> list[ESGFact]:
            if fact_repository is None:
                return []
            scoped_doc_ids = company_documents.get(company) if company_documents else None
            facts = fact_repository.query_facts(company=company)
            if scoped_doc_ids:
                facts = [fact for fact in facts if fact.document_id in scoped_doc_ids]
            return facts

        def fact_citations(facts: list[ESGFact]) -> list[Citation]:
            return [fact.source for fact in facts if fact.source is not None]

        for company in companies:
            facts = accepted_facts(company)
            cites = fact_citations(facts)
            matrix = self.evidence_matrix_builder.build(cites, facts, target_criteria)
            found_count = sum(1 for m in matrix if m.status == "found")
            partial_count = sum(1 for m in matrix if m.status == "partial")
            cov = round(
                ((found_count + 0.5 * partial_count) / max(1, len(matrix))) * 100,
                1,
            )
            coverage_summary[company] = cov

        for crit in target_criteria:
            row_dict: dict[str, Any] = {}
            for company in companies:
                facts_crit = accepted_facts(company)
                cites = fact_citations(facts_crit)
                eval_res = self.rubric_evaluator.evaluate_criterion(crit, cites, facts=facts_crit)
                row_dict[company] = {
                    "status": eval_res.status,
                    "value": eval_res.value,
                    "page": eval_res.citation.page if eval_res.citation else None,
                    "confidence": eval_res.confidence,
                }

            comp_rows.append(
                CompanyComparisonCriterion(
                    criterion_id=crit.id,
                    criterion_name=crit.name,
                    pillar=crit.pillar,
                    values_by_company=row_dict,
                )
            )

        findings = [
            f"So sánh {len(companies)} doanh nghiệp: "
            + ", ".join(f"{c}: {cov}% coverage" for c, cov in coverage_summary.items())
        ]
        return CompanyComparisonResult(
            companies=companies,
            criteria_matrix=comp_rows,
            coverage_summary=coverage_summary,
            findings=findings,
        )

    def run_comparison(
        self,
        companies: list[str],
        store: Store,
        criteria_ids: list[str] | None = None,
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> CompanyComparisonResult:
        """Backward-compatible entry point delegating to compare()."""
        return self.compare(
            companies=companies,
            store=store,
            criteria_ids=criteria_ids,
            criteria_definitions=criteria_definitions,
        )
